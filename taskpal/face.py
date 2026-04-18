"""Menu bar icon selection — maps current activity state to an icon string.

face.py imports from taskpal.config and taskpal.monitor because app.py passes
live instances in. This is expected per ARCHITECTURE.md: face.py sits one
layer above the leaf modules.
"""

from __future__ import annotations

from datetime import datetime

from taskpal.config import Config
from taskpal.monitor import Monitor


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

    def current_chat_face(self) -> str:
        """Return an expressive emoji for the chat window header.

        Priority order (highest to lowest):
        1. snooze_count >= 3 on any pending reminder → 😡
        2. Win logged in last 30 min → 🥳
        3. Multiple wins today (>= 3) → 😎
        4. Idle > 30 min → 😴
        5. Idle > 5 min → 🤔
        6. Same app > 2 hrs → 😤
        7. Any pending reminder with snooze_count >= 1 → 😬
        8. Late night (after 11pm) → 🌙
        9. Default → 😊
        """
        import json
        import os
        from datetime import timedelta

        now = datetime.now()

        # Load pending reminders
        pending: list[dict] = []
        pending_path = os.path.expanduser("~/.taskpal_pending_reminders.json")
        try:
            if os.path.exists(pending_path):
                with open(pending_path) as f:
                    pending = json.load(f)
        except Exception:
            pass

        # Load completions
        completions: list[dict] = []
        completions_path = os.path.expanduser("~/.taskpal_completions.json")
        try:
            if os.path.exists(completions_path):
                with open(completions_path) as f:
                    completions = json.load(f)
        except Exception:
            pass

        # Priority 1 — any reminder snoozed 3+ times
        if any(r.get("snooze_count", 0) >= 3 for r in pending):
            return "😡"

        # Priority 2 — win in last 30 min
        cutoff_30 = now - timedelta(minutes=30)
        recent_wins = [
            c for c in completions
            if datetime.fromisoformat(
                c.get("completed_at", "1970-01-01")
            ) >= cutoff_30
        ]
        if recent_wins:
            return "🥳"

        # Priority 3 — 3+ wins today
        cutoff_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        wins_today = [
            c for c in completions
            if datetime.fromisoformat(
                c.get("completed_at", "1970-01-01")
            ) >= cutoff_today
        ]
        if len(wins_today) >= 3:
            return "😎"

        # Priority 4 — idle > 30 min
        if self._monitor.idle_duration() >= 1800:
            return "😴"

        # Priority 5 — idle > 5 min
        if self._monitor.idle_duration() >= 300:
            return "🤔"

        # Priority 6 — same app > 2 hrs
        if self._monitor.current_app_duration() >= 7200:
            return "😤"

        # Priority 7 — any snoozed reminder
        if any(r.get("snooze_count", 0) >= 1 for r in pending):
            return "😬"

        # Priority 8 — late night
        if now.hour >= 23:
            return "🌙"

        return "😊"
