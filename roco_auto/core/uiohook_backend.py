"""Input backend using uiohook global hooks + Interception driver.

MaaXXX analysis revealed: uiohook's WH_KEYBOARD_LL/WH_MOUSE_LL hooks
must be installed to establish the input context. Once hooks are active,
interception.dll events can reach the game. Without hooks, they can't.
"""

import ctypes
import ctypes.wintypes
import threading
import time
import logging
logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

# Must be kept alive at module scope to prevent GC
_hook_proc_kbd = None
_hook_proc_mouse = None
_hook_kbd = None
_hook_mouse = None
_hook_running = False
_hook_thread = None


from roco_auto.core.interception_controller import find_interception_dll as _find_interception_dll


def _message_pump():
    """Message pump for low-level hooks. Uses GetMessage (blocking) for
    minimal latency — no sleep loop that would slow mouse movement."""
    global _hook_running
    msg = ctypes.wintypes.MSG()
    while _hook_running:
        # GetMessage blocks until a message arrives — zero CPU waste, zero latency
        if user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# Named callback functions — must be module-level (not lambdas) to prevent
# garbage-collection of the ctypes thunks, which would crash the process when
# Windows calls into deallocated memory.
@ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                     ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
def _kbd_hook_proc(nCode, wParam, lParam):
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


@ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                     ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
def _mouse_hook_proc(nCode, wParam, lParam):
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def install_uiohook_hooks():
    """Install WH_KEYBOARD_LL and WH_MOUSE_LL global hooks.

    These hooks create the input context that allows Interception/PS2
    events to penetrate into RawInput-protected games.

    MUST be called from a thread with a Windows message pump.
    """
    global _hook_kbd, _hook_mouse, _hook_proc_kbd, _hook_proc_mouse
    global _hook_running, _hook_thread

    _hook_proc_kbd = _kbd_hook_proc
    _hook_proc_mouse = _mouse_hook_proc

    _hook_kbd = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _hook_proc_kbd, 0, 0)
    _hook_mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, _hook_proc_mouse, 0, 0)

    if not _hook_kbd:
        err = ctypes.get_last_error()
        logger.error("SetWindowsHookExW(WH_KEYBOARD_LL) failed: error %d", err)
    if not _hook_mouse:
        err = ctypes.get_last_error()
        logger.error("SetWindowsHookExW(WH_MOUSE_LL) failed: error %d", err)

    if not _hook_kbd or not _hook_mouse:
        _hook_running = False
        logger.critical("Hook installation failed — input context not established")
        return

    logger.info("uiohook-style hooks: kbd=%d mouse=%d", _hook_kbd, _hook_mouse)

    _hook_running = True
    _message_pump()


def start_hooks():
    """Start hook thread and wait for hooks to be active."""
    global _hook_thread
    if _hook_thread is not None:
        return
    _hook_thread = threading.Thread(target=install_uiohook_hooks, daemon=True)
    _hook_thread.start()
    time.sleep(0.15)  # Wait for hooks to install


def stop_hooks():
    global _hook_running
    _hook_running = False
    if _hook_kbd:
        user32.UnhookWindowsHookEx(_hook_kbd)
    if _hook_mouse:
        user32.UnhookWindowsHookEx(_hook_mouse)


class UiohookBackend:
    """Input backend: uiohook-style global hooks + InterceptionController."""

    def __init__(self):
        self._ctrl = None
        self._initialized = False
        self._held_vk: set[int] = set()

    def is_connected(self) -> bool:
        return self._initialized

    def initialize(self) -> bool:
        try:
            # Step 1: Install global hooks (creates input context)
            start_hooks()

            # Step 2: Initialize Interception (same as MaaXXX)
            from roco_auto.core.interception_controller import InterceptionController
            dll_path = _find_interception_dll()
            self._ctrl = InterceptionController(dll_path)
            self._ctrl.initialize()
            self._ctrl.discover_keyboard_device(timeout_ms=5000)
            self._ctrl.discover_mouse_device()
            self._ctrl.start_passthrough()
            self._initialized = True
            return True
        except Exception as e:
            logger.exception("UiohookBackend init failed: %s", e)
            return False

    def send_key(self, key: str):
        if not self._ctrl or self._ctrl.keyboard_device is None:
            return
        if not key or not isinstance(key, str):
            return
        from roco_auto.core.input_backend import _resolve_vk
        vk = _resolve_vk(key.upper())
        if not vk and len(key) == 1:
            vk = ord(key.upper())
        if vk:
            self._ctrl.click_key(vk)

    def send_move_click(self, x: int, y: int):
        if not self._ctrl or not self._ctrl.mouse_device:
            return
        ix = int(x * 65535 / max(self._ctrl._screen_width, 1))
        iy = int(y * 65535 / max(self._ctrl._screen_height, 1))
        self._ctrl._send_mouse_event(0x001, 0x001, x=ix, y=iy)
        time.sleep(0.05)
        self._ctrl._send_mouse_event(0x002, 0x001, x=ix, y=iy)

    def send_stop(self):
        for vk in list(self._held_vk):
            self._ctrl.key_up(vk)
        self._held_vk.clear()

    def press(self, key: str):
        if not self._ctrl or self._ctrl.keyboard_device is None:
            return
        from roco_auto.core.input_backend import _resolve_vk
        vk = _resolve_vk(key.upper())
        if not vk and len(key) == 1:
            vk = ord(key.upper())
        if vk:
            self._ctrl.key_down(vk)
            self._held_vk.add(vk)

    def release(self, key: str):
        if not self._ctrl or self._ctrl.keyboard_device is None:
            return
        from roco_auto.core.input_backend import _resolve_vk
        vk = _resolve_vk(key.upper())
        if not vk and len(key) == 1:
            vk = ord(key.upper())
        if vk:
            self._ctrl.key_up(vk)
            self._held_vk.discard(vk)

    def send_screen_size(self, w, h):
        if self._ctrl:
            self._ctrl._screen_width = w
            self._ctrl._screen_height = h

    def shutdown(self):
        stop_hooks()
        if self._ctrl:
            self._ctrl.shutdown()
        self._initialized = False
