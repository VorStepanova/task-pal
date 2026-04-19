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
from taskpal.reminders.state import (
    DISMISSED_PATH, is_dismissed_today, sync_mode_marker,
)

_REMINDERS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "reminders",
)
_PENDING_PATH = os.path.expanduser("~/.taskpal_pending_reminders.json")
_POLL_INTERVAL = 60  # 1 minute — so a missed-slot grace window is small
_GRACE_MINUTES = 60  # allow queueing a time up to this many minutes in the past

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

    # Only pending rows block re-queueing. Done/dismissed rows exist for UX
    # (so the user can flip them back) but must not prevent the next slot.
    blocking_labels = {
        r.get("label") for r in existing
        if r.get("status", "pending") == "pending"
    }

    grace_cutoff = now - timedelta(minutes=_GRACE_MINUTES)

    new_entries: list[dict] = []
    labels_being_queued: set[str] = set()
    for task in tasks:
        if not task.get("enabled", True):
            continue
        name = task.get("name", "")
        if name in blocking_labels:
            continue
        if is_dismissed_today(name):
            continue
        context = task.get("context", "")
        emoji = task.get("emoji", "")

        # Pick the closest-to-now slot that hasn't aged past the grace window.
        # A missed slot within grace wins over a future one so the user sees
        # the reminder they actually just missed. Scheduler fires it on its
        # next tick since due_at <= now.
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
                if candidate < grace_cutoff:
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
            "status": "pending",
            "created_at": now.isoformat(timespec="seconds"),
        })
        labels_being_queued.add(name)
        blocking_labels.add(name)

    if new_entries:
        # Drop stale done/dismissed rows for any label being re-queued, so the
        # menu shows the fresh pending row instead of both.
        existing = [
            r for r in existing
            if not (
                r.get("label") in labels_being_queued
                and r.get("status") in ("done", "dismissed")
            )
        ]
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


def _purge_stale() -> None:
    """Drop pending rows whose effective fire time is before today.

    Handles done/dismissed rows (kept for UX during the day) and pending rows
    whose due_at slipped past without firing (app was off, machine was asleep,
    etc.). A row with a future next_fire_at is kept regardless of due_at.
    """
    if not os.path.exists(_PENDING_PATH):
        return
    try:
        with open(_PENDING_PATH) as f:
            reminders = json.load(f)
        today = datetime.now().date()
        cleaned = []
        for r in reminders:
            effective = r.get("next_fire_at") or r.get("due_at", "")
            try:
                if datetime.fromisoformat(effective).date() < today:
                    continue
            except (ValueError, TypeError):
                pass
            cleaned.append(r)
        if len(cleaned) != len(reminders):
            _save_pending(cleaned)
    except Exception:
        pass


def _seconds_until_midnight() -> float:
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=1, second=0, microsecond=0
    )
    return (midnight - now).total_seconds()


def _loop() -> None:
    # If demo-mode toggled since last run, pending state is stale — wipe it
    # before queuing today's reminders so old demo/default entries don't linger.
    sync_mode_marker(is_demo())
    _queue_todays_reminders()
    last_date = datetime.now().date()
    while True:
        time.sleep(_POLL_INTERVAL)
        try:
            current_date = datetime.now().date()
            if current_date != last_date:
                _clear_dismissed()
                _purge_stale()
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
