"""Battle runner — repeatedly press a battle key at configurable intervals."""

import time
import random
from roco_auto.core.mode_runner import ModeRunner, RunnerContext
from roco_auto.core.anti_detection import randomize_wait


class BattleRunner(ModeRunner):
    """Auto-battle: press battle_key repeatedly with configurable interval."""

    def __init__(self, ctx: RunnerContext,
                 battle_key: str = "1",
                 battle_interval: int = 3000,
                 first_start_delay: int = 5000,
                 on_tick: callable = None):
        super().__init__(ctx)
        self.battle_key = battle_key
        self.battle_interval = battle_interval
        self.first_start_delay = first_start_delay
        self.count = 0
        self.start_time = 0.0
        self._on_tick = on_tick  # called each iteration for counter updates

    def run_loop(self) -> None:
        self.start_time = time.time()
        # Break initial delay into chunks for responsive stop
        elapsed = 0
        delay = self.first_start_delay
        while elapsed < delay and not self._stop_event.is_set():
            chunk = min(200, delay - elapsed)
            time.sleep(chunk / 1000.0)
            elapsed += chunk

        while not self._stop_event.is_set():
            self.ctx.focus_game_window()
            self.ctx.send_key(self.battle_key)
            self.count += 1
            if self._on_tick:
                self._on_tick(self.count)

            interval = randomize_wait(self.battle_interval, 0.3)
            # Chunk the sleep for responsive stop
            waited = 0
            while waited < interval and not self._stop_event.is_set():
                chunk = min(200, interval - waited)
                time.sleep(chunk / 1000.0)
                waited += chunk
