"""Arduino Leonardo/Micro auto-detection via USB VID/PID."""

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class PortInfo(NamedTuple):
    port: str
    description: str
    hardware_id: str


# USB Vendor IDs for common Arduino boards
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1B4F}
# Product IDs for Leonardo / Micro / Leonardo ETH
LEONARDO_PIDS = {0x8036, 0x0036, 0x8037, 0x800C}


def _safe_discover() -> list:
    """Safely import and list serial ports, returning empty list on any error."""
    try:
        import serial.tools.list_ports
        return list(serial.tools.list_ports.comports())
    except Exception as e:
        logger.warning("Failed to enumerate serial ports: %s", e)
        return []


def discover_arduino_ports() -> list[PortInfo]:
    """Find all connected Arduino Leonardo/Micro boards.

    Returns a list of PortInfo tuples (port_name, description, hardware_id).
    """
    result = []
    for port in _safe_discover():
        # vid/pid can be None for virtual/bluetooth serial ports
        try:
            vid = getattr(port, 'vid', None)
            pid = getattr(port, 'pid', None)
        except Exception:
            continue
        if vid is not None and pid is not None:
            if vid in ARDUINO_VIDS and pid in LEONARDO_PIDS:
                result.append(PortInfo(
                    port=port.device,
                    description=port.description or f"USB VID:{vid:04X} PID:{pid:04X}",
                    hardware_id=getattr(port, 'hwid', '') or "",
                ))
    return result


def list_all_ports() -> list[PortInfo]:
    """List all available serial ports (not just Arduino)."""
    result = []
    for port in _safe_discover():
        result.append(PortInfo(
            port=port.device,
            description=getattr(port, 'description', None) or "Unknown device",
            hardware_id=getattr(port, 'hwid', '') or "",
        ))
    return result


def is_arduino_port(port_name: str) -> bool:
    """Check if a port belongs to an Arduino Leonardo/Micro."""
    for port in _safe_discover():
        if port.device == port_name:
            try:
                vid = getattr(port, 'vid', None)
                pid = getattr(port, 'pid', None)
            except Exception:
                return False
            if vid is not None and pid is not None:
                return vid in ARDUINO_VIDS and pid in LEONARDO_PIDS
    return False
