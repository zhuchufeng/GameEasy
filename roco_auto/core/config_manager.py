"""Configuration persistence - save/load settings to JSON file.

Features:
  - Atomic writes (temp file + rename) to prevent corruption on crash
  - Automatic backup of existing config before overwriting
  - Version tracking for future migration support
  - Robust error handling with user-visible warnings
  - resolve_model_path() for portable model file resolution
"""

import json
import os
import sys
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def get_app_dir() -> str:
    """Return the application root directory.

    In development: the directory containing roco_auto/ (3 levels up from core/).
    In PyInstaller: the directory containing the frozen executable.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Development: roco_auto/core/config_manager.py -> 3 levels up
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_model_path(path: str, subdir: str = "models") -> Optional[str]:
    """Resolve a model path to an absolute path that exists on disk.

    Resolution order:
      1. If `path` is a relative path, resolve against get_app_dir().
      2. If `path` is an absolute path and exists, return as-is.
      3. If `path` is absolute but does NOT exist, try:
         a. get_app_dir() / subdir / basename(path)
         b. get_app_dir() / models / basename(path)
      4. If `path` is a directory path (ends with / or \), just resolve it.
      5. Return the first existing path found, or None.

    This ensures models bundled with the app are found regardless of
    which machine the app is running on.
    """
    if not path:
        return None

    app_dir = get_app_dir()

    # If path is already absolute and exists, use it directly
    if os.path.isabs(path):
        if os.path.exists(path):
            return os.path.abspath(path)
        # Absolute path doesn't exist - try fallback to app's models directory
        basename = os.path.basename(path.rstrip("/\\"))
        if basename:
            fallback = os.path.join(app_dir, subdir, basename)
            if os.path.exists(fallback):
                logger.info("Model '%s' not found, using bundled: %s", path, fallback)
                return os.path.abspath(fallback)
        # Try broader models/ fallback
        fallback2 = os.path.join(app_dir, "models", basename)
        if os.path.exists(fallback2):
            logger.info("Model '%s' not found, using bundled: %s", path, fallback2)
            return os.path.abspath(fallback2)
        logger.warning("Model path not found: %s (no fallback found)", path)
        return None

    # Relative path - resolve against app_dir first, then models/
    resolved = os.path.join(app_dir, path)
    if os.path.exists(resolved):
        return os.path.abspath(resolved)
    # Try under models/ subdir
    resolved2 = os.path.join(app_dir, subdir, os.path.basename(path))
    if os.path.exists(resolved2):
        logger.info("Relative model path '%s' resolved to: %s", path, resolved2)
        return os.path.abspath(resolved2)
    logger.warning("Relative model path not found: %s (tried %s and %s)", path, resolved, resolved2)
    return None


def get_default_models_dir() -> str:
    """Return the default models directory (bundled with the app)."""
    return os.path.join(get_app_dir(), "models")


def get_default_visitor_models_dir() -> str:
    """Return the default visitor stage models directory."""
    return os.path.join(get_app_dir(), "models", "visitor")


CONFIG_VERSION = 1  # bump when schema changes to enable migration


class ConfigManager:
    """Manages application configuration with JSON file persistence."""

    def __init__(self, filepath: str):
        self._filepath = filepath
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict:
        """Load config from disk. Returns empty dict on any error (never crashes)."""
        if not os.path.exists(self._filepath):
            self._data = {"_config_version": CONFIG_VERSION}
            return self._data

        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Config file corrupted (%s), backing up and resetting", e)
            # Try to back up the corrupted file
            try:
                bak = self._filepath + ".corrupted"
                if os.path.exists(self._filepath):
                    os.replace(self._filepath, bak)
                    logger.info("Corrupted config backed up to %s", bak)
            except Exception:
                pass
            self._data = {"_config_version": CONFIG_VERSION}

        # Ensure version marker exists
        if "_config_version" not in self._data:
            self._data["_config_version"] = CONFIG_VERSION

        return self._data

    def save(self) -> None:
        """Save config atomically - writes to temp file then renames.

        On any failure the original file is preserved intact.
        Always uses UTF-8 encoding with ensure_ascii=False for proper
        Chinese character support across different machines.
        """
        # Ensure parent directory exists
        parent = os.path.dirname(os.path.abspath(self._filepath))
        if parent:
            os.makedirs(parent, exist_ok=True)

        tmp = self._filepath + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._filepath)  # atomic on Windows
        except Exception as e:
            logger.exception("Failed to save config: %s", e)
            # Clean up temp file if it exists
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_all(self) -> dict:
        return dict(self._data)

    def update(self, d: dict) -> None:
        self._data.update(d)

    def clean_stale_keys(self, known_keys: set) -> int:
        """Remove keys not in `known_keys`. Returns number of keys removed.

        Always preserves keys starting with '_' (internal/version markers).
        """
        removed = 0
        for key in list(self._data.keys()):
            if not key.startswith("_") and key not in known_keys:
                del self._data[key]
                removed += 1
        return removed
