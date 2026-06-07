"""Skip-story runner — YOLO-based dialogue and cutscene skipping."""

import os
import time
import logging

from roco_auto.core.config_manager import get_app_dir
from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class SkipRunner(ModeRunner):
    """Skip story: YOLO detects dialogs → press 1, cutscenes → ESC → click confirm."""

    def __init__(self, ctx: RunnerContext,
                 yolo_model: str = "",
                 confidence: float = 0.5,
                 poll_interval: int = 300,
                 on_tick: callable = None):
        super().__init__(ctx)
        self.yolo_model = yolo_model
        self.confidence = confidence
        self.poll_interval = poll_interval
        self.count = 0
        self.start_time = 0.0
        self._on_tick = on_tick
        self._yolo = None

    def _get_yolo(self):
        """Lazy-init the YoloDetector."""
        if self._yolo is not None:
            return self._yolo
        from roco_auto.core.yolo_detector import YoloDetector
        model_path = self.yolo_model
        if not model_path:
            model_path = os.path.join(
                get_app_dir(), "models", "roco_yolo.onnx"
            )
        self._yolo = YoloDetector(model_path, confidence=self.confidence)
        loaded = self._yolo.load()
        if not loaded:
            logger.error("YOLO model failed to load: %s", model_path)
        return self._yolo

    def is_yolo_loaded(self) -> bool:
        yolo = self._get_yolo()
        return yolo.is_loaded

    def yolo_class_names(self) -> list:
        yolo = self._get_yolo()
        return yolo.class_names if yolo.is_loaded else []

    def run_loop(self) -> None:
        self.start_time = time.time()
        yolo_load_failures = 0
        MAX_RETRIES = 5
        # Exponential backoff delays (seconds): 10, 30, 60, 60, 60
        _BACKOFF_DELAYS = [10000, 30000, 60000, 60000, 60000]

        while not self._stop_event.is_set():
            try:
                yolo = self._get_yolo()
                if not yolo.is_loaded:
                    yolo_load_failures += 1
                    if yolo_load_failures <= 3:
                        logger.warning("YOLO not loaded, waiting... (attempt %d)", yolo_load_failures)
                    # Exponential backoff — give up after MAX_RETRIES reload attempts
                    if yolo_load_failures < MAX_RETRIES:
                        delay = _BACKOFF_DELAYS[min(yolo_load_failures - 1, len(_BACKOFF_DELAYS) - 1)]
                        logger.info("Retrying YOLO model load in %.1fs (attempt %d/%d)...",
                                    delay / 1000.0, yolo_load_failures, MAX_RETRIES)
                        self._yolo = None
                        self.ctx.send_wait(delay, 0.0)
                    else:
                        logger.error("YOLO model failed to load after %d attempts — giving up", MAX_RETRIES)
                        return  # exit the loop permanently
                    continue
                yolo_load_failures = 0

                detections = yolo.detect(self.confidence)

                dialogs = [d for d in detections if d["class"] == "dialog"]
                if dialogs:
                    self.count += 1
                    if self._on_tick:
                        self._on_tick(self.count)
                    for _ in range(3):
                        if self._stop_event.is_set():
                            break
                        self.ctx.send_key("1")
                        self.ctx.send_wait(80, 0.0)
                    self.ctx.send_wait(200, 0.0)
                    continue

                cutscenes = [d for d in detections if d["class"] == "cutscene"]
                if cutscenes:
                    self.count += 1
                    if self._on_tick:
                        self._on_tick(self.count)
                    for _ in range(3):
                        if self._stop_event.is_set():
                            break
                        self.ctx.send_key("ESC")
                        self.ctx.send_wait(80, 0.0)
                    self.ctx.send_wait(300, 0.0)

                    result = yolo.wait_for_class("confirm", timeout_ms=3000,
                                                  poll_interval_ms=200)
                    if result is not None:
                        self.ctx.send_move_click(result["x"], result["y"])
                        self.ctx.send_wait(500, 0.0)  # debounce after cutscene
                    continue

            except Exception:
                logger.exception("Error in skip story loop")

            self.ctx.send_wait(self.poll_interval, 0.0)
