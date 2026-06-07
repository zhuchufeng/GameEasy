"""Serial protocol: encode/decode commands for Arduino firmware.

Protocol format: {CMD}\n  (one command per line)
Examples: {TAB}, {CTRL+C}, {MOVE_500_300}, {MC_500_300}, {WAIT_1000}
"""

from typing import Optional


def encode_command(cmd: str) -> bytes:
    """Encode a command string into wire format (UTF-8 bytes with newline)."""
    return f"{{{cmd}}}\n".encode("utf-8")


def encode_commands(cmds: list[str]) -> bytes:
    """Encode multiple commands into a single byte string."""
    return b"".join(encode_command(c) for c in cmds)


def decode_response(line: str) -> tuple[str, Optional[str]]:
    """Parse a response line from the Arduino.

    Returns (type, payload):
      ("cmd", "STOP")       for "CMD:STOP"
      ("bad", "raw text")   for "BAD:raw text"
      ("ok", "message")     for "OK"
      ("pos", (x, y))       for "POS:500:300"
      ("cfg", params)       for "CFG:1920:1080"
      ("unknown", raw)      for anything else
    """
    line = line.strip()
    if not line:
        return ("empty", None)
    if line == "READY":
        return ("ready", None)
    if line.startswith("CMD:"):
        return ("cmd", line[4:].strip())
    if line.startswith("BAD:"):
        return ("bad", line[4:].strip())
    if line.startswith("OK"):
        return ("ok", line[2:].strip())
    if line.startswith("POS:"):
        parts = line[4:].split(":")
        if len(parts) == 2:
            try:
                return ("pos", (int(parts[0]), int(parts[1])))
            except ValueError:
                pass
    if line.startswith("CFG:"):
        parts = line[4:].split(":")
        if len(parts) == 2:
            try:
                return ("cfg", {"width": int(parts[0]), "height": int(parts[1])})
            except ValueError:
                pass
    return ("unknown", line)


def build_stop_command() -> str:
    """Build the emergency stop command."""
    return "STOP"


def build_screen_config(width: int, height: int) -> str:
    """Build screen resolution configuration command."""
    return f"SCR_{width}_{height}"


def build_wait_command(ms: int) -> str:
    """Build a wait/delay command."""
    return f"WAIT_{ms}"
