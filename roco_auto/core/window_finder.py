"""Find game window position and size on Windows."""

import ctypes
from ctypes import wintypes


def find_window_by_title(title_keyword: str) -> dict | None:
    """Find a window whose title contains the keyword. Returns first match."""
    windows = find_all_windows(title_keyword)
    return windows[0] if windows else None


def find_all_windows(title_keyword: str) -> list[dict]:
    """Find ALL windows whose title contains the keyword.

    Each result: {"left", "top", "right", "bottom", "width", "height",
                   "client_width", "client_height", "title", "hwnd", "pid"}
    Uses client rect (content area) for width/height — what matters for click coords.
    """
    user32 = ctypes.windll.user32
    results = []

    def enum_callback(hwnd, _):
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_keyword in buf.value and user32.IsWindowVisible(hwnd):
                # Window rect (outer)
                wrect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(wrect))
                # Client rect (inner content area — what we need)
                crect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(crect))
                # Convert client rect top-left to screen coordinates
                pt = wintypes.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(pt))

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                results.append({
                    "left": pt.x,
                    "top": pt.y,
                    "right": pt.x + crect.right,
                    "bottom": pt.y + crect.bottom,
                    "width": crect.right,
                    "height": crect.bottom,
                    "outer_width": wrect.right - wrect.left,
                    "outer_height": wrect.bottom - wrect.top,
                    "title": buf.value,
                    "hwnd": hwnd,
                    "pid": pid.value,
                })
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return results


def list_all_visible_windows() -> list[dict]:
    """List all visible windows with titles. For dropdown selection."""
    user32 = ctypes.windll.user32
    results = []

    def enum_callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            crect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(crect))
            results.append({
                "title": title,
                "hwnd": hwnd,
                "width": crect.right,
                "height": crect.bottom,
            })
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    # Sort by size descending
    results.sort(key=lambda w: w["width"] * w["height"], reverse=True)
    return results


def find_window_by_process(process_name: str) -> dict | None:
    """Find a window by process name (e.g., '洛克王国.exe')."""
    import subprocess
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    result = {}

    def enum_callback(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        if user32.IsWindowVisible(hwnd) == 0:
            return True

        try:
            process_handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if process_handle:
                buf = ctypes.create_unicode_buffer(260)
                kernel32.QueryFullProcessImageNameW(process_handle, 0, buf, None)
                kernel32.CloseHandle(process_handle)
                if process_name.lower() in buf.value.lower():
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    result["left"] = rect.left
                    result["top"] = rect.top
                    result["right"] = rect.right
                    result["bottom"] = rect.bottom
                    result["width"] = rect.right - rect.left
                    result["height"] = rect.bottom - rect.top
                    result["hwnd"] = hwnd

                    # Also get window title
                    length = user32.GetWindowTextLengthW(hwnd)
                    title_buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, title_buf, length + 1)
                    result["title"] = title_buf.value
                    return False
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return result if result else None
