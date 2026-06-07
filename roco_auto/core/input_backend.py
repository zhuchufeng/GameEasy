"""Input backends for 洛克王国减负小助手.

Two real adapters behind the InputBackend seam:
  - UiohookBackend  — kernel driver (Interception PS/2 injection)
  - ArduinoBackend  — serial → Arduino USB HID hardware
"""

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


# ── Shared VK mapping — used by uiohook_backend ──

_KEY_TO_VK: dict[str, int] = {
    "ESC": 0x1B, "TAB": 0x09, "ENTER": 0x0D, "SPACE": 0x20,
    "BACKSPACE": 0x08,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12, "WIN": 0x5B,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
}


def _resolve_vk(key: str) -> int:
    """Resolve any key name to a Windows virtual key code. Returns 0 if unknown."""
    k = key.upper()
    if len(k) == 1:
        return ord(k)
    return _KEY_TO_VK.get(k, 0)


# ============================================================
#  Input Backend ABC
# ============================================================

class InputBackend(ABC):
    @abstractmethod
    def send_key(self, key: str) -> None: ...
    @abstractmethod
    def send_move_click(self, x: int, y: int) -> None: ...
    @abstractmethod
    def press(self, key: str) -> None: ...
    @abstractmethod
    def release(self, key: str) -> None: ...
    @abstractmethod
    def send_stop(self) -> None: ...
    @abstractmethod
    def send_screen_size(self, w: int, h: int) -> None: ...
    @abstractmethod
    def is_connected(self) -> bool: ...


# ============================================================
#  Noop Backend — safe placeholder before a real backend is set
# ============================================================

class NoopBackend(InputBackend):
    """Placeholder backend that logs warnings. All operations are no-ops.

    Used as the initial default before the user selects kernel driver or
    Arduino mode.  Also used as a stub while waiting for Arduino to connect.
    """

    def is_connected(self) -> bool:
        return False

    def send_key(self, key: str) -> None:
        logger.debug("NoopBackend: drop key %s", key)

    def send_move_click(self, x: int, y: int) -> None:
        logger.debug("NoopBackend: drop click (%d, %d)", x, y)

    def press(self, key: str) -> None:
        logger.debug("NoopBackend: drop press %s", key)

    def release(self, key: str) -> None:
        logger.debug("NoopBackend: drop release %s", key)

    def send_stop(self) -> None:
        pass

    def send_screen_size(self, w: int, h: int) -> None:
        pass


# ============================================================
#  Arduino Backend
# ============================================================

class ArduinoBackend(InputBackend):
    def __init__(self, serial_client=None):
        self._client = serial_client
        self._screen_w = 1920
        self._screen_h = 1080

    def set_client(self, client):
        self._client = client

    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    def _send(self, cmd: str):
        if self._client and self._client.is_connected():
            self._client.send(cmd)
        else:
            logger.warning("Arduino not connected — command dropped: %s", cmd)

    def send_key(self, key: str):
        self._send(key.upper())

    def send_move_click(self, x: int, y: int):
        self._send(f"MC_{x}_{y}")

    def press(self, key: str):
        k = key.upper()
        if k in ("LEFT", "RIGHT"):
            self._send(f"{k}_PRESS")
        else:
            self._send(f"KEY_DOWN_{k}")

    def release(self, key: str):
        k = key.upper()
        if k in ("LEFT", "RIGHT"):
            self._send(f"{k}_RELEASE")
        else:
            self._send(f"KEY_UP_{k}")

    def send_stop(self):
        self._send("STOP")

    def send_screen_size(self, w: int, h: int):
        self._screen_w = w
        self._screen_h = h
        self._send(f"SCR_{w}_{h}")
