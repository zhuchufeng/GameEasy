"""Global hotkey manager using GetAsyncKeyState polling.
Keyboard hotkeys + mouse side button — all polled in a single background thread.
Works in-game with admin privileges (Interception driver active).
"""

import ctypes, threading, time, logging

logger = logging.getLogger(__name__)
user32 = ctypes.windll.user32

KEY_MAP = {
    "ESC": 0x1B, "TAB": 0x09, "ENTER": 0x0D, "SPACE": 0x20,
    "BACKSPACE": 0x08, "F1": 0x70, "F2": 0x71, "F3": 0x72,
    "F4": 0x73, "F5": 0x74, "F6": 0x75, "F7": 0x76,
    "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12, "WIN": 0x5B,
}
for i in range(ord('A'), ord('Z') + 1): KEY_MAP[chr(i)] = i
for i in range(ord('0'), ord('9') + 1): KEY_MAP[chr(i)] = i

VK_XBUTTON1 = 0x05


class HotkeyEntry:
    __slots__ = ('name', 'combo', 'callback', '_keys', '_mods')
    def __init__(self, name, combo, callback):
        self.name = name; self.combo = combo; self.callback = callback
        self._keys: list[int] = []   # unique key VKs (deduplicated)
        self._mods: set[int] = set()
        seen = set()
        for p in combo.upper().replace(" ", "").split("+"):
            v = KEY_MAP.get(p, 0)
            if not v and len(p) == 1:
                v = ord(p)
            if v and v not in seen:
                seen.add(v)
                if v in (0x11, 0x10, 0x12, 0x5B):
                    self._mods.add(v)
                self._keys.append(v)

    def all_held(self) -> bool:
        """Check if ALL keys in the combo are currently held."""
        for vk in self._keys:
            if not (user32.GetAsyncKeyState(vk) & 0x8000):
                return False
        return True


class GlobalHotkeyManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._entries: list[HotkeyEntry] = []
            cls._instance._stop_callbacks: list = []
            cls._instance._running = False
            cls._instance._start_poll()
        return cls._instance

    def register(self, name: str, combo: str, callback) -> bool:
        if not combo: return False
        e = HotkeyEntry(name, combo, callback)
        if not e._keys: return False
        self._entries.append(e)
        return True

    def unregister_all(self):
        self._entries.clear()

    def on_global_stop(self, callback):
        self._stop_callbacks.append(callback)

    def _trigger_stop(self):
        for cb in self._stop_callbacks:
            try: cb()
            except Exception: pass

    def _start_poll(self):
        if self._running: return
        self._running = True
        def poll():
            was = {}     # vk → was_down
            was_x1 = False
            while self._running:
                try:
                    # Mouse side button — always active
                    is_x1 = bool(user32.GetAsyncKeyState(VK_XBUTTON1) & 0x8000)
                    if is_x1 and not was_x1:
                        self._trigger_stop()
                    was_x1 = is_x1

                    # Keyboard hotkeys: skip if any HotkeyCapture is active
                    try:
                        from roco_auto.ui.hotkey_capture import HotkeyCapture
                        if HotkeyCapture._any_capturing:
                            time.sleep(0.03); continue
                    except Exception: pass

                    for e in self._entries:
                        if not e._keys: continue
                        last_vk = e._keys[-1]
                        all_held = all(bool(user32.GetAsyncKeyState(v) & 0x8000) for v in e._keys)
                        last_rising = bool(user32.GetAsyncKeyState(last_vk) & 0x8000) and not was.get(last_vk, False)
                        if all_held and last_rising:
                            try: e.callback()
                            except Exception: logger.exception("HK err: %s", e.name)
                        for vk in e._keys:
                            was[vk] = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                    time.sleep(0.02)
                except Exception:
                    logger.exception("Poll error")
                    time.sleep(0.1)
        self._thread = threading.Thread(target=poll, daemon=True, name="HK")
        self._thread.start()

    def shutdown(self):
        self._running = False
        self._entries.clear()





