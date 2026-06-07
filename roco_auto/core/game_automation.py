"""Game automation routines for 洛克王国减负小助手 v1.1.

Modes (each extracted to a ModeRunner in roco_auto.core.runners):
  - auto_battle       → BattleRunner
  - skip_story        → SkipRunner
  - mine_listen       → MineRunner
  - release_pets      → ReleaseRunner
  - auto_throw        → ThrowRunner

GameAutomation is a thin coordinator: config storage, backend management,
hotkey dispatch, and runner lifecycle.  The UI reads/writes config attrs
directly — they remain on this class for backward compatibility.
"""

import time
import math
import random
import os
import threading
import logging
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

from roco_auto.core.anti_detection import randomize_wait
from roco_auto.core.input_backend import InputBackend, ArduinoBackend, NoopBackend
from roco_auto.core.config_manager import get_app_dir, resolve_model_path
from roco_auto.core.mode_runner import RunnerContext, ModeRunner


# ── Known config keys for stale-key cleanup ──
KNOWN_CONFIG_KEYS = {
    "screen_w", "screen_h",
    "battle_key", "battle_interval", "first_start_delay",
    "skip_yolo_model", "skip_confidence", "skip_poll_interval",
    "mine_switch_delay",
    "release_per_step", "release_click_jitter", "release_window_title",
    "release_all_pages", "release_x0", "release_y0", "release_x30", "release_y30",
    "release_confirm_rel", "release_final_rel", "release_next_page_rel",
    "throw_base_delay", "throw_hold_time",
    "throw_limit_enabled", "throw_limit_count",
    "throw_limit_action", "throw_limit_wait_ms",
    "global_random_min", "global_random_max",
    "hotkey_battle", "hotkey_skip", "hotkey_mine",
    "hotkey_release", "hotkey_throw",
    "boxcheck_match_threshold", "boxcheck_check_interval",
    "boxcheck_post_detect_delays", "boxcheck_disappear_frames",
    "boxcheck_cooldown", "boxcheck_point_a", "boxcheck_point_b",
    "boxcheck_monitor_rx1", "boxcheck_monitor_ry1",
    "boxcheck_monitor_rx2", "boxcheck_monitor_ry2",
    "boxcheck_template_paths", "boxcheck_save_enabled",
    "boxcheck_save_folder", "boxcheck_rearm_frames",
    "visitor_model_path", "visitor_win1_title", "visitor_win2_title",
    "visitor_enter_class", "visitor_request_class", "visitor_accept_class",
    "visitor_world_class", "visitor_exit_class",
    "visitor_minimap_classes", "visitor_confidence", "visitor_crop",
    "visitor_sckey", "visitor_notify_title", "visitor_notify_body",
}


class GameAutomation:
    """Coordinator for 洛克王国 automation routines.

    Owns the input backend and config values (read/written by the UI).
    Delegates each automation-mode loop to a ModeRunner implementation.
    """

    def __init__(self):
        self._backend: InputBackend = NoopBackend()  # placeholder until mode selected
        self._state_lock = Lock()
        self._current_runner: Optional[ModeRunner] = None

        # Single toggle hotkey per mode (start/stop)
        self.hotkey_battle = ""
        self.hotkey_skip = ""
        self.hotkey_mine = ""
        self.hotkey_release = ""
        self.hotkey_throw = ""

        # Register mode hotkey handler with the global dispatcher (priority 10 — after capture)
        self._register_hotkey_handler()

        # Default screen resolution
        self.screen_w = 1920
        self.screen_h = 1080

        # Battle defaults
        self.battle_key = "1"
        self.battle_interval = 3000
        self.first_start_delay = 5000

        # Execution counters and timers
        self.battle_count = 0
        self.skip_count = 0
        self.mine_count = 0
        self.release_count = 0
        self.throw_count = 0
        self.battle_start_time = 0.0
        self.skip_start_time = 0.0
        self.mine_start_time = 0.0
        self.release_start_time = 0.0
        self.throw_start_time = 0.0

        # YOLO-based skip story defaults
        self.skip_yolo_model = os.path.join(get_app_dir(), "models", "skip", "skip_model.onnx")
        self.skip_poll_interval = 300
        self.skip_confidence = 0.5
        self._yolo = None

        # Mine/Pet switch defaults (采矿切宠)
        self.mine_switch_keys = ["2", "3", "4", "5", "6"]
        self.mine_switch_delay = 500

        # Release defaults (一键放生)
        self.release_per_step = 50
        self.release_x0 = 0; self.release_y0 = 0  # first circle center (top-left)
        self.release_x30 = 0; self.release_y30 = 0  # last circle center (bottom-right)
        self.release_confirm_rel = (0.5, 0.85)
        self.release_final_rel = (0.5, 0.88)
        self.release_next_page_rel = (0.9, 0.92)
        self.release_grid_cols = 6
        self.release_grid_rows = 5
        self.release_click_jitter = 4
        self.release_all_pages = False
        self.release_window_title = "洛克王国"
        self._target_hwnd = None
        self._target_window_rect: dict | None = None

        # Ball throw defaults (自动丢球)
        self.throw_base_delay = 1200
        self.throw_hold_time = 300
        self.throw_limit_enabled = False
        self.throw_limit_count = 50
        self.throw_limit_action = "stop"
        self.throw_limit_wait_ms = 5000

        # Global random delay applied to ALL modes
        self.global_random_min = 0
        self.global_random_max = 500

        # Mode hotkey dispatch table: hotkey_attr → (start_fn, runner factory)
        self._MODE_HOTKEYS = {
            "hotkey_battle": (self.start_auto_battle,),
            "hotkey_skip": (self.start_skip_story,),
            "hotkey_mine": (self.start_mine_listen,),
            "hotkey_release": (self.start_release_pets,),
            "hotkey_throw": (self.start_auto_throw,),
        }

    # ================================================================
    #  Backend setup
    # ================================================================

    def set_arduino_client(self, client):
        """Switch to Arduino hardware mode."""
        self._backend = ArduinoBackend(client)

    def set_interception_mode(self):
        """Uiohook + Interception mode: global hooks + kernel driver."""
        from roco_auto.core.uiohook_backend import UiohookBackend
        backend = UiohookBackend()
        backend.initialize()
        win = self.get_target_window()
        if win and win.get("hwnd"):
            backend._ctrl.set_window_hwnd(win["hwnd"])
        self._backend = backend

    def get_mode_name(self) -> str:
        if isinstance(self._backend, ArduinoBackend):
            return "Arduino (硬件)"
        from roco_auto.core.uiohook_backend import UiohookBackend
        if isinstance(self._backend, UiohookBackend):
            return "内核驱动"
        return "未设置"

    def is_backend_ready(self) -> bool:
        return self._backend.is_connected()

    # ================================================================
    #  Shared helpers (delegated to RunnerContext for runners)
    # ================================================================

    def _focus_game_window(self):
        """Bring the game window to foreground before sending input."""
        win = self.get_target_window()
        if win and win.get("hwnd"):
            import ctypes
            hwnd = win["hwnd"]
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)

    def _send_wait(self, ms: int, variance: float = 0.2):
        if ms <= 0:
            return
        actual = randomize_wait(ms, variance)
        # Human rhythm: occasional micro-pauses (5% chance)
        if random.random() < 0.05:
            actual += random.randint(100, 600)
        if self.global_random_max > 0:
            extra = random.randint(self.global_random_min, self.global_random_max)
            actual += extra
        # Fatigue drift: delays gradually drift ±20% over time
        drift = (time.time() % 60) / 60.0  # 0-1 sine wave per minute
        actual = int(actual * (0.9 + 0.2 * (0.5 + 0.5 * math.sin(drift * 2 * 3.14159))))
        time.sleep(actual / 1000.0)

    def _send_key(self, key: str):
        self._backend.send_key(key.upper())

    def _send_move_click(self, x: int, y: int):
        # Add micro-jitter: ±3px random offset, never same pixel twice
        jx = x + random.randint(-3, 3)
        jy = y + random.randint(-3, 3)
        self._backend.send_move_click(jx, jy)

    def _send_hold(self, key: str, duration_ms: int):
        self._backend.press(key.upper())
        # Key hold duration varies ±25% — humans don't hold keys for exact ms
        actual_ms = duration_ms + random.randint(-duration_ms // 4, duration_ms // 4)
        time.sleep(max(10, actual_ms) / 1000.0)
        self._backend.release(key.upper())

    def _build_context(self) -> RunnerContext:
        """Create a RunnerContext that delegates to this coordinator's helpers."""
        return RunnerContext(
            backend=self._backend,
            send_key=self._send_key,
            send_wait=self._send_wait,
            send_move_click=self._send_move_click,
            send_hold=self._send_hold,
            focus_game_window=self._focus_game_window,
            get_target_window=self.get_target_window,
            random_min=lambda: self.global_random_min,
            random_max=lambda: self.global_random_max,
        )

    # ================================================================
    #  Control
    # ================================================================

    def stop_all(self):
        """Thread-safe stop — signals the current runner and joins its thread."""
        with self._state_lock:
            runner = self._current_runner
        if runner is not None:
            runner.stop()
            with self._state_lock:
                if self._current_runner is runner:
                    self._current_runner = None
        try:
            self._backend.send_stop()
        except Exception:
            pass  # backend may not be fully initialized (e.g. missing win32api)

    def stop_all_safe(self):
        """Emergency stop — only sets stop flags, never touches backend.
        Prevents interference with Interception passthrough."""
        with self._state_lock:
            runner = self._current_runner
        if runner is not None:
            runner._stop_event.set()
            with self._state_lock:
                if self._current_runner is runner:
                    self._current_runner = None

    def _start_mode(self, runner: ModeRunner,
                    start_time_attr: str) -> bool:
        """Thread-safe mode starter. Returns True if started, False if already running."""
        with self._state_lock:
            if self._current_runner is not None and self._current_runner.is_running():
                return False
            # Stop any previous runner
            if self._current_runner is not None:
                self._current_runner.stop()
            self._current_runner = runner
            now = time.time()
            setattr(self, start_time_attr, now)
            started = runner.start()
            if not started:
                self._current_runner = None
            return started

    def _register_hotkey_handler(self):
        """Mode hotkeys are now registered by MainWindow via GlobalHotkeyManager.
        This method is kept for backward compatibility but does nothing."""
        pass

    def _on_hotkey_event(self, _name: str, combo: str) -> bool:
        """Called by the global dispatcher when a hotkey combo is pressed."""
        self._handle_hotkey(combo)
        return False

    def _handle_hotkey(self, name: str):
        """Toggle mode on/off. Supports multi-key sequences via buffering."""
        if not name:
            return

        try:
            # Buffer key presses for multi-key hotkeys (e.g. "A+B")
            now = time.time()
            if not hasattr(self, '_hk_buffer'):
                self._hk_buffer = []
                self._hk_last = 0.0

            if now - self._hk_last > 0.8:
                self._hk_buffer = []
            self._hk_buffer.append(name)
            self._hk_last = now

            # Build candidate: accumulated sequence
            candidate = "+".join(self._hk_buffer)

            for hotkey_attr, (start_fn,) in self._MODE_HOTKEYS.items():
                hk = getattr(self, hotkey_attr, "")
                if hk and hk == candidate:
                    self._hk_buffer = []
                    if self.is_running():
                        self.stop_all()
                    else:
                        start_fn()
                    return
        except Exception:
            logger.exception("Hotkey handler error")

    def is_running(self) -> bool:
        runner = self._current_runner
        return runner is not None and runner.is_running()

    # ================================================================
    #  Window targeting (used by release runner + interception backend)
    # ================================================================

    def set_target_window(self, hwnd, title):
        """Bind to a specific game window. Once set, operations only target this window."""
        self._target_hwnd = hwnd
        self.release_window_title = title
        self._target_window_rect = None  # force refresh

    def get_target_window(self) -> dict | None:
        """Get the bound game window rect. Only uses the bound hwnd — no fallback search."""
        if self._target_hwnd is not None:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            crect = wintypes.RECT()
            if user32.IsWindow(self._target_hwnd) and user32.GetClientRect(self._target_hwnd, ctypes.byref(crect)):
                pt = wintypes.POINT(0, 0)
                user32.ClientToScreen(self._target_hwnd, ctypes.byref(pt))
                rect = {
                    "left": pt.x, "top": pt.y,
                    "right": pt.x + crect.right, "bottom": pt.y + crect.bottom,
                    "width": crect.right, "height": crect.bottom,
                    "hwnd": self._target_hwnd,
                }
                self._target_window_rect = rect
                return rect
            # Window gone — clear stale hwnd
            self._target_hwnd = None
            self._target_window_rect = None
        return None

    # ================================================================
    #  1. AUTO BATTLE (自动战斗)
    # ================================================================

    def start_auto_battle(self):
        from roco_auto.core.runners.battle_runner import BattleRunner
        runner = BattleRunner(
            ctx=self._build_context(),
            battle_key=self.battle_key,
            battle_interval=self.battle_interval,
            first_start_delay=self.first_start_delay,
            on_tick=lambda c: setattr(self, "battle_count", c),
        )
        if self._start_mode(runner, "battle_start_time"):
            self.battle_count = 0

    # ================================================================
    #  2. SKIP STORY (跳过剧情)
    # ================================================================

    def _get_yolo(self):
        """Lazy-init YOLO model."""
        if self._yolo is not None:
            return self._yolo
        from ultralytics import YOLO
        model_path = resolve_model_path(self.skip_yolo_model, "models")
        if not model_path:
            model_path = os.path.join(get_app_dir(), "models", "skip", "skip_model.onnx")
            logger.warning("skip_yolo_model not found, falling back to: %s", model_path)
        try:
            self._yolo = YOLO(model_path)
        except Exception as e:
            logger.error("YOLO model failed to load: %s", model_path)
            self._yolo = None
        return self._yolo
    def start_skip_story(self, on_status=None, on_detect=None):
        from roco_auto.core.runners.skip_runner import SkipRunner
        runner = SkipRunner(
            ctx=self._build_context(),
            yolo_model=self.skip_yolo_model,
            confidence=self.skip_confidence,
            poll_interval=self.skip_poll_interval,
            on_tick=lambda c: setattr(self, "skip_count", c),
            on_status=on_status,
            on_detect=on_detect,
        )
        if self._start_mode(runner, "skip_start_time"):
            self.skip_count = 0

    # ================================================================
    #  3. MINE / PET SWITCH (采矿切宠)
    # ================================================================

    def start_mine_listen(self):
        from roco_auto.core.runners.mine_runner import MineRunner
        runner = MineRunner(
            ctx=self._build_context(),
            switch_keys=list(self.mine_switch_keys),
            switch_delay=self.mine_switch_delay,
            on_tick=lambda c: setattr(self, "mine_count", c),
        )
        if self._start_mode(runner, "mine_start_time"):
            self.mine_count = 0

    # ================================================================
    #  4. RELEASE PETS (一键放生)
    # ================================================================

    def start_release_pets(self):
        from roco_auto.core.runners.release_runner import ReleaseRunner
        win = self._get_target_window_rect()
        if win and win.get("width", 0) > 0 and win.get("height", 0) > 0:
            top_left_rel = (
                max(0.0, min(1.0, (self.release_x0 - win["left"]) / win["width"])),
                max(0.0, min(1.0, (self.release_y0 - win["top"]) / win["height"])),
            )
            bottom_right_rel = (
                max(0.0, min(1.0, (self.release_x30 - win["left"]) / win["width"])),
                max(0.0, min(1.0, (self.release_y30 - win["top"]) / win["height"])),
            )
        else:
            top_left_rel = (0.15, 0.20)
            bottom_right_rel = (0.85, 0.80)
        runner = ReleaseRunner(
            ctx=self._build_context(),
            per_step=self.release_per_step,
            top_left_rel=top_left_rel,
            bottom_right_rel=bottom_right_rel,
            confirm_rel=self.release_confirm_rel,
            final_rel=self.release_final_rel,
            next_page_rel=self.release_next_page_rel,
            grid_cols=self.release_grid_cols,
            grid_rows=self.release_grid_rows,
            click_jitter=self.release_click_jitter,
            all_pages=self.release_all_pages,
            on_tick=lambda c: setattr(self, "release_count", c),
        )
        if self._start_mode(runner, "release_start_time"):
            self.release_count = 0

    # ================================================================
    #  5. AUTO BALL THROW (自动丢球)
    # ================================================================

    def start_auto_throw(self):
        from roco_auto.core.runners.throw_runner import ThrowRunner
        runner = ThrowRunner(
            ctx=self._build_context(),
            hold_time=self.throw_hold_time,
            base_delay=self.throw_base_delay,
            limit_enabled=self.throw_limit_enabled,
            limit_count=self.throw_limit_count,
            limit_action=self.throw_limit_action,
            limit_wait_ms=self.throw_limit_wait_ms,
            on_tick=lambda c: setattr(self, "throw_count", c),
        )
        if self._start_mode(runner, "throw_start_time"):
            self.throw_count = 0
