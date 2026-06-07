"""Entry point: python -m roco_auto. Optionally elevates to admin for driver mode."""

import sys
import os
import ctypes

# Enable DPI awareness BEFORE any Qt imports (fixes 2K/4K screen coordinate issues)
try:
    # Windows 10+ modern API
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        # Windows 8.1 fallback
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_to_admin():
    """Re-launch the script with administrator privileges."""
    if is_admin():
        return True
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        f' -m roco_auto',
        proj_root, 1
    )
    sys.exit(0)


# Auto-elevate to admin (required for Interception driver)
if not is_admin():
    elevate_to_admin()

from roco_auto.app import main
sys.exit(main())
