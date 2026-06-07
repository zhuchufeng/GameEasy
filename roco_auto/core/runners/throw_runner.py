"""Auto ball-throw runner — hold-and-release mouse loop for catching pets."""

import time
import logging

from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class ThrowRunner(ModeRunner):
    """Simulate hold-mouse → release → wait → repeat for ball throwing.

    Optional limit: stop or wait after N throws.
    """

    def __init__(
        self,
        ctx: RunnerContext,
        hold_time: int,
        base_delay: int,
        limit_enabled: bool,
        limit_count: int,
        limit_action: str,
        limit_wait_ms: int,
        on_tick: callable,
    ):
        super().__init__(ctx)
        self.hold_time = hold_time
        self.base_delay = base_delay
        self.limit_enabled = limit_enabled
        self.limit_count = limit_count
        self.limit_action = limit_action  # "stop" or "wait"
        self.limit_wait_ms = limit_wait_ms
        self.on_tick = on_tick
        self._count = 0

    def run_loop(self):
        self.ctx.focus_game_window()

        while not self._stop_event.is_set():
            # Hold mouse button down (simulate charging the throw)
            self.ctx.send_hold("LEFT", self.hold_time)

            self._count += 1
            try:
                self.on_tick(self._count)
            except Exception:
                pass

            # Limit check
            if self.limit_enabled and self._count >= self.limit_count:
                if self.limit_action == "stop":
                    self._stop_event.set()
                    return
                elif self.limit_action == "wait":
                    self.ctx.send_wait(self.limit_wait_ms, variance=0.1)
                    self._count = 0  # reset counter after wait
                    continue

            # Base delay between throws
            self.ctx.send_wait(self.base_delay, variance=0.2)
