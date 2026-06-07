"""YOLO object detector for game UI element recognition.

Uses ONNX Runtime for inference — no PyTorch dependency at runtime.
Model is trained separately using scripts/train_yolo.py.
"""

import os
import time
from typing import Optional

import numpy as np

from roco_auto.core.screen_capture import ScreenCapture
from roco_auto.core.config_manager import resolve_model_path, get_app_dir


class YoloDetector:
    """Lightweight YOLO detector using ONNX Runtime.

    Detects game UI elements: dialog boxes, cutscene triggers, buttons, etc.
    """

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.5,
        iou_threshold: float = 0.45,
    ):
        self.model_path = model_path
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self._capture = ScreenCapture()
        self._session = None
        self._input_name = ""
        self._input_width = 640
        self._input_height = 640
        self._class_names: list[str] = []
        self._loaded = False

    def load(self) -> bool:
        """Load the ONNX model. Returns True on success."""
        if not self.model_path or not os.path.exists(self.model_path):
            import logging
            logging.getLogger(__name__).warning("YOLO model not found: %s", self.model_path or "(empty path)")
            return False
        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                self.model_path,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
            input_shape = self._session.get_inputs()[0].shape
            self._input_width = input_shape[2]
            self._input_height = input_shape[3]

            # Try to load class names (rsplit to handle .onnx in dir names)
            label_path = self.model_path[:self.model_path.rfind(".onnx")] + ".names"
            if os.path.exists(label_path):
                with open(label_path, "r", encoding="utf-8") as f:
                    self._class_names = [line.strip() for line in f if line.strip()]
            self._loaded = True
            return True
        except ImportError:
            import logging
            logging.getLogger(__name__).warning("onnxruntime not installed - YOLO detection disabled")
            return False
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to load YOLO model '%s': %s", self.model_path, e)
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def class_names(self) -> list[str]:
        return self._class_names

    def detect(self, confidence: Optional[float] = None) -> list[dict]:
        """Run detection on current screen.

        Returns list of dicts:
          {"class": str, "confidence": float, "x": int, "y": int, "w": int, "h": int}
        where (x,y) is the center of the bounding box.
        """
        if not self._loaded:
            return []

        conf = confidence if confidence is not None else self.confidence
        img = self._capture.capture_full()

        # Preprocess: resize and normalize
        input_tensor = self._preprocess(img)

        # Inference
        outputs = self._session.run(None, {self._input_name: input_tensor})
        detections = self._postprocess(outputs, img.shape[1], img.shape[0], conf)

        return detections

    def detect_class(self, class_name: str, confidence: Optional[float] = None) -> Optional[dict]:
        """Detect a specific class. Returns the first match or None."""
        detections = self.detect(confidence)
        for d in detections:
            if d["class"] == class_name:
                return d
        return None

    def detect_any(self, class_names: list[str], confidence: Optional[float] = None) -> Optional[dict]:
        """Detect any of the given classes. Returns the highest-confidence match."""
        detections = self.detect(confidence)
        best = None
        best_conf = 0
        for d in detections:
            if d["class"] in class_names and d["confidence"] > best_conf:
                best = d
                best_conf = d["confidence"]
        return best

    def wait_for_class(
        self,
        class_name: str,
        timeout_ms: int = 5000,
        poll_interval_ms: int = 200,
        confidence: Optional[float] = None,
    ) -> Optional[dict]:
        """Wait until a specific class appears. Returns detection or None on timeout."""
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            result = self.detect_class(class_name, confidence)
            if result is not None:
                return result
            time.sleep(poll_interval_ms / 1000.0)
        return None

    def detect_on_region(
        self,
        bgr_image: np.ndarray,
        confidence: Optional[float] = None,
        target_classes: Optional[list[str]] = None,
    ) -> list[dict]:
        """Run YOLO on an arbitrary BGR image (window region, minimap, etc.).

        Args:
            bgr_image: BGR numpy array of any size (will be letterboxed).
            confidence: Override confidence threshold. Uses self.confidence if None.
            target_classes: If provided, filter results to these class names only.

        Returns:
            List of detection dicts with coordinates relative to the input image.
        """
        if not self._loaded:
            return []
        conf = confidence if confidence is not None else self.confidence
        h, w = bgr_image.shape[:2]
        input_tensor = self._preprocess(bgr_image)
        outputs = self._session.run(None, {self._input_name: input_tensor})
        detections = self._postprocess(outputs, w, h, conf)
        if target_classes:
            detections = [d for d in detections if d["class"] in target_classes]
        return detections

    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        """Resize and normalize image for YOLO input.

        Stores letterbox params as instance attrs for correct inverse mapping.
        """
        import cv2
        h, w = img.shape[:2]
        # Letterbox resize (ultralytics-style: pad with 114, resize with INTER_LINEAR)
        r = min(self._input_width / w, self._input_height / h)
        new_w = int(round(w * r))
        new_h = int(round(h * r))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Pad to input size with gray (114,114,114)
        canvas = np.full((self._input_height, self._input_width, 3), 114, dtype=np.uint8)
        self._pad_x = (self._input_width - new_w) // 2
        self._pad_y = (self._input_height - new_h) // 2
        canvas[self._pad_y:self._pad_y + new_h, self._pad_x:self._pad_x + new_w] = resized
        self._preprocess_scale = r

        # BGR → RGB, normalize to [0,1], transpose to NCHW
        blob = canvas[:, :, ::-1].astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)  # HWC -> CHW
        blob = np.expand_dims(blob, axis=0)  # Add batch dim
        return blob

    def _postprocess(
        self, outputs: list[np.ndarray],
        screen_w: int, screen_h: int,
        confidence: float,
    ) -> list[dict]:
        """Parse YOLO output into detection dicts with screen coordinates."""
        results = []
        output = outputs[0]  # Detect: (1, 4+cls, 8400)  Seg: (1, 300, 4+1+cls+mask)

        shape = output.shape
        if len(shape) == 3 and shape[2] == 8400:
            # Detect format: (1, N, 8400) → transpose to (8400, N)
            preds = output[0].T  # (8400, N)
            boxes = preds[:, :4]
            scores = preds[:, 4:]
        elif len(shape) == 3:
            # Segment format: (1, 300, 4+1+cls+mask)
            preds = output[0]  # (300, N)
            boxes = preds[:, :4]
            obj_conf = preds[:, 4]  # objectness
            num_cls = len(self._class_names) if self._class_names else 1
            scores_raw = preds[:, 5:5 + num_cls]  # class scores
            # Multiply class scores by objectness
            scores = scores_raw * obj_conf[:, np.newaxis]
        else:
            return []

        class_ids = np.argmax(scores, axis=1)
        max_scores = np.max(scores, axis=1)

        mask = max_scores > confidence
        boxes = boxes[mask]
        class_ids = class_ids[mask]
        max_scores = max_scores[mask]

        if len(boxes) == 0:
            return []

        # Convert cxcywh to xyxy
        cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2

        # Undo letterbox: remove padding, then divide by resize scale.
        # YOLO boxes are in the letterbox input space; after this they
        # are in screen coordinates because the input image was a full screen capture.
        x1 = (x1 - self._pad_x) / self._preprocess_scale
        y1 = (y1 - self._pad_y) / self._preprocess_scale
        x2 = (x2 - self._pad_x) / self._preprocess_scale
        y2 = (y2 - self._pad_y) / self._preprocess_scale

        for i in range(len(boxes)):
            if max_scores[i] < confidence:
                continue
            cls_id = int(class_ids[i])
            cls_name = (
                self._class_names[cls_id]
                if cls_id < len(self._class_names)
                else str(cls_id)
            )
            center_x = int((x1[i] + x2[i]) / 2)
            center_y = int((y1[i] + y2[i]) / 2)
            results.append({
                "class": cls_name,
                "confidence": float(max_scores[i]),
                "x": center_x,
                "y": center_y,
                "w": int(x2[i] - x1[i]),
                "h": int(y2[i] - y1[i]),
            })

        # NMS
        results = self._nms(results)
        return results

    def _nms(self, detections: list[dict]) -> list[dict]:
        """Simple class-wise NMS."""
        if not detections:
            return []

        # Group by class
        by_class: dict[str, list[dict]] = {}
        for d in detections:
            by_class.setdefault(d["class"], []).append(d)

        kept = []
        for cls_name, items in by_class.items():
            items.sort(key=lambda d: d["confidence"], reverse=True)
            while items:
                best = items.pop(0)
                kept.append(best)
                items = [
                    d for d in items
                    if self._iou(best, d) < self.iou_threshold
                ]

        return kept

    def _iou(self, a: dict, b: dict) -> float:
        """Calculate IoU between two detection boxes."""
        ax1 = a["x"] - a["w"] / 2
        ay1 = a["y"] - a["h"] / 2
        ax2 = a["x"] + a["w"] / 2
        ay2 = a["y"] + a["h"] / 2
        bx1 = b["x"] - b["w"] / 2
        by1 = b["y"] - b["h"] / 2
        bx2 = b["x"] + b["w"] / 2
        by2 = b["y"] + b["h"] / 2

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h

        area_a = a["w"] * a["h"]
        area_b = b["w"] * b["h"]
        union = area_a + area_b - inter_area

        return inter_area / union if union > 0 else 0
