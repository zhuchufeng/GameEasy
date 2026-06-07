"""Mine/pet-switch runner — listen for mouse release, then cycle pets 2→3→4→5→6."""

import time
import threading
from collections import deque
import logging

from roco_auto.core.mode_runner import ModeRunner, RunnerContext

logger = logging.getLogger(__name__)


class MineRunner(ModeRunner):
    """Mine pet-switch: monitor mouse-up events, then cycle through pet hotkeys.

    Uses a single reusable worker thread with a request queue instead of
    spawning a new thread per click — prevents thread explosion under
    rapid clicking.
    """

    def __init__(self, ctx: RunnerContext,
                 switch_keys: list = None,
                 switch_delay: int = 500,
                 on_tick: callable = None):
        super().__init__(ctx)
        self.switch_keys = switch_keys or ["2", "3", "4", "5", "6"]
        self.switch_delay = switch_delay
        self.count = 0
        self.start_time = 0.0
        self._on_tick = on_tick
        self._switch_lock = threading.Lock()
        self._pending: deque = deque()  # queue of (key, expected_idx)

    def _switch_worker(self, state):
        """Single worker thread: dequeues switch requests with delay."""
        delay_sec = self.switch_delay / 1000.0
        while not self._stop_event.is_set():
            try:
                key, expected_idx = self._pending.popleft()
            except IndexError:
                time.sleep(0.05)
                continue

            time.sleep(delay_sec)
            if self._stop_event.is_set():
                return
            with self._switch_lock:
                if state.idx == expected_idx:
                    self.ctx.send_key(key)
                    self.count += 1
                    if self._on_tick:
                        self._on_tick(self.count)
                    state.idx += 1
                state.busy = False

    def run_loop(self) -> None:
        self.start_time = time.time()
        try:
            from pynput import mouse

            class _SwitchState:
                def __init__(self):
                    self.idx = 0
                    self.busy = False

            state = _SwitchState()

            # Single reusable worker — replaces per-click Thread()
            worker = threading.Thread(
                target=self._switch_worker,
                args=(state,),
                daemon=True,
                name="mine-switch-worker",
            )
            worker.start()

            def on_click(x, y, button, pressed):
                if self._stop_event.is_set():
                    return False
                if not pressed and button == mouse.Button.left:
                    with self._switch_lock:
                        if state.busy:
                            return  # drop duplicate clicks during switch
                        state.busy = True
                        key = self.switch_keys[state.idx % len(self.switch_keys)]
                        expected = state.idx
                    self._pending.append((key, expected))

            with mouse.Listener(on_click=on_click) as listener:
                while not self._stop_event.is_set():
                    time.sleep(0.1)
                listener.stop()

            worker.join(timeout=3.0)
        except Exception:
            logger.exception("Failed to start mine mouse listener")
