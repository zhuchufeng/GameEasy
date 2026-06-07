"""Throw-ball runner — hold mouse → release → wait → repeat."""

import time

from roco_auto.core.mode_runner import ModeRunner, RunnerContext


class ThrowRunner(ModeRunner):
    """Auto ball throw: hold mouse, release, wait for aim interval, repeat."""

    def __init__(self, ctx: RunnerContext,
                 hold_time: int = 300,
                 base_delay: int = 1200,
                 limit_enabled: bool = False,
                 limit_count: int = 50,
                 limit_action: str = "stop",
                 limit_wait_ms: int = 5000,
                 on_tick: callable = None):
        super().__init__(ctx)
        self.hold_time = hold_time
        self.base_delay = base_delay
        self.limit_enabled = limit_enabled
        self.limit_count = limit_count
        self.limit_action = limit_action
        self.limit_wait_ms = limit_wait_ms
        self.count = 0
        self.start_time = 0.0
        self._on_tick = on_tick

    def run_loop(self) -> None:
        self.start_time = time.time()
        session_throws = 0

        while not self._stop_event.is_set():
            self.ctx.focus_game_window()
            self.ctx.send_hold("LEFT", self.hold_time)
            self.count += 1
            session_throws += 1
            if self._on_tick:
                self._on_tick(self.count)

            if self.limit_enabled and session_throws >= self.limit_count:
                if self.limit_action == "stop":
                    break  # coordinator will call stop_all()
                else:
                    self.ctx.send_wait(self.limit_wait_ms, variance=0.0)
                    session_throws = 0

            self.ctx.send_wait(self.base_delay, variance=0.2)
