"""State management for pending reminders.

Converts raw extractor output (due_in_minutes) into absolute due_at
timestamps and rewrites ~/.taskpal_pending_reminders.json in resolved form.
Deduplicates by (label, due_at) so repeated extractions don't stack.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

PENDING_PATH = os.path.expanduser("~/.taskpal_pending_reminders.json")
COMPLETIONS_PATH = os.path.expanduser("~/.taskpal_completions.json")
DISMISSED_PATH = os.path.expanduser("~/.taskpal_dismissed_today.json")


def _load_raw() -> list[dict]:
    if not os.path.exists(PENDING_PATH):
        return []
    try:
        with open(PENDING_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def load_pending() -> list[dict]:
    """Read ~/.taskpal_pending_reminders.json without resolving or rewriting."""
    return _load_raw()


def log_fired(label: str) -> None:
    """Append a reminder completion to ~/.taskpal_completions.json."""
    existing: list[dict] = []
    if os.path.exists(COMPLETIONS_PATH):
        try:
            with open(COMPLETIONS_PATH) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.append({
        "task": label,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "reminder",
    })
    try:
        with open(COMPLETIONS_PATH, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


def remove_fired(label: str, due_at: str) -> None:
    """Remove one reminder from the pending file by (label, due_at)."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        reminders = [
            r for r in reminders
            if not (r.get("label") == label and r.get("due_at") == due_at)
        ]
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def _save(reminders: list[dict]) -> None:
    try:
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def _resolve(raw: dict, now: datetime) -> dict | None:
    """Convert a raw reminder dict to a resolved one with due_at.

    Returns None if the reminder is already resolved (has due_at) or
    if due_in_minutes is missing/invalid.
    """
    if "due_at" in raw:
        return raw  # already resolved, pass through
    try:
        minutes = int(raw["due_in_minutes"])
    except (KeyError, ValueError, TypeError):
        return None  # malformed, discard
    return {
        "label": raw.get("label", "Reminder"),
        "due_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
        "raw": raw.get("raw", ""),
        "created_at": now.isoformat(timespec="seconds"),
    }


def _deduplicate(reminders: list[dict]) -> list[dict]:
    """Remove duplicates by (label, due_at) keeping first occurrence."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for r in reminders:
        key = (r.get("label", ""), r.get("due_at", ""))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def dismiss_today(label: str) -> None:
    """Mark a reminder label as dismissed for today. Removes all pending entries."""
    today = datetime.now().strftime("%Y-%m-%d")
    dismissed: dict[str, str] = {}
    if os.path.exists(DISMISSED_PATH):
        try:
            with open(DISMISSED_PATH) as f:
                dismissed = json.load(f)
        except Exception:
            pass
    dismissed[label] = today
    try:
        with open(DISMISSED_PATH, "w") as f:
            json.dump(dismissed, f, indent=2)
    except Exception:
        pass
    remove_all_for_label(label)


def is_dismissed_today(label: str) -> bool:
    """Check if a label was dismissed today."""
    if not os.path.exists(DISMISSED_PATH):
        return False
    try:
        with open(DISMISSED_PATH) as f:
            dismissed = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        return dismissed.get(label) == today
    except Exception:
        return False


def remove_all_for_label(label: str) -> None:
    """Remove all pending reminders matching a label."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        reminders = [r for r in reminders if r.get("label") != label]
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def snooze_for_hours(label: str, hours: int) -> None:
    """Snooze all pending reminders for a label by N hours."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        target = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds")
        for r in reminders:
            if r.get("label") == label:
                r["next_fire_at"] = target
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def resolve_pending() -> list[dict]:
    """Load, resolve, deduplicate, and rewrite the pending reminders file.

    Returns the resolved list so the scheduler can use it directly
    without reading the file again.
    """
    now = datetime.now()
    raw_list = _load_raw()
    resolved = [r for raw in raw_list if (r := _resolve(raw, now)) is not None]
    deduped = _deduplicate(resolved)
    _save(deduped)
    return deduped
