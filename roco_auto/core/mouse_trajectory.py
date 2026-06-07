"""Human-like mouse movement trajectory generation using Bezier curves."""

import random
import math


def generate_waypoints(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int | None = None,
) -> list[tuple[int, int]]:
    """Generate waypoints for a natural-looking mouse path.

    Uses a cubic Bezier curve with a randomized control point offset
    perpendicular to the straight line between start and end.
    """
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    distance = math.sqrt(dx * dx + dy * dy)

    if steps is None:
        steps = max(10, int(distance / 80))

    # Randomized perpendicular offset for the control point
    offset_magnitude = distance * random.uniform(0.2, 0.5)
    angle = math.atan2(dy, dx) + math.pi / 2
    offset_x = offset_magnitude * math.cos(angle)
    offset_y = offset_magnitude * math.sin(angle)

    # Control point: midpoint + random offset + random overshoot
    mid_x = (x1 + x2) / 2 + offset_x + random.uniform(-50, 50)
    mid_y = (y1 + y2) / 2 + offset_y + random.uniform(-50, 50)

    waypoints = []
    for i in range(steps + 1):
        t = i / steps
        # Cubic Bezier: B(t) = (1-t)^3*P0 + 3(1-t)^2*t*P1 + 3(1-t)*t^2*P2 + t^3*P3
        u = 1 - t
        x = u**3 * x1 + 3 * u**2 * t * mid_x + 3 * u * t**2 * mid_x + t**3 * x2
        y = u**3 * y1 + 3 * u**2 * t * mid_y + 3 * u * t**2 * mid_y + t**3 * y2
        waypoints.append((int(x), int(y)))

    # Add micro-jitter: every few points gets a tiny offset
    for i in range(len(waypoints)):
        if i % 3 == 0 and 0 < i < len(waypoints) - 1:
            wx, wy = waypoints[i]
            waypoints[i] = (
                wx + random.randint(-2, 2),
                wy + random.randint(-2, 2),
            )

    return waypoints


def waypoints_to_commands(
    waypoints: list[tuple[int, int]],
) -> list[str]:
    """Convert waypoints to MOVE_REL commands for the Arduino."""
    commands = []
    prev = waypoints[0]
    for pt in waypoints[1:]:
        dx = pt[0] - prev[0]
        dy = pt[1] - prev[1]
        if dx != 0 or dy != 0:
            commands.append(f"MOVE_REL_{dx}_{dy}")
        prev = pt
    return commands
