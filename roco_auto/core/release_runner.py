"""Release-pets runner — click 6×5 grid, confirm ×4, optionally flip pages."""

import time
import random
import logging

from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class ReleaseRunner(ModeRunner):
    """One-click pet release: 6×5 grid → confirm ×4 → [next page → repeat]."""

    def __init__(self, ctx: RunnerContext,
                 per_step: int = 50,
                 top_left_rel: tuple = (0.15, 0.2),
                 bottom_right_rel: tuple = (0.85, 0.8),
                 confirm_rel: tuple = (0.5, 0.85),
                 final_rel: tuple = (0.5, 0.88),
                 next_page_rel: tuple = (0.9, 0.92),
                 grid_cols: int = 6,
                 grid_rows: int = 5,
                 click_jitter: int = 4,
                 all_pages: bool = False,
                 on_tick: callable = None):
        super().__init__(ctx)
        self.per_step = per_step
        self.top_left_rel = top_left_rel
        self.bottom_right_rel = bottom_right_rel
        self.confirm_rel = confirm_rel
        self.final_rel = final_rel
        self.next_page_rel = next_page_rel
        self.grid_cols = grid_cols
        self.grid_rows = grid_rows
        self.click_jitter = click_jitter
        self.all_pages = all_pages
        self.count = 0
        self.start_time = 0.0
        self._on_tick = on_tick

    # ---- coordinate helpers (private to this runner) ----

    def _rel_to_abs(self, win: dict, rx: float, ry: float,
                    jitter: int = 0) -> tuple:
        x = int(win["left"] + win["width"] * rx) + random.randint(-jitter, jitter)
        y = int(win["top"] + win["height"] * ry) + random.randint(-jitter, jitter)
        return x, y

    def _calc_positions(self, win: dict) -> list:
        x1, y1 = self._rel_to_abs(win, *self.top_left_rel)
        x2, y2 = self._rel_to_abs(win, *self.bottom_right_rel)
        positions = []
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                t_col = col / (self.grid_cols - 1) if self.grid_cols > 1 else 0.5
                t_row = row / (self.grid_rows - 1) if self.grid_rows > 1 else 0.5
                x = int(x1 + (x2 - x1) * t_col)
                y = int(y1 + (y2 - y1) * t_row)
                positions.append((x, y))
        return positions

    def run_loop(self) -> None:
        self.start_time = time.time()
        jitter = self.click_jitter

        while not self._stop_event.is_set():
            self.ctx.focus_game_window()
            win = self.ctx.get_target_window()
            if win is None:
                time.sleep(1)
                continue

            positions = self._calc_positions(win)

            # Step 1: Click all grid positions
            for px, py in positions:
                if self._stop_event.is_set():
                    break
                self.ctx.send_move_click(
                    px + random.randint(-jitter, jitter),
                    py + random.randint(-jitter, jitter))
                self.ctx.send_wait(self.per_step, variance=0.0)

            if self._stop_event.is_set():
                break

            # Step 2: Click confirm button 4 times
            cx, cy = self._rel_to_abs(win, *self.confirm_rel, jitter)
            for _ in range(4):
                if self._stop_event.is_set():
                    break
                self.ctx.send_move_click(cx, cy)
                self.ctx.send_wait(250, variance=0.0)

            self.count += 1
            if self._on_tick:
                self._on_tick(self.count)

            if not self.all_pages:
                # stop_all() is called by the coordinator, not by the runner
                break

            self.ctx.send_wait(500, variance=0.0)
            if self._stop_event.is_set():
                break

            nx, ny = self._rel_to_abs(win, *self.next_page_rel, jitter)
            for _ in range(2):
                self.ctx.send_move_click(nx, ny)
                self.ctx.send_wait(500, variance=0.0)
