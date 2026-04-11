"""User configuration — loads from and saves to ~/.clippy_config.json.

All other modules read config through this module, never directly from disk.
This module has no imports from within the clippy package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH: Path = Path.home() / ".clippy_config.json"

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
}


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
