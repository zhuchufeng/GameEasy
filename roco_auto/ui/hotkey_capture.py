"""Hotkey capture widget — captures key combos via GetAsyncKeyState polling.
No timer — finalizes when all keys are released."""

from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Signal, QTimer
import ctypes, threading

VK_NAMES = {
    0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x1B: "ESC", 0x20: "SPACE",
    0x21: "PAGEUP", 0x22: "PAGEDOWN", 0x23: "END", 0x24: "HOME",
    0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x2C: "PRINT", 0x2D: "INSERT", 0x2E: "DELETE",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5",
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
}
MOD_VKS = {0x11: "CTRL", 0x10: "SHIFT", 0x12: "ALT", 0x5B: "WIN"}

ALL_VKS = (list(range(0x70, 0x7C))
         + list(range(0x30, 0x5B))
         + list(range(0x60, 0x6F))
         + [0x08, 0x09, 0x0D, 0x1B, 0x20,
            0x21, 0x22, 0x23, 0x24,
            0x25, 0x26, 0x27, 0x28,
            0x2C, 0x2D, 0x2E,
            0x6A, 0x6B, 0x6D, 0x6E, 0x6F,
            0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
            0xC0, 0xDB, 0xDC, 0xDD, 0xDE])


class HotkeyCapture(QPushButton):
    key_changed = Signal(str)
    _capture_signal = Signal(str)
    _is_dark = True
    _any_capturing = False

    def __init__(self, default_key: str = "", parent=None):
        super().__init__(parent)
        self._key = default_key
        self._capturing = False
        self._captured: list[str] = []
        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finalize)
        self._capture_signal.connect(self._set)
        self._update_text()
        self.clicked.connect(self._on_click)

    @classmethod
    def set_theme_dark(cls, is_dark: bool):
        cls._is_dark = is_dark

    @property
    def key(self) -> str: return self._key
    @key.setter
    def key(self, value: str): self._key = value; self._update_text()

    def _on_click(self):
        self._capturing = True
        self._last_combo = "..."
        self._final_sequence = []
        self._final_mods = set()
        self._update_text()
        HotkeyCapture._any_capturing = True
        self._poll_run = True

        def poll():
            held_mods = set()
            pressed_all = []
            held_keys = []
            was_pressed = {vk: False for vk in ALL_VKS + list(MOD_VKS.keys())}
            released_count = 0
            while self._poll_run:
                import time; time.sleep(0.03)
                held_mods.clear()
                for mvk, mn in MOD_VKS.items():
                    if ctypes.windll.user32.GetAsyncKeyState(mvk) & 0x8000:
                        held_mods.add(mn)
                any_held = bool(held_mods)
                for vk in ALL_VKS:
                    isd = ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
                    name = VK_NAMES.get(vk)
                    if name is None and 0x20 <= vk <= 0x7E: name = chr(vk)
                    elif name is None and 0x60 <= vk <= 0x69: name = f"NUM{vk-0x60}"
                    elif name is None: name = chr(vk) if 0xBA <= vk <= 0xDE else None
                    if isd and not was_pressed[vk] and name and name not in MOD_VKS.values():
                        pressed_all.append(name)
                        if name not in held_keys: held_keys.append(name)
                    if isd and name and name not in MOD_VKS.values():
                        any_held = True
                    if not isd and was_pressed[vk] and name and name in held_keys:
                        held_keys.remove(name)
                    was_pressed[vk] = isd
                self._final_mods |= held_mods
                display = "+".join(sorted(self._final_mods) + pressed_all) if (self._final_mods or pressed_all) else "..."
                self._capture_signal.emit(display)
                self._final_sequence = pressed_all[:]
                if any_held or held_keys:
                    released_count = 0
                else:
                    released_count += 1
                    if released_count >= 8 and (self._final_mods or pressed_all):
                        self._capture_signal.emit("__DONE__")
                        return
        threading.Thread(target=poll, daemon=True).start()

    def _set(self, combo: str):
        if combo == "__DONE__":
            self._poll_run = False
            return self._done()
        self._last_combo = combo
        self._update_text()

    def _finalize(self):
        self._done()

    def _done(self):
        self._capturing = False; self._poll_run = False
        HotkeyCapture._any_capturing = False
        seq = self._final_sequence
        mods = self._final_mods
        if seq or mods:
            seen = set(); deduped = []
            for k in sorted(mods): deduped.append(k); seen.add(k)
            for k in seq:
                if k not in seen: seen.add(k); deduped.append(k)
            self._key = "+".join(deduped)
        self._update_text()
        self.key_changed.emit(self._key)

    def _update_text(self):
        if self._capturing:
            txt = getattr(self, '_last_combo', '...')
            self.setText(f"按下: {txt}")
            self.setStyleSheet(
                "QPushButton { background:#8b0000; color:#fff; border:1px solid #a00;"
                "border-radius:3px; padding:3px 10px; font-size:11px; min-width:80px; }")
        elif self._key:
            self.setText(f"[{self._key}]")
            self.setStyleSheet(
                "QPushButton { background:#0e639c; color:#fff; border:1px solid #1565a8;"
                "border-radius:3px; padding:3px 10px; font-size:11px; min-width:80px; }")
        else:
            self.setText("点击设置")
            bg = "#3d3d3d" if HotkeyCapture._is_dark else "#e8e8e8"
            c = "#aaa" if HotkeyCapture._is_dark else "#555"
            self.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{c}; border:1px solid #555;"
                "border-radius:3px; padding:3px 10px; font-size:11px; min-width:80px; }}")
