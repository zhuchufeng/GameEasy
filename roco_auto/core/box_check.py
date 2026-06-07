# -*- coding: utf-8 -*-
"""BoxCheck 开箱检测引擎 — 监测敌方头像区域，捕获宠物结果。

状态机:
  IDLE → ARMED → WAITING → CAPTURING → COOLDOWN → ARMED → ...

触发条件: 监测区域内匹配到模板(1.png/2.png/3.png) → 等待模板消失 →
         延时三连截图 → 裁剪结果区域 → 冷却 → 重新布防。

使用 ScreenCapture (mss) 进行快速屏幕捕获。
"""

import os
import time
import threading
import ctypes
from collections import deque
from datetime import datetime

import cv2
import numpy as np
from PIL import Image

from roco_auto.core.screen_capture import ScreenCapture
from roco_auto.core.config_manager import resolve_model_path, get_app_dir


def _set_dpi_aware():
    """避免 Windows DPI 缩放导致坐标错位。"""
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class BoxCheckEngine:
    """开箱检测核心引擎，纯逻辑层，不依赖任何 GUI 框架。"""

    IDLE = "idle"
    ARMED = "armed"
    WAITING = "waiting"
    CAPTURING = "capturing"
    COOLDOWN = "cooldown"

    def __init__(self):
        self._templates: list[dict] = []
        self._monitor_region: tuple | None = None
        self._capture = ScreenCapture()

        # ── 可调参数 ──
        self.check_interval: float = 0.12
        self.post_detect_delays: tuple = (0.7,)       # single shot after disappear
        self.disappear_confirm_frames: int = 5         # frames without detection to confirm
        self.appear_confirm_frames: int = 2
        self.rearm_miss_frames: int = 5
        self.cooldown_after_success: float = 3.0
        self.yolo_confidence: float = 0.3
        self.yolo_classes: list[str] = ['chest_blue','chest_red','chest_yellow']
        self._yolo = None
        # Crop region for screenshots (ratios, resolution-independent)
        self.crop_rx1: float = 0.0
        self.crop_ry1: float = 0.0
        self.crop_rx2: float = 1.0
        self.crop_ry2: float = 1.0
        self.save_to_folder: str = ""
        self.save_prefix: str = "boxcheck"

        # ── 运行时状态 (protected by _lock) ──
        self._lock = threading.Lock()
        self._running = False
        self._stop_flag = False
        self._thread: threading.Thread | None = None
        self._state = self.IDLE

        # ── 异步保存队列 — 监控线程入队，写入线程落盘，互不阻塞 ──
        self._save_queue: deque = deque()
        self._save_thread: threading.Thread | None = None
        self._save_stop = threading.Event()

        self.check_count: int = 0
        self.capture_count: int = 0
        self.start_time: float = 0.0
        self.last_detected_name: str = ""
        self.last_detected_score: float = 0.0

        # ── 回调 ──
        self.on_status: callable | None = None
        self.on_result: callable | None = None
        self.on_detected: callable | None = None

        _set_dpi_aware()

    # ═══════════════════════════════════════ 属性 ═══

    @property
    def state(self) -> str:
        return self._state

    @property
    def monitor_region(self) -> tuple | None:
        return self._monitor_region

    # ═══════════════════════════════════════ 模板 ═══

    def load_templates(self, paths: list[str]) -> int:
        """Load template images. Uses np.fromfile for Unicode path support.
        Supports both absolute and relative paths (relative to app dir)."""
        self._templates = []
        for path in paths:
            if not path or not path.strip():
                continue
            # Resolve path: try absolute first, then relative to app dir
            resolved = path
            if not os.path.isabs(path):
                resolved = os.path.join(get_app_dir(), path)
            if not os.path.exists(resolved):
                # Try under models/ directory
                resolved = os.path.join(get_app_dir(), "models", os.path.basename(path))
            if not os.path.exists(resolved):
                import logging
                logging.getLogger(__name__).warning("Template not found: %s", path)
                continue
            try:
                data = np.fromfile(resolved, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            except Exception:
                continue
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            self._templates.append({
                "path": resolved, "name": os.path.basename(resolved),
                "gray": gray, "w": w, "h": h,
            })
        return len(self._templates)
    @property
    def template_names(self) -> list[str]:
        return [t["name"] for t in self._templates]

    @property
    def template_count(self) -> int:
        return len(self._templates)

    # ═══════════════════════════════════════ 监测区域 ═══

    def set_monitor_region(self, left: int, top: int, right: int, bottom: int):
        if left < right and top < bottom:
            self._monitor_region = (left, top, right, bottom)

    def set_monitor_region_from_window(self, win: dict, rx1: float, ry1: float,
                                        rx2: float, ry2: float):
        """根据窗口矩形和相对坐标设置监测区域。"""
        left = int(win["left"] + win["width"] * rx1)
        top = int(win["top"] + win["height"] * ry1)
        right = int(win["left"] + win["width"] * rx2)
        bottom = int(win["top"] + win["height"] * ry2)
        self.set_monitor_region(left, top, right, bottom)

    # ═══════════════════════════════════════ 控制 (thread-safe) ═══

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Start monitoring. Auto-loads YOLO model and sets full-screen region."""
        with self._lock:
            if self._running:
                return False
            if not self.using_yolo:
                self._emit_status("Error: no YOLO model loaded")
                return False
            # Full screen as monitoring region
            screen_w, screen_h = self._capture.get_screen_size()
            self._monitor_region = (0, 0, screen_w, screen_h)
            if not self._monitor_region:
                self._emit_status("错误：未设置监测区域")
                return False

            self._stop_flag = False
            self._running = True
            self.check_count = 0
            self.capture_count = 0
            self.start_time = time.time()
            self._state = self.ARMED

            # 启动异步保存线程
            self._save_stop.clear()
            self._save_thread = threading.Thread(
                target=self._save_worker, daemon=True, name="boxcheck-save"
            )
            self._save_thread.start()

            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            self._emit_status("监测已启动...")
            return True

    def stop(self):
        """停止监测。"""
        with self._lock:
            self._stop_flag = True
            self._running = False
            self._state = self.IDLE
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        # 停止异步保存线程 — 先排空队列再退出
        self._save_stop.set()
        if self._save_thread is not None and self._save_thread.is_alive():
            self._save_thread.join(timeout=5.0)
        self._emit_status("监测已停止")

    # ═══════════════════════════════════════ 回调 ═══

    def _emit_status(self, text: str):
        try:
            if self.on_status:
                self.on_status(text)
        except Exception:
            pass

    def _emit_result(self, image, info: str):
        try:
            if self.on_result:
                self.on_result(image, info)
        except Exception:
            pass

    def _emit_detected(self, name: str, score: float):
        try:
            self.last_detected_name = name
            self.last_detected_score = score
            if self.on_detected:
                self.on_detected(name, score)
        except Exception:
            pass

    # ═══════════════════════════════════════ YOLO 检测 ═══

    def load_yolo(self, model_path: str, confidence: float = 0.5) -> bool:
        """Load a YOLO ONNX model. Returns True on success."""
        self.yolo_model = model_path
        self.yolo_confidence = confidence
        try:
            from roco_auto.core.yolo_detector import YoloDetector
            self._yolo = YoloDetector(model_path, confidence=confidence)
            ok = self._yolo.load()
            if ok:
                self.yolo_classes = self._yolo.class_names
            return ok
        except Exception:
            return False

    @property
    def using_yolo(self) -> bool:
        return self._yolo is not None and self._yolo.is_loaded

    def _detect_yolo(self, region_img: Image.Image) -> dict | None:
        """Run YOLO on the monitoring region, return best matching detection.

        Converts PIL → numpy → YOLO inference → filter to yolo_classes.
        Returns None if nothing detected.
        """
        if not self.using_yolo:
            return None
        import numpy as np
        img = np.array(region_img.convert("RGB"))
        # YOLO expects BGR
        img_bgr = img[:, :, ::-1]
        # Preprocess + infer directly (bypass full-screen capture)
        input_tensor = self._yolo._preprocess(img_bgr)
        outputs = self._yolo._session.run(None, {self._yolo._input_name: input_tensor})
        detections = self._yolo._postprocess(outputs, img_bgr.shape[1], img_bgr.shape[0], self.yolo_confidence)
        # Filter to configured classes
        detections = [d for d in detections if d["class"] in self.yolo_classes]
        if not detections:
            return None
        best = max(detections, key=lambda d: d["confidence"])
        # Convert center coords to top-left for compatibility with existing code
        best["x"] = best["x"] - best["w"] // 2
        best["y"] = best["y"] - best["h"] // 2
        best["score"] = best["confidence"]
        best["name"] = best["class"]
        return best

    # ═══════════════════════════════════════ 模板匹配 ═══

    def _locate_template(self, pil_img: Image.Image, template_gray) -> dict | None:
        """在 PIL 图片中匹配单个模板。"""
        img_rgb = pil_img.convert("RGB")
        img_gray = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2GRAY)

        th, tw = template_gray.shape[:2]
        ih, iw = img_gray.shape[:2]
        if iw < tw or ih < th:
            return None

        result = cv2.matchTemplate(img_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= self.match_threshold:
            return {"x": int(max_loc[0]), "y": int(max_loc[1]), "score": float(max_val)}
        return None

    def _locate_any(self, pil_img: Image.Image) -> dict | None:
        """匹配所有模板，返回最高分匹配。"""
        best = None
        for tpl in self._templates:
            found = self._locate_template(pil_img, tpl["gray"])
            if found:
                found.update({
                    "path": tpl["path"], "name": tpl["name"],
                    "w": tpl["w"], "h": tpl["h"],
                })
                if best is None or found["score"] > best["score"]:
                    best = found
        return best

    # ═══════════════════════════════════════ 裁剪 ═══

    def _crop_result(self, full_img: Image.Image, top_right_x: int,
                      top_right_y: int) -> Image.Image | None:
        """以模板右上角为基准，根据偏移量计算裁剪区域。"""
        ax = top_right_x + self.point_a_offset[0]
        ay = top_right_y + self.point_a_offset[1]
        bx = top_right_x + self.point_b_offset[0]
        by = top_right_y + self.point_b_offset[1]

        left = min(ax, bx)
        top = min(ay, by)
        right = max(ax, bx)
        bottom = max(ay, by)

        screen_w, screen_h = full_img.size
        left = max(0, min(screen_w, left))
        right = max(0, min(screen_w, right))
        top = max(0, min(screen_h, top))
        bottom = max(0, min(screen_h, bottom))

        if right <= left or bottom <= top:
            return None
        return full_img.crop((left, top, right, bottom))

    # ═══════════════════════════════════════ 截图 ═══

    def _screenshot_full(self) -> Image.Image:
        """全屏截图 (mss → numpy → PIL RGB)。"""
        bgr = self._capture.capture_full()
        # BGR → RGB
        return Image.fromarray(bgr[:, :, ::-1], mode="RGB")

    def _screenshot_region(self, region: tuple) -> Image.Image:
        """区域截图 (left, top, right, bottom) → PIL RGB。"""
        left, top, right, bottom = region
        w, h = right - left, bottom - top
        bgr = self._capture.capture_region((left, top, w, h))
        return Image.fromarray(bgr[:, :, ::-1], mode="RGB")

    # ═══════════════════════════════════════ 延迟捕获 ═══

    def _capture_one(self, delay: float, detected_top_right: tuple) -> dict:
        """Capture cropped region after delay (ratio-based, resolution-independent)."""
        full_img = self._screenshot_full()
        w, h = full_img.size
        left = int(w * self.crop_rx1)
        top = int(h * self.crop_ry1)
        right = int(w * self.crop_rx2)
        bottom = int(h * self.crop_ry2)
        left, right = max(0, min(w, left)), max(0, min(w, right))
        top, bottom = max(0, min(h, top)), max(0, min(h, bottom))
        if right > left and bottom > top:
            cropped = full_img.crop((left, top, right, bottom))
        else:
            cropped = full_img
        return {
            "delay": delay,
            "cropped": cropped,
            "top_right": detected_top_right,
            "source": f"crop({left},{top},{right},{bottom})",
        }

    # ═══════════════════════════════════════ 异步保存 ═══

    def _save_worker(self):
        """后台写入线程：从队列取图落盘，永不阻塞监控循环。"""
        while not self._save_stop.is_set():
            try:
                # 非阻塞取队首；队列为空时短暂休眠
                if self._save_queue:
                    item = self._save_queue.popleft()
                else:
                    time.sleep(0.05)
                    continue
            except IndexError:
                time.sleep(0.05)
                continue
            except Exception:
                time.sleep(0.1)
                continue

            try:
                combined = item["combined"]
                captures = item["captures"]
                folder = item["folder"]
                prefix = item["prefix"]
                ts = item["ts"]

                os.makedirs(folder, exist_ok=True)
                fname = f"{prefix}_{ts}.png"
                fpath = os.path.join(folder, fname)
                combined.save(fpath, "PNG")
                for i, c in enumerate(captures):
                    single_path = os.path.join(folder, f"{prefix}_{ts}_{i + 1}.png")
                    c["cropped"].save(single_path, "PNG")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("BoxCheck save failed: %s", e)

    def _capture_fixed_region(self, delay: float) -> dict:
        """Capture using the user-selected fixed crop region (window-relative ratios)."""
        full_img = self._screenshot_full()
        w, h = full_img.size
        left = int(w * self.crop_rx1)
        top = int(h * self.crop_ry1)
        right = int(w * self.crop_rx2)
        bottom = int(h * self.crop_ry2)
        left = max(0, min(w, left))
        right = max(0, min(w, right))
        top = max(0, min(h, top))
        bottom = max(0, min(h, bottom))
        if right <= left or bottom <= top:
            return {"delay": delay, "cropped": None, "top_right": (0, 0), "source": "fixed"}
        cropped = full_img.crop((left, top, right, bottom))
        return {
            "delay": delay,
            "cropped": cropped,
            "top_right": (left, top),
            "source": f"固定区域({left},{top},{right},{bottom})",
        }

    def _delayed_capture(self, detected_top_right: tuple):
        """Delayed screenshot → async save."""
        trigger_time = time.time()
        captures = []
        self._state = self.CAPTURING

        for i, delay in enumerate(self.post_detect_delays):
            wait_sec = trigger_time + delay - time.time()
            if wait_sec > 0:
                time.sleep(wait_sec)
            if self._stop_flag:
                return
            self._emit_status(f"Capturing screenshot (delay {delay:.1f}s)...")
            result = self._capture_one(delay, detected_top_right)
            if result["cropped"] is not None:
                captures.append(result)

        if not captures:
            self._emit_status("截图裁剪失败，继续监测...")
            return

        # Use first (and only) capture
        result_img = captures[0]["cropped"].convert("RGB")
        info = f"{captures[0]['delay']:.2f}s:{captures[0]['source']}"

        # Async save
        if self.save_to_folder:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._save_queue.append({
                "combined": result_img,
                "captures": captures,
                "folder": self.save_to_folder,
                "prefix": self.save_prefix,
                "ts": ts,
            })
            info += f"  <- saved {ts}"

        self.capture_count += 1
        self._emit_result(result_img, info)
        self._emit_status(f"screenshot done | {info}")

    # ═══════════════════════════════════════ 主循环 ═══

    def _monitor_loop(self):
        """后台监测主循环（状态机）。"""
        armed = True
        waiting_for_disappear = False
        capture_in_progress = False
        cooldown_until = 0.0
        miss_frames = 0
        disappear_miss_frames = 0
        appear_frames = 0  # consecutive frames with detection
        last_detected_top_right = None
        last_status_time = 0.0

        while not self._stop_flag:
            try:
                now = time.time()

                # 冷却检查
                cooldown_left = cooldown_until - now
                if cooldown_left > 0:
                    self._state = self.COOLDOWN
                    time.sleep(self.check_interval)
                    continue
                elif cooldown_until > 0:
                    cooldown_until = 0.0
                    armed = True
                    waiting_for_disappear = False
                    miss_frames = 0
                    disappear_miss_frames = 0
                    appear_frames = 0
                    last_detected_top_right = None
                    self._state = self.ARMED
                    self._emit_status("冷却结束，恢复检测...")

                if self._monitor_region is None:
                    time.sleep(0.5)
                    continue

                # YOLO 检测
                region_img = self._screenshot_region(self._monitor_region)
                found = self._detect_yolo(region_img) if self.using_yolo else None

                should_start_capture = False
                capture_top_right = None

                if found:
                    match_left_x = self._monitor_region[0] + found["x"]
                    match_top_y = self._monitor_region[1] + found["y"]
                    top_right_x = match_left_x + found["w"]
                    top_right_y = match_top_y

                    miss_frames = 0
                    disappear_miss_frames = 0
                    appear_frames += 1
                    last_detected_top_right = (top_right_x, top_right_y)

                    if armed and not capture_in_progress and appear_frames >= self.appear_confirm_frames:
                        armed = False
                        waiting_for_disappear = True
                        self._state = self.WAITING
                        last_status_time = 0.0
                        self._emit_detected(found["name"], found["score"])

                    if waiting_for_disappear and now - last_status_time >= 1.0:
                        last_status_time = now
                        self._emit_status(f"识别到 {found['name']} (match={found['score']:.3f})，等待消失...")

                else:
                    appear_frames = 0
                    if waiting_for_disappear and not capture_in_progress:
                        disappear_miss_frames += 1
                        if disappear_miss_frames >= self.disappear_confirm_frames:
                            waiting_for_disappear = False
                            capture_in_progress = True
                            armed = False
                            miss_frames = 0
                            if last_detected_top_right:
                                capture_top_right = last_detected_top_right
                                should_start_capture = True
                            else:
                                capture_in_progress = False
                                armed = True
                    elif not capture_in_progress:
                        miss_frames += 1
                        if miss_frames >= self.rearm_miss_frames:
                            armed = True
                            self._state = self.ARMED

                if should_start_capture:
                    self._emit_status("目标已消失，开始延迟截图...")
                    self._delayed_capture(capture_top_right)
                    cooldown_until = time.time() + self.cooldown_after_success
                    capture_in_progress = False
                    waiting_for_disappear = False
                    armed = False
                    miss_frames = 0
                    disappear_miss_frames = 0
                    last_detected_top_right = None
                    self._state = self.COOLDOWN
                    self._emit_status(f"截图完成，冷却 {self.cooldown_after_success:.1f}s...")

                self.check_count += 1
                # Vary check interval ±30% to avoid fixed timing pattern
                import random
                actual_interval = self.check_interval * (0.7 + 0.6 * random.random())
                time.sleep(actual_interval)

            except Exception as e:
                self._emit_status(f"监测异常：{e}")
                time.sleep(0.5)
