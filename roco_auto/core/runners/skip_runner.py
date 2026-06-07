"""Skip-story runner — YOLO-based detection of cutscene/dialog_confirm/dialog_1.

Model classes:
  cutscene       → press ESC twice, then look for dialog_confirm
  dialog_confirm → mouse click
  dialog_1       → press key "1" three times
"""

import os, time, logging
from roco_auto.core.mode_runner import ModeRunner, RunnerContext
from roco_auto.core.config_manager import get_app_dir

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.path.join(get_app_dir(), "models", "skip", "skip_model.onnx")


class SkipRunner(ModeRunner):
    def __init__(self, ctx: RunnerContext, yolo_model: str, confidence: float,
                 poll_interval: int, on_tick: callable,
                 on_status: callable = None, on_detect: callable = None):
        super().__init__(ctx)
        self.yolo_model = yolo_model or DEFAULT_MODEL
        self.confidence = confidence
        self.poll_interval = poll_interval
        self.on_tick = on_tick
        self.on_status = on_status  # callback for floating window status
        self.on_detect = on_detect  # callback for detection result
        self._count = 0

    def _emit(self, text: str):
        if self.on_status:
            try: self.on_status(text)
            except: pass

    def _load_model(self):
        from ultralytics import YOLO
        path = self.yolo_model or DEFAULT_MODEL
        if not os.path.exists(path):
            return None
        return YOLO(path)

    def _detect(self, model) -> list:
        win = self.ctx.get_target_window()
        if not win:
            return []
        from roco_auto.core.screen_capture import ScreenCapture
        from PIL import Image
        import numpy as np
        cap = ScreenCapture()
        bgr = cap.capture_region((win["left"], win["top"], win["width"], win["height"]))
        pil_img = Image.fromarray(bgr[:, :, ::-1], mode="RGB")
        img = np.array(pil_img.convert("RGB"))
        img_bgr = img[:, :, ::-1]
        results = model(img_bgr, conf=self.confidence, imgsz=640, verbose=False)
        dets = []
        img_area = win["width"] * win["height"]
        for r in results:
            if r.boxes is not None:
                for box in r.boxes:
                    xyxy = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0]) if box.cls is not None else 0
                    cls_name = model.names.get(cls_id, str(cls_id))
                    bw = int(xyxy[2] - xyxy[0])
                    bh = int(xyxy[3] - xyxy[1])
                    # Ignore boxes covering >80% of screen
                    if (bw * bh) > img_area * 0.8:
                        continue
                    dets.append({
                        "class": cls_name,
                        "confidence": float(box.conf[0]) if box.conf is not None else 0.0,
                        "x": int((xyxy[0] + xyxy[2]) / 2),
                        "y": int((xyxy[1] + xyxy[3]) / 2),
                        "w": bw, "h": bh,
                    })
        return dets

    def _any_class(self, dets, cls_name: str) -> bool:
        return any(d["class"] == cls_name for d in dets)

    def _first_of(self, dets, cls_name: str) -> dict | None:
        for d in dets:
            if d["class"] == cls_name:
                return d
        return None

    def run_loop(self):
        model = self._load_model()
        if model is None:
            self._emit("错误: 模型加载失败")
            return
        self._emit("跳过剧情已启动")

        _consecutive = 0  # require 2 consecutive frames to confirm

        while not self._stop_event.is_set():
            dets = self._detect(model)

            if self._any_class(dets, "cutscene"):
                _consecutive += 1
                if _consecutive < 2:
                    self.ctx.send_wait(self.poll_interval, variance=0.15)
                    continue
                names = ", ".join(f"{d['class']}@{d['confidence']:.1f}" for d in dets[:3])
                self._emit(f"检测到: {names}")
                if self.on_detect:
                    try: self.on_detect(dets)
                    except: pass
                # Click on cutscene every 500ms until dialog_confirm appears
                cutscene_item = self._first_of(dets, "cutscene")
                self._emit("cutscene: 点击直到确认出现...")
                for _ in range(30):
                    if self._stop_event.is_set():
                        break
                    if cutscene_item:
                        win = self.ctx.get_target_window()
                        if win:
                            self.ctx.send_move_click(win["left"] + cutscene_item["x"],
                                                     win["top"] + cutscene_item["y"])
                    self.ctx.send_wait(500, variance=0.0)
                    dets2 = self._detect(model)
                    item = self._first_of(dets2, "dialog_confirm")
                    if item:
                        self._emit(f"点击确认 (conf={item['confidence']:.2f})")
                        win = self.ctx.get_target_window()
                        if win:
                            self.ctx.send_move_click(win["left"] + item["x"], win["top"] + item["y"])
                        self._count += 1
                        try: self.on_tick(self._count)
                        except: pass
                        self.ctx.send_wait(500, variance=0.0)
                        break

            else:
                _consecutive = 0  # reset on non-cutscene frames

            if self._any_class(dets, "dialog_1"):
                names = ", ".join(f"{d['class']}@{d['confidence']:.1f}" for d in dets[:3])
                self._emit(f"检测到: {names} -> 按1三次")
                if self.on_detect:
                    try: self.on_detect(dets)
                    except: pass
                for i in range(3):
                    if self._stop_event.is_set():
                        break
                    self.ctx.send_key("1")
                    self.ctx.send_wait(250 if i < 2 else 500, variance=0.0)
                self._count += 1
                try: self.on_tick(self._count)
                except: pass

            elif self._any_class(dets, "dialog_confirm"):
                item = self._first_of(dets, "dialog_confirm")
                if item:
                    self._emit(f"点击确认 (conf={item['confidence']:.2f})")
                    if self.on_detect:
                        try: self.on_detect(dets)
                        except: pass
                    win = self.ctx.get_target_window()
                    if win:
                        self.ctx.send_move_click(win["left"] + item["x"], win["top"] + item["y"])
                    self._count += 1
                    try: self.on_tick(self._count)
                    except: pass
                    self.ctx.send_wait(500, variance=0.0)

            self.ctx.send_wait(self.poll_interval, variance=0.15)
