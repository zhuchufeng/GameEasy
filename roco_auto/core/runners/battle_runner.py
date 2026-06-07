"""Auto-battle runner — repeatedly press a skill key at intervals."""

import time
import random

from roco_auto.core.mode_runner import ModeRunner, RunnerContext


class BattleRunner(ModeRunner):
    """Repeatedly press a configured battle skill key."""

    def __init__(
        self,
        ctx: RunnerContext,
        battle_key: str,
        battle_interval: int,
        first_start_delay: int,
        on_tick: callable,
    ):
        super().__init__(ctx)
        self.battle_key = battle_key
        self.battle_interval = battle_interval
        self.first_start_delay = first_start_delay
        self.on_tick = on_tick
        self._count = 0

    def run_loop(self):
        self.ctx.focus_game_window()

        # Initial delay before first action (give user time to switch to game)
        if self.first_start_delay > 0:
            self.ctx.send_wait(self.first_start_delay, variance=0.0)

        while not self._stop_event.is_set():
            self.ctx.send_key(self.battle_key)
            self._count += 1
            try:
                self.on_tick(self._count)
            except Exception:
                pass
            self.ctx.send_wait(self.battle_interval, variance=0.2)
