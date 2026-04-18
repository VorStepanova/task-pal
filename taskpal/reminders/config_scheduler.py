"""Config-based reminder scheduler.

Reads config JSON every 5 minutes and queues the NEXT upcoming reminder
per task into ~/.taskpal_pending_reminders.json. Only one pending entry per
label at a time — the next time slot is queued after the current one is
completed or dismissed. Clears dismissed state at midnight.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta

from taskpal.config import is_demo
from taskpal.reminders.state import is_dismissed_today, DISMISSED_PATH

_REMINDERS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "reminders",
)
_PENDING_PATH = os.path.expanduser("~/.taskpal_pending_reminders.json")
_POLL_INTERVAL = 300  # 5 minutes

_DAY_MAP = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu",
    4: "fri", 5: "sat", 6: "sun",
}


def _config_path() -> str:
    filename = "demo_config.json" if is_demo() else "default_config.json"
    return os.path.join(_REMINDERS_DIR, filename)


def _load_config() -> list[dict]:
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except Exception:
        return []


def _load_pending() -> list[dict]:
    if not os.path.exists(_PENDING_PATH):
        return []
    try:
        with open(_PENDING_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_pending(reminders: list[dict]) -> None:
    try:
        with open(_PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def _purge_foreign_labels(tasks: list[dict]) -> None:
    """Remove pending config-sourced reminders whose labels aren't in the active config."""
    valid_names = {t.get("name", "") for t in tasks}
    existing = _load_pending()
    cleaned = [
        r for r in existing
        if r.get("source") != "config" or r.get("label") in valid_names
    ]
    if len(cleaned) != len(existing):
        _save_pending(cleaned)


def _queue_todays_reminders() -> None:
    now = datetime.now()
    today = _DAY_MAP[now.weekday()]
    tasks = _load_config()
    _purge_foreign_labels(tasks)
    existing = _load_pending()

    existing_labels = {r.get("label") for r in existing}

    new_entries: list[dict] = []
    for task in tasks:
        if not task.get("enabled", True):
            continue
        name = task.get("name", "")
        if name in existing_labels:
            continue
        if is_dismissed_today(name):
            continue
        context = task.get("context", "")
        emoji = task.get("emoji", "")

        next_due: datetime | None = None
        for schedule in task.get("schedule", []):
            if today not in schedule.get("days", []):
                continue
            for time_str in schedule.get("remind_at", []):
                try:
                    hour, minute = map(int, time_str.split(":"))
                except ValueError:
                    continue
                candidate = now.replace(
                    hour=hour, minute=minute,
                    second=0, microsecond=0,
                )
                if candidate <= now:
                    continue
                if next_due is None or candidate < next_due:
                    next_due = candidate

        if next_due is None:
            continue
        new_entries.append({
            "label": name,
            "emoji": emoji,
            "due_at": next_due.isoformat(timespec="seconds"),
            "raw": context,
            "source": "config",
            "created_at": now.isoformat(timespec="seconds"),
        })
        existing_labels.add(name)

    if new_entries:
        existing.extend(new_entries)
        _save_pending(existing)


def _clear_dismissed() -> None:
    """Remove stale entries from the dismissed file at midnight."""
    if not os.path.exists(DISMISSED_PATH):
        return
    try:
        with open(DISMISSED_PATH) as f:
            dismissed = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        cleaned = {k: v for k, v in dismissed.items() if v == today}
        with open(DISMISSED_PATH, "w") as f:
            json.dump(cleaned, f, indent=2)
    except Exception:
        pass


def _seconds_until_midnight() -> float:
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=1, second=0, microsecond=0
    )
    return (midnight - now).total_seconds()


def _loop() -> None:
    _queue_todays_reminders()
    last_date = datetime.now().date()
    while True:
        time.sleep(_POLL_INTERVAL)
        try:
            current_date = datetime.now().date()
            if current_date != last_date:
                _clear_dismissed()
                last_date = current_date
            _queue_todays_reminders()
        except Exception:
            pass


def start() -> None:
    """Start the config scheduler daemon thread. Call once from app.py."""
    t = threading.Thread(
        target=_loop, daemon=True, name="taskpal-config-scheduler"
    )
    t.start()
