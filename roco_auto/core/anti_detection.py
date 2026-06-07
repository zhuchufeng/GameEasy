"""Humanize automation patterns — make bot-like behavior look human.

Key principles:
  - Humans have rhythm variations — never fixed intervals
  - Humans drift — clicks are never pixel-perfect
  - Humans get tired — delays gradually increase, then reset
  - Humans make micro-errors — occasional hesitation or double-tap
"""

import random
import time
import math


# ═══════════════════════════════════════════════════════════════
#  Core delay randomizers
# ═══════════════════════════════════════════════════════════════

def randomize_wait(base_ms: int, variance_pct: float = 0.2) -> int:
    """Gaussian delay around base_ms."""
    variance = int(base_ms * variance_pct)
    offset = int(random.gauss(0, max(variance / 3, 1)))
    return max(1, base_ms + offset)


def human_reaction_delay() -> int:
    """200-600ms — typical human visual reaction time."""
    return max(100, int(random.gauss(380, 120)))


def key_press_duration() -> int:
    """80-200ms — realistic key hold time."""
    return max(50, int(random.gauss(130, 35)))


def human_click_delay() -> int:
    """50-150ms — time between mouse down and up."""
    return max(30, int(random.gauss(90, 30)))


# ═══════════════════════════════════════════════════════════════
#  Position jitter
# ═══════════════════════════════════════════════════════════════

class PositionJitter:
    """Add human-like pixel drift to click positions.

    Accumulates small random offsets, then gradually resets to origin.
    Simulates natural hand movement — never hits the exact same pixel.
    """

    def __init__(self, max_drift: int = 4):
        self._x = 0.0
        self._y = 0.0
        self._max = max_drift

    def apply(self, x: int, y: int) -> tuple[int, int]:
        """Return (x, y) with accumulated jitter applied."""
        # Brownian-like drift
        self._x += random.gauss(0, 0.6)
        self._y += random.gauss(0, 0.6)
        # Pull back toward zero (elastic)
        self._x *= 0.85
        self._y *= 0.85
        # Clamp
        self._x = max(-self._max, min(self._max, self._x))
        self._y = max(-self._max, min(self._max, self._y))
        return int(x + self._x), int(y + self._y)


# ═══════════════════════════════════════════════════════════════
#  Rhythm engine — simulates human attention patterns
# ═══════════════════════════════════════════════════════════════

class HumanRhythm:
    """Generates delays that mimic human attention rhythms.

    Humans operate in bursts: fast for a while, then a micro-pause, then fast again.
    Fixed delays are the #1 anti-cheat giveaway.
    """

    def __init__(self, base_ms: int, variance_pct: float = 0.25):
        self._base = base_ms
        self._variance = variance_pct
        self._fatigue = 0.0  # 0.0 = fresh, 1.0 = tired
        self._action_count = 0

    def next_delay(self) -> int:
        """Return the next delay in ms, with human-like rhythm."""
        self._action_count += 1

        # Every few actions, add a micro-pause (attention shift)
        if self._action_count % random.randint(8, 20) == 0:
            micro_pause = random.randint(200, 800)
            self._action_count = 0
            return self._base + micro_pause

        # Occasionally add a "hesitation" — slight pause
        if random.random() < 0.05:  # 5% chance
            hesitation = random.randint(100, 500)
            return self._base + hesitation

        # Fatigue: delays gradually increase, then reset
        self._fatigue += random.uniform(0.001, 0.005)
        if self._fatigue > 0.15:
            self._fatigue = 0.0  # "rest" — back to fast

        fatigue_extra = int(self._fatigue * self._base)

        # Base delay + Gaussian variance + fatigue
        base = self._base + fatigue_extra
        variance = int(base * self._variance)
        offset = int(random.gauss(0, max(variance / 3, 1)))
        return max(1, base + offset)

    def reset(self):
        self._fatigue = 0.0
        self._action_count = 0


# ═══════════════════════════════════════════════════════════════
#  Rest simulation — periodic breaks
# ═══════════════════════════════════════════════════════════════

class RestSimulator:
    """Periodically pause automation to simulate taking a break.

    After N actions, pause for M seconds. Humans don't grind nonstop.
    """

    def __init__(self, actions_per_rest: int = 200, rest_min_s: float = 15, rest_max_s: float = 90):
        self._interval = actions_per_rest
        self._rest_min = rest_min_s
        self._rest_max = rest_max_s
        self._count = 0

    def should_rest(self) -> bool:
        """Call after each action. Returns True if it's time to rest."""
        self._count += 1
        if self._count >= self._interval:
            self._count = 0
            self._interval = random.randint(
                int(self._interval * 0.7),
                int(self._interval * 1.3)
            )
            return True
        return False

    def rest_duration(self) -> float:
        """How long to rest in seconds."""
        return random.uniform(self._rest_min, self._rest_max)


# ═══════════════════════════════════════════════════════════════
#  Convenience: all-in-one humanizer
# ═══════════════════════════════════════════════════════════════

class ActionHumanizer:
    """Combines rhythm, position jitter, and rest into one object.

    Usage:
        h = ActionHumanizer(base_delay_ms=3000)
        for action in actions:
            if h.should_rest():
                time.sleep(h.rest_duration())
            x, y = h.jitter(target_x, target_y)
            click(x, y)
            time.sleep(h.next_delay() / 1000.0)
            h.tick()
    """

    def __init__(self, base_delay_ms: int = 1000):
        self.rhythm = HumanRhythm(base_delay_ms)
        self.jitter = PositionJitter(max_drift=4)
        self.rest = RestSimulator()
        self._count = 0

    def next_delay(self) -> int:
        return self.rhythm.next_delay()

    def jitter_pos(self, x: int, y: int) -> tuple[int, int]:
        return self.jitter.apply(x, y)

    def should_rest(self) -> bool:
        return self.rest.should_rest()

    def rest_duration(self) -> float:
        return self.rest.rest_duration()

    def tick(self):
        """Call after each action to advance state."""
        self._count += 1
