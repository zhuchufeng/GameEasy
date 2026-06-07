"""Fast screen region capture using mss (DXGI/DirectX backend)."""

import numpy as np
from typing import Optional


class ScreenCapture:
    """Screen capture with mss backend, falling back to PIL."""

    def __init__(self):
        self._mss = None
        try:
            import mss
            self._mss = mss.MSS()
        except ImportError:
            pass

    def capture_full(self) -> np.ndarray:
        """Capture the entire primary monitor as a BGR numpy array."""
        if self._mss:
            monitor = self._mss.monitors[1]
            sct = self._mss.grab(monitor)
            img = np.array(sct, dtype=np.uint8)
            return img[:, :, :3]  # BGRA → BGR
        else:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            return np.array(img, dtype=np.uint8)[:, :, ::-1]  # RGB → BGR

    def capture_region(self, region: tuple[int, int, int, int]) -> np.ndarray:
        """Capture (left, top, width, height) as BGR numpy array."""
        if self._mss:
            sct = self._mss.grab({
                "left": region[0], "top": region[1],
                "width": region[2], "height": region[3],
            })
            img = np.array(sct, dtype=np.uint8)
            return img[:, :, :3]
        else:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(
                region[0], region[1],
                region[0] + region[2], region[1] + region[3],
            ))
            return np.array(img, dtype=np.uint8)[:, :, ::-1]

    def get_screen_size(self) -> tuple[int, int]:
        """Get primary monitor resolution."""
        if self._mss:
            monitor = self._mss.monitors[1]
            return monitor["width"], monitor["height"]
        else:
            import ctypes
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
