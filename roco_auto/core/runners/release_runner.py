"""Release-pets runner — batch release pets from backpack grid (6×5=30/page).

Grid: 6 columns × 5 rows = 30 slots per page.
Positions: x = x0 + col * dx,  y = y0 + row * dy  (col=0..5, row=0..4)

Flow: Phase 1: click all 30 pet slots → Phase 2: confirm each one.
"""

import time
import random
import logging

from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class ReleaseRunner(ModeRunner):
    def __init__(
        self,
        ctx: RunnerContext,
        per_step: int,
        x0: int, y0: int,
        x30: int, y30: int,
        grid_cols: int,
        grid_rows: int,
        confirm_rel: tuple[float, float],
        final_rel: tuple[float, float],
        next_page_rel: tuple[float, float],
        click_jitter: int,
        all_pages: bool,
        on_tick: callable,
    ):
        super().__init__(ctx)
        self.per_step = per_step
        self.x0 = x0; self.y0 = y0
        # Compute spacing from first (0,0) and last (cols-1, rows-1) circles
        self.dx = (x30 - x0) // max(grid_cols - 1, 1)
        self.dy = (y30 - y0) // max(grid_rows - 1, 1)
        self.grid_cols = grid_cols
        self.grid_rows = grid_rows
        self.confirm_rel = confirm_rel
        self.final_rel = final_rel
        self.next_page_rel = next_page_rel
        self.click_jitter = click_jitter
        self.all_pages = all_pages
        self.on_tick = on_tick
        self._count = 0

    def _grid_positions(self) -> list[tuple[int, int]]:
        """Compute absolute screen coordinates for each grid cell."""
        positions = []
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                x = self.x0 + col * self.dx
                y = self.y0 + row * self.dy
                positions.append((x, y))
        return positions

    def _click_abs(self, px: int, py: int):
        """Click at absolute screen coordinates, with jitter."""
        if self.click_jitter > 0:
            px += random.randint(-self.click_jitter, self.click_jitter)
            py += random.randint(-self.click_jitter, self.click_jitter)
        self.ctx.send_move_click(px, py)

    def _click_rel(self, rx: float, ry: float):
        """Click at a relative position within the game window."""
        win = self.ctx.get_target_window()
        if not win:
            return
        px = int(win["left"] + win["width"] * rx)
        py = int(win["top"] + win["height"] * ry)
        if self.click_jitter > 0:
            px += random.randint(-self.click_jitter, self.click_jitter)
            py += random.randint(-self.click_jitter, self.click_jitter)
        self.ctx.send_move_click(px, py)

    def _release_page(self):
        """Release one full page of pets."""
        positions = self._grid_positions()

        # Phase 1: Click all 30 pet slots
        for i, (x, y) in enumerate(positions):
            if self._stop_event.is_set():
                return
            self._click_abs(x, y)
            self.ctx.send_wait(self.per_step, variance=0.1)

        # Phase 2: Confirm — 4 clicks, longer delay before 4th
        for i in range(4):
            if self._stop_event.is_set(): return
            if i == 3:
                self.ctx.send_wait(400, variance=0.1)  # wait for UI transition
            self._click_rel(*self.confirm_rel)
            self.ctx.send_wait(150, variance=0.1)
        # Final confirm
        self._click_rel(*self.final_rel)
        self.ctx.send_wait(self.per_step * 2, variance=0.2)

        self._count += len(positions)
        try:
            self.on_tick(self._count)
        except Exception:
            pass

    def run_loop(self):
        self.ctx.focus_game_window()
        while not self._stop_event.is_set():
            self._release_page()
            if not self.all_pages:
                self._stop_event.set()
                return
            self._click_rel(*self.next_page_rel)
            self.ctx.send_wait(self.per_step * 2, variance=0.3)
