"""Mode runner ABC and shared context for GameAutomation mode extraction.

Each automation mode (battle, skip, mine, release, throw) is a ModeRunner
adapter behind a common interface. GameAutomation becomes a thin coordinator.
"""

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional
from roco_auto.core.input_backend import InputBackend


@dataclass
class RunnerContext:
    """Shared dependencies injected into every ModeRunner.

    All send methods delegate to the configured input backend.  Random delay
    settings are stored on the GameAutomation instance; the runner reads them
    via the `random_min` / `random_max` callables so they stay live.
    """

    backend: InputBackend
    send_key: Callable[[str], None]
    send_wait: Callable[[int, float], None]  # (ms, variance)
    send_move_click: Callable[[int, int], None]
    send_hold: Callable[[str, int], None]  # (key, duration_ms)
    focus_game_window: Callable[[], None]
    get_target_window: Callable[[], Optional[dict]]
    random_min: Callable[[], int]
    random_max: Callable[[], int]


class ModeRunner(ABC):
    """Interface for an automation-mode runner.

    Each concrete runner owns its own worker thread and stop signal.
    GameAutomation calls start() / stop() / is_running() — never touches
    the runner's internal thread directly.
    """

    def __init__(self, ctx: RunnerContext):
        self.ctx = ctx
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- public API ----

    @abstractmethod
    def run_loop(self) -> None:
        """The per-mode loop body (runs in a background thread)."""
        ...

    def start(self) -> bool:
        """Launch the runner's loop in a new daemon thread.  Returns True on success."""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._safe_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal the loop to stop and join the worker thread."""
        self._stop_event.set()
        try:
            self.ctx.backend.send_stop()
        except Exception:
            pass  # backend may not be fully initialized (e.g. missing win32api)
        if self._thread is not None and self._thread.is_alive():
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=3.0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- internal ----

    def _safe_loop(self) -> None:
        """Wrapper that catches top-level exceptions so one crash doesn't
        orphan the runner in a half-dead state."""
        try:
            self.run_loop()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Unhandled error in %s", type(self).__name__
            )
        finally:
            self._stop_event.set()
