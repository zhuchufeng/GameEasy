"""Mine pet-switch runner — cycle pets after mouse release during mining."""

import time
import logging

from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class MineRunner(ModeRunner):
    """Listen for mouse-left release, then cycle through pet switch keys
    (2→3→4→5→6→2→…). Used during mining where each pet mines one ore."""

    def __init__(
        self,
        ctx: RunnerContext,
        switch_keys: list[str],
        switch_delay: int,
        on_tick: callable,
    ):
        super().__init__(ctx)
        self.switch_keys = switch_keys or ["2", "3", "4", "5", "6"]
        self.switch_delay = switch_delay
        self.on_tick = on_tick
        self._count = 0
        self._idx = 0
        # Track mouse state: detect left-button release transitions
        self._mouse_was_down = False

    def run_loop(self):
        self.ctx.focus_game_window()
        import ctypes

        while not self._stop_event.is_set():
            # Poll mouse left button state via Win32
            is_down = (ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000) != 0

            # Detect button-up transition (was down, now up)
            if self._mouse_was_down and not is_down:
                # Mouse button released — switch to next pet
                if self.switch_delay > 0:
                    self.ctx.send_wait(self.switch_delay, variance=0.1)

                key = self.switch_keys[self._idx % len(self.switch_keys)]
                self.ctx.send_key(key)
                self._idx += 1
                self._count += 1
                try:
                    self.on_tick(self._count)
                except Exception:
                    pass

            self._mouse_was_down = is_down
            # Fast polling (mouse event detection needs low latency)
            self.ctx.send_wait(20, variance=0.0)
