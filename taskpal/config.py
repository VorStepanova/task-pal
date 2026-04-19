"""User configuration — loads from and saves to ~/.taskpal_config.json.

All other modules read config through this module, never directly from disk.
This module has no imports from within the taskpal package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH: Path = Path.home() / ".taskpal_config.json"

DEFAULTS: dict[str, Any] = {
    "idle_threshold": 300,
    "poll_interval": 5,
    "long_app_threshold": 7200,
    "faces": {
        "default": "📎",
        "idle": "💤",
        "long_session": "⚠️",
        "happy": "✅",
    },
    "history_enabled": True,
    "history_retention_days": None,
    "demo": False,
    "activity_share_enabled": True,
}


def is_activity_sharing_enabled() -> bool:
    """Whether monitor data (active app, idle time) may be sent to Claude.

    Reads the config file fresh each call so toggles made in the menu bar
    take effect in the chat subprocess and scheduler thread without a restart.
    Defaults to True to preserve behavior for users who never touch the setting.
    """
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return bool(data.get("activity_share_enabled", True))
        except Exception:
            pass
    return True


def is_demo() -> bool:
    """Check if demo mode is active via TASKPAL_DEMO env var or config file.

    Env var precedence is explicit in both directions — a truthy value forces
    demo on, a falsy value forces it off, even if the config file disagrees.
    Only an absent/empty env var falls through to the config file.
    """
    import os
    raw = os.environ.get("TASKPAL_DEMO", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return bool(data.get("demo", False))
        except Exception:
            pass
    return False


class Config:
    """Persistent user configuration backed by a JSON file.

    On instantiation the config file is read from disk. If the file does not
    exist it is created with sensible defaults so the app never crashes on a
    first run. All writes go to disk immediately so that a restart always
    reflects the latest values.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._load()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the top-level config value for *key*.

        Returns *default* if the key is not present in the loaded config.
        """
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set the top-level config value for *key* and persist to disk immediately."""
        self._data[key] = value
        self._save()

    def reload(self) -> None:
        """Re-read the config file from disk.

        Useful when the user has edited the file by hand and wants changes
        picked up without restarting the app.
        """
        self._load()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read config from disk, falling back to defaults if the file is absent."""
        if CONFIG_PATH.exists():
            try:
                with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
                return
            except (json.JSONDecodeError, OSError):
                pass  # corrupted or unreadable — fall through to defaults
        self._data = dict(DEFAULTS)
        self._save()

    def _save(self) -> None:
        """Write the current config dict to disk as formatted JSON."""
        with CONFIG_PATH.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
