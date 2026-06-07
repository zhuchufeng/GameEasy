"""Visitor engine — per-stage YOLO models for "互访炫彩" two-window automation.

Each stage uses its own dedicated single-class YOLO model:
  ENTER       → enter_visit model
  REQUEST     → request_visit model
  ACCEPT      → accept_visit model
  WORLD_CHECK → world_popup model
  MINIMAP     → colorful model (PT/HB detection)
  EXIT        → exit_world model

State machine:
  ENTER → REQUEST → SWITCH_TO_WIN2 → ACCEPT → WORLD_CHECK → MINIMAP → SWITCH_BACK → EXIT → ENTER
"""

import os
import time
import random
import threading
import logging
from enum import Enum, auto

import numpy as np

logger = logging.getLogger(__name__)


class Stage(Enum):
    ENTER = auto()
    REQUEST = auto()
    SWITCH_TO_WIN2 = auto()
    ACCEPT_IN_WIN2 = auto()
    WORLD_CHECK = auto()
    MINIMAP = auto()
    SWITCH_BACK = auto()
    EXIT = auto()
    STOPPED = auto()


_STAGE_LABELS = {
    Stage.ENTER: "进入访问",
    Stage.REQUEST: "申请访问",
    Stage.SWITCH_TO_WIN2: "切换到窗口2",
    Stage.ACCEPT_IN_WIN2: "同意访问(窗口2)",
    Stage.WORLD_CHECK: "确认世界人数",
    Stage.MINIMAP: "小地图检测",
    Stage.SWITCH_BACK: "切回窗口1",
    Stage.EXIT: "退出世界",
    Stage.STOPPED: "已停止",
}

_STAGE_COLORS = {
    "进入访问": "#6c8cff", "申请访问": "#ffaa00",
    "切换到窗口2": "#8888ff", "同意访问(窗口2)": "#cc88ff",
    "确认世界人数": "#ffcc00", "小地图检测": "#4ade80",
    "切回窗口1": "#8888ff", "退出世界": "#ff6c6c",
    "已停止": "#ff5c5c",
}

# Stage → model key mapping
_STAGE_MODEL_KEY = {
    Stage.ENTER: "enter",
    Stage.REQUEST: "request",
    Stage.ACCEPT_IN_WIN2: "accept",
    Stage.WORLD_CHECK: "world",
    Stage.EXIT: "exit",
}


class VisitorEngine:
    """Multi-stage two-window visitor automation engine (per-stage YOLO models)."""

    def __init__(self):
        # ── Window targets ──
        self._win1_hwnd: int | None = None
        self._win2_hwnd: int | None = None

        # ── Per-stage YOLO models ──
        self._models: dict[str, object] = {}
        self._model_paths: dict[str, str] = {}
        self._yolo_confidence: float = 0.7
        self._stage_delay: float = 0.5
        self._debug_save: bool = True
        self._loop_delay: float = 0.0  # seconds to wait between full loops

        # ── Minimap (separate model) ──
        self._minimap_yolo = None
        self._minimap_classes: list[str] = ["PT", "HB"]

        # ── Minimap region ──
        self._minimap_region: tuple | None = None
        self._minimap_scan_attempts: int = 3

        # ── Click jitter ──
        self._click_jitter: int = 4

        # ── Server酱 ──
        self._sckey: str = ""
        self._notify_title: str = "互访炫彩检测通知"
        self._notify_body: str = "检测到: {name}\n置信度: {conf:.3f}\n时间: {time}"

        # ── Runtime ──
        self._running = False
        self._stop_flag = False
        self._thread: threading.Thread | None = None
        self._stage = Stage.ENTER
        self._lock = threading.Lock()
        self._current_win: bool | None = None  # True=Win1, False=Win2, None=unknown

        # ── Callbacks ──
        self.on_status: callable | None = None
        self.on_stage_change: callable | None = None
        self.on_detected: callable | None = None

        # ── Stats ──
        self.loop_count: int = 0
        self.start_time: float = 0.0

    # ═══════════════════════════════════════  Properties  ═══

    @property
    def stage(self):
        return self._stage

    @property
    def running(self):
        return self._running

    @property
    def yolo_loaded(self):
        """True if all 5 stage models are loaded."""
        return len(self._models) >= 5

    @property
    def minimap_loaded(self):
        return self._minimap_yolo is not None and self._minimap_yolo.is_loaded

    @property
    def model_paths(self) -> dict:
        return dict(self._model_paths)

    # ═══════════════════════════════════════  Configuration  ═══

    def set_win1(self, hwnd: int):
        self._win1_hwnd = hwnd

    def set_win2(self, hwnd: int):
        self._win2_hwnd = hwnd

    def auto_load_models(self, model_dir: str) -> int:
        """Auto-load all 5 stage models from a directory. Falls back to bundled models."""
        # If model_dir doesn't exist, try the bundled models/visitor/ directory
        if not os.path.isdir(model_dir):
            logger.warning("Model dir not found: %s, falling back to bundled models", model_dir)
            model_dir = os.path.join(get_app_dir(), "models", "visitor")
            if not os.path.isdir(model_dir):
                logger.error("Bundled visitor models not found at: %s", model_dir)
                return 0

        stage_files = {
            "enter":   "enter_visit.onnx",
            "request": "request_visit.onnx",
            "accept":  "accept_visit.onnx",
            "world":   "world_popup.onnx",
            "exit":    "exit_world.onnx",
        }
        loaded = 0
        for key, fname in stage_files.items():
            path = os.path.join(model_dir, fname)
            if not os.path.exists(path):
                # Try common alternative filenames
                alt_path = os.path.join(model_dir, key + "_visit.onnx")
                if os.path.exists(alt_path):
                    path = alt_path
                else:
                    logger.warning("Stage model not found: %s for stage '%s'", fname, key)
                    continue
            try:
                from roco_auto.core.yolo_detector import YoloDetector
                detector = YoloDetector(path, confidence=self._yolo_confidence)
                if detector.load():
                    self._models[key] = detector
                    self._model_paths[key] = path
                    loaded += 1
                    logger.info("Loaded stage model '%s': %s", key, path)
                else:
                    logger.warning("Failed to load stage model: %s", path)
            except Exception as e:
                logger.error("Error loading stage model '%s': %s", path, e)
        return loaded
    def load_stage_model(self, stage_key: str, model_path: str) -> bool:
        """Load a per-stage model using ultralytics YOLO (same as user's test.py)."""
        try:
            from ultralytics import YOLO
            self._models[stage_key] = YOLO(model_path)
            self._model_paths[stage_key] = model_path
            return True
        except Exception:
            return False

    def load_minimap_model(self, model_path: str) -> bool:
        """Load the minimap YOLO model (colorful.onnx)."""
        from roco_auto.core.yolo_detector import YoloDetector
        d = YoloDetector(model_path, confidence=self._yolo_confidence)
        if d.load():
            self._minimap_yolo = d
            self._minimap_model_path = model_path
            if d.class_names:
                self._minimap_classes = d.class_names
            return True
        return False

    def _get_model(self, stage: Stage):
        """Get the model for a given stage."""
        key = _STAGE_MODEL_KEY.get(stage)
        return self._models.get(key) if key else None

    def set_loop_delay(self, seconds: float):
        self._loop_delay = max(0, seconds)

    def set_confidence(self, value: float):
        self._yolo_confidence = value
        if self._minimap_yolo:
            self._minimap_yolo.confidence = value

    def set_minimap_classes(self, names: list[str]):
        self._minimap_classes = names or ["PT", "HB"]

    def set_minimap_region(self, left, top, right, bottom):
        self._minimap_region = (left, top, right, bottom)

    def set_minimap_region_from_window(self, win_rect: dict, rx1, ry1, rx2, ry2):
        left = int(win_rect["left"] + win_rect["width"] * rx1)
        top = int(win_rect["top"] + win_rect["height"] * ry1)
        right = int(win_rect["left"] + win_rect["width"] * rx2)
        bottom = int(win_rect["top"] + win_rect["height"] * ry2)
        self._minimap_region = (left, top, right, bottom)

    def set_sckey(self, key: str):
        self._sckey = key

    def set_notify_title(self, title: str):
        self._notify_title = title

    def set_notify_body(self, body: str):
        self._notify_body = body

    @property
    def _backend(self):
        return getattr(self, '_input_backend', None)

    # ═══════════════════════════════════════  Control  ═══

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            if self._win1_hwnd is None:
                self._emit_status("错误：未选择窗口1")
                return False
            if self._win2_hwnd is None:
                self._emit_status("错误：未选择窗口2")
                return False
            if self._win1_hwnd == self._win2_hwnd:
                self._emit_status("错误：两个窗口不能相同")
                return False
            if not self.yolo_loaded:
                missing = [k for k in ["enter","request","accept","world","exit"] if k not in self._models]
                self._emit_status(f"错误：缺少模型: {', '.join(missing)}")
                return False
            if self._minimap_region is None:
                self._emit_status("错误：未设置小地图监测区域")
                return False

            self._stop_flag = False
            self._running = True
            self.loop_count = 0
            self.start_time = time.time()
            self._current_win = True  # Start on Win1
            self._set_stage(Stage.ENTER)
            self._thread = threading.Thread(target=self._main_loop, daemon=True)
            self._thread.start()
            self._emit_status("互访炫彩已启动")
            return True

    def stop(self):
        with self._lock:
            self._stop_flag = True
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._set_stage(Stage.STOPPED)
        self._emit_status("互访炫彩已停止")

    # ═══════════════════════════════════════  Main loop  ═══

    def _main_loop(self):
        while not self._stop_flag:
            self.loop_count += 1
            try:
                stage = self._stage
                if stage == Stage.ENTER:
                    self._do_enter()
                elif stage == Stage.REQUEST:
                    self._do_request()
                elif stage == Stage.ACCEPT_IN_WIN2:
                    self._do_accept_in_win2()
                elif stage == Stage.WORLD_CHECK:
                    self._do_world_check()
                elif stage == Stage.MINIMAP:
                    self._do_minimap()
                elif stage == Stage.EXIT:
                    self._do_exit()
            except Exception:
                logger.exception("Visitor engine error in stage %s", self._stage)
                time.sleep(0.5)

    # ═══════════════════════════════════════  Stage implementations  ═══

    def _save_debug(self, bgr, dets, label):
        """Save debug screenshot (detections and non-detections)."""
        if not self._debug_save:
            return
        # Throttle: max 1 save per second per stage
        cache_key = f"{label}_{int(time.time())}"
        if hasattr(self, '_debug_saved') and cache_key in self._debug_saved:
            return
        if not hasattr(self, '_debug_saved'):
            self._debug_saved = set()
        self._debug_saved.add(cache_key)
        try:
            import cv2
            dbg_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "debug_visitor")
            os.makedirs(dbg_dir, exist_ok=True)
            img = bgr.copy()
            for d in dets:
                cx, cy, w, h = d["x"], d["y"], d["w"], d["h"]
                x1 = max(0, int(cx - w/2)); y1 = max(0, int(cy - h/2))
                x2 = max(0, int(cx + w/2)); y2 = max(0, int(cy + h/2))
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(img, f"{d['class']} {d['confidence']:.2f}", (x1, max(y1-4, 20)),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            fname = f"{self.loop_count:03d}_{label}.png"
            cv2.imencode('.png', img)[1].tofile(os.path.join(dbg_dir, fname))
        except Exception:
            pass

    def _detect_with_model(self, model, rect: dict, stage_label: str) -> list:
        """Capture window and run detection with ultralytics YOLO. Returns detection list."""
        # Only switch windows if this stage needs a different window
        target_win = self._STAGE_WINDOW.get(self._stage)
        if target_win is not None and target_win != self._current_win:
            target_hwnd = self._win1_hwnd if target_win else self._win2_hwnd
            self._switch_to(target_hwnd)
            self._current_win = target_win
        bgr = self._capture_window(rect)
        if bgr is None or bgr.size == 0:
            return []
        # ultralytics YOLO: run inference on BGR image
        results = model(bgr, conf=self._yolo_confidence, imgsz=640, verbose=False)
        dets = []
        for r in results:
            if r.boxes is not None:
                for box in r.boxes:
                    xyxy = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0]) if box.cls is not None else 0
                    cls_name = model.names.get(cls_id, str(cls_id)) if hasattr(model, 'names') else str(cls_id)
                    dets.append({
                        "class": cls_name,
                        "confidence": float(box.conf[0]) if box.conf is not None else 0.0,
                        "x": int((xyxy[0] + xyxy[2]) / 2),
                        "y": int((xyxy[1] + xyxy[3]) / 2),
                        "w": int(xyxy[2] - xyxy[0]),
                        "h": int(xyxy[3] - xyxy[1]),
                    })
        self._save_debug(bgr, dets, stage_label)
        if dets:
            names = ", ".join(f"{d['class']}@{d['confidence']:.1f}" for d in dets[:3])
            self._emit_status(f"[{stage_label}] 检测到: {names}")
        return dets

    def _do_enter(self):
        self._emit_status(f"第{self.loop_count}轮: 寻找进入访问...")
        rect = self._get_window_rect(self._win1_hwnd)
        if not rect:
            self._emit_status("错误: 窗口1不可用")
            time.sleep(1.0)
            return
        model = self._get_model(Stage.ENTER)
        dets = self._detect_with_model(model, rect, "阶段1-进入")
        if dets:
            self._press_key("F")
            time.sleep(random.uniform(0.3, 0.7))
            self._set_stage(Stage.REQUEST)
        else:
            time.sleep(0.15)

    def _do_request(self):
        self._emit_status(f"第{self.loop_count}轮: 寻找申请访问...")
        rect = self._get_window_rect(self._win1_hwnd)
        if not rect:
            time.sleep(0.3)
            return
        model = self._get_model(Stage.REQUEST)
        dets = self._detect_with_model(model, rect, "阶段2-申请")
        if dets:
            best = max(dets, key=lambda d: d["confidence"])
            screen_x = rect["left"] + best["x"]
            screen_y = rect["top"] + best["y"]
            self._click_at(screen_x, screen_y)
            time.sleep(random.uniform(0.5, 0.8))
            self._set_stage(Stage.ACCEPT_IN_WIN2)
        else:
            time.sleep(0.15)

    def _do_accept_in_win2(self):
        self._emit_status(f"第{self.loop_count}轮: 窗口2寻找同意访问...")
        rect = self._get_window_rect(self._win2_hwnd)
        if not rect:
            time.sleep(0.3)
            return
        model = self._get_model(Stage.ACCEPT_IN_WIN2)
        dets = self._detect_with_model(model, rect, "阶段4-同意")
        if dets:
            self._press_key("F")
            time.sleep(random.uniform(0.3, 0.6))
            self._set_stage(Stage.WORLD_CHECK)
        else:
            time.sleep(0.15)

    def _do_world_check(self):
        self._emit_status(f"第{self.loop_count}轮: 确认世界人数...")
        rect = self._get_window_rect(self._win2_hwnd)
        if not rect:
            time.sleep(0.3)
            return
        model = self._get_model(Stage.WORLD_CHECK)
        for _ in range(20):
            if self._stop_flag:
                return
            dets = self._detect_with_model(model, rect, "阶段5-世界")
            if dets:
                self._emit_status("已确认世界人数，进入小地图检测")
                self._set_stage(Stage.MINIMAP)
                return
            time.sleep(0.15)
        self._emit_status("错误：未检测到世界人数，退出重试...")
        self._set_stage(Stage.EXIT)

    def _do_minimap(self):
        self._emit_status(f"第{self.loop_count}轮: 小地图检测中...")
        if self._current_win != False:
            self._switch_to(self._win2_hwnd); self._current_win = False
        for attempt in range(self._minimap_scan_attempts + 1):
            if self._stop_flag:
                return
            found = self._scan_minimap()
            if found:
                self._emit_detected(found["class"], found["confidence"])
                self._send_wechat(found["class"], found["confidence"])
                self._emit_status(f"检测到 {found['class']}！微信通知已发送，停止")
                self.stop()
                return
            if attempt >= self._minimap_scan_attempts:
                self._emit_status(f"第{self.loop_count}轮: 小地图未检测到 PT/HB，进入退出流程")
                self._set_stage(Stage.EXIT)
            else:
                time.sleep(0.15)

    def _do_exit(self):
        self._emit_status(f"第{self.loop_count}轮: 按U，寻找退出世界...")
        if self._current_win != True:
            self._switch_to(self._win1_hwnd); self._current_win = True
        self._press_key("U")
        time.sleep(random.uniform(0.3, 0.6))
        rect = self._get_window_rect(self._win1_hwnd)
        if not rect:
            time.sleep(0.3)
            self._set_stage(Stage.ENTER)
            return
        model = self._get_model(Stage.EXIT)
        for _ in range(15):
            if self._stop_flag:
                return
            dets = self._detect_with_model(model, rect, "阶段8-退出")
            if dets:
                best = max(dets, key=lambda d: d["confidence"])
                screen_x = rect["left"] + best["x"]
                screen_y = rect["top"] + best["y"]
                self._click_at(screen_x, screen_y)
                time.sleep(random.uniform(0.5, 1.0))
                break
            time.sleep(0.15)
        # Loop delay between full rounds
        if self._loop_delay > 0:
            self._emit_status(f"本轮完成，等待 {self._loop_delay:.0f}s...")
            time.sleep(self._loop_delay)
        self._set_stage(Stage.ENTER)

    # ═══════════════════════════════════════  Minimap YOLO  ═══

    def _scan_minimap(self) -> dict | None:
        if not self.minimap_loaded or not self._minimap_region:
            return None
        from roco_auto.core.screen_capture import ScreenCapture
        left, top, right, bottom = self._minimap_region
        from PIL import Image
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None
        cap = ScreenCapture()
        bgr = cap.capture_region((left, top, w, h))
        pil_img = Image.fromarray(bgr[:, :, ::-1], mode="RGB")
        img = np.array(pil_img.convert("RGB"))
        bgr2 = img[:, :, ::-1]
        dets = self._minimap_yolo.detect_on_region(bgr2, self._yolo_confidence, self._minimap_classes)
        self._save_debug(bgr2, dets, "minimap")
        return max(dets, key=lambda d: d["confidence"]) if dets else None

    # ═══════════════════════════════════════  Window helpers  ═══

    @staticmethod
    def _get_window_rect(hwnd: int) -> dict | None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        crect = wintypes.RECT()
        if not user32.IsWindow(hwnd) or not user32.GetClientRect(hwnd, ctypes.byref(crect)):
            return None
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return {
            "left": pt.x, "top": pt.y,
            "width": crect.right, "height": crect.bottom,
            "right": pt.x + crect.right, "bottom": pt.y + crect.bottom,
            "hwnd": hwnd,
        }

    # Stage → window mapping: True=Win1, False=Win2
    _STAGE_WINDOW = {
        Stage.ENTER: True, Stage.REQUEST: True,
        Stage.ACCEPT_IN_WIN2: False, Stage.WORLD_CHECK: False, Stage.MINIMAP: False,
        Stage.EXIT: True,
    }

    @staticmethod
    def _switch_to(hwnd: int):
        """Switch to a specific window. Uses SendInput to get foreground rights,
        then SetForegroundWindow. Works regardless of other windows in between."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        # SendInput: fake keystroke grants foreground activation rights to our process
        class KI(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class INP(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("ki", KI)]

        inp = INP(); inp.type = 1  # INPUT_KEYBOARD
        inp.ki.wVk = 0xFF  # harmless no-op key
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))
        inp.ki.dwFlags = 0x0002  # KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))

        # Now we have foreground rights — switch directly
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        time.sleep(0.3)

    def _send_win_d(self):
        """Minimize all windows via Win+D."""
        self._p("WIN"); time.sleep(0.03)
        self._send("D"); time.sleep(0.03)
        self._r("WIN"); time.sleep(0.2)

    def _p(self, key):
        """Press a key (hold down) via backend."""
        k = key.upper()
        if self._backend:
            self._backend.press(k)

    def _r(self, key):
        """Release a key via backend."""
        if self._backend:
            self._backend.release(key.upper())

    def _send(self, key):
        """Tap a key via backend."""
        if self._backend:
            self._backend.send_key(key.upper())

    @staticmethod
    def _capture_window(rect: dict) -> np.ndarray:
        from roco_auto.core.screen_capture import ScreenCapture
        from PIL import Image
        cap = ScreenCapture()
        bgr = cap.capture_region((rect["left"], rect["top"], rect["width"], rect["height"]))
        pil_img = Image.fromarray(bgr[:, :, ::-1], mode="RGB")
        img = np.array(pil_img.convert("RGB"))
        return img[:, :, ::-1]

    # ═══════════════════════════════════════  Input  ═══

    def _press_key(self, key: str):
        if self._backend:
            self._backend.send_key(key.upper())
        else:
            import win32api, win32con
            vk = ord(key.upper()) if len(key) == 1 else 0
            if vk:
                win32api.keybd_event(vk, 0, 0, 0)
                time.sleep(random.uniform(0.05, 0.12))
                win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _release_key(self, key: str):
        """Release a held key (for combos like Alt+Tab)."""
        if self._backend:
            self._backend.release(key.upper())
        else:
            import win32api, win32con
            vk = 0
            if key.upper() == "ALT": vk = win32con.VK_MENU
            elif key.upper() == "TAB": vk = win32con.VK_TAB
            elif len(key) == 1: vk = ord(key.upper())
            if vk:
                win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

    def _click_at(self, x: int, y: int):
        jx = x + random.randint(-self._click_jitter, self._click_jitter)
        jy = y + random.randint(-self._click_jitter, self._click_jitter)
        if self._backend:
            self._backend.send_move_click(jx, jy)
        else:
            import win32api, win32con
            win32api.SetCursorPos((jx, jy))
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(random.uniform(0.05, 0.12))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    # ═══════════════════════════════════════  WeChat  ═══

    def _send_wechat(self, detected_name: str, confidence: float = 0.0):
        if not self._sckey:
            return
        try:
            import urllib.request, urllib.parse
            title = self._notify_title.format(name=detected_name, conf=confidence, time=time.strftime('%H:%M:%S'), loop=self.loop_count)
            content = self._notify_body.format(name=detected_name, conf=confidence, time=time.strftime('%H:%M:%S'), loop=self.loop_count)
            url = f"https://sctapi.ftqq.com/{self._sckey}.send"
            data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
            logger.info("WeChat notification sent")
        except Exception:
            logger.exception("Failed to send WeChat notification")

    # ═══════════════════════════════════════  Callbacks  ═══

    def _set_stage(self, stage: Stage):
        self._stage = stage
        label = _STAGE_LABELS.get(stage, str(stage))
        # Wait for game UI to render after stage transition
        if stage not in (Stage.STOPPED,):
            time.sleep(self._stage_delay)
        try:
            if self.on_stage_change:
                self.on_stage_change(label)
        except Exception:
            pass

    def _emit_status(self, text: str):
        try:
            if self.on_status:
                self.on_status(text)
        except Exception:
            pass

    def _emit_detected(self, name: str, score: float):
        try:
            if self.on_detected:
                self.on_detected(name, score)
        except Exception:
            pass
