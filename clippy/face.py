"""Menu bar icon selection — maps current activity state to an icon string.

face.py imports from clippy.config and clippy.monitor because app.py passes
live instances in. This is expected per ARCHITECTURE.md: face.py sits one
layer above the leaf modules.
"""

from __future__ import annotations

from clippy.config import Config
from clippy.monitor import Monitor


class Face:
    """Maps monitor state to a menu bar icon string.

    Rules (evaluated in priority order):
    1. Idle longer than idle_threshold  → idle face
    2. Same app longer than long_app_threshold → long_session face
    3. Otherwise → default face
    """

    def __init__(self, config: Config, monitor: Monitor) -> None:
        """Store references to the shared config and monitor instances."""
        self._config = config
        self._monitor = monitor

    def current_icon(self) -> str:
        """Return the icon string appropriate for the current activity state.

        Reads thresholds from config and state from monitor on every call so
        it always reflects the latest values without needing to be reset.
        """
        faces: dict = self._config.get("faces", {})
        idle_threshold: int = self._config.get("idle_threshold", 300)
        long_app_threshold: int = self._config.get("long_app_threshold", 7200)

        if self._monitor.idle_duration() >= idle_threshold:
            return faces.get("idle", "💤")

        if self._monitor.current_app_duration() >= long_app_threshold:
            return faces.get("long_session", "⚠️")

        return faces.get("default", "📎")
