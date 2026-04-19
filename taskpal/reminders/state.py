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
LAST_MODE_PATH = os.path.expanduser("~/.taskpal_last_mode.json")


def clear_all_pending() -> None:
    """Wipe pending reminders and today's dismissed flags.

    Completions history is preserved so streaks aren't affected.
    """
    for path in (PENDING_PATH, DISMISSED_PATH):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def sync_mode_marker(current_demo: bool) -> bool:
    """Compare the stored mode marker to current_demo and clear on mismatch.

    Returns True if state was cleared due to a mode change. Writes the current
    mode back to the marker so the next call matches. If no marker exists
    (first run), the current mode is recorded and no state is cleared.
    """
    last: dict | None = None
    if os.path.exists(LAST_MODE_PATH):
        try:
            with open(LAST_MODE_PATH) as f:
                last = json.load(f)
        except Exception:
            last = None

    cleared = False
    if isinstance(last, dict) and "demo" in last and bool(last["demo"]) != current_demo:
        clear_all_pending()
        cleared = True

    try:
        with open(LAST_MODE_PATH, "w") as f:
            json.dump({"demo": current_demo}, f)
    except Exception:
        pass
    return cleared


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


def _write_dismissed_today(label: str) -> None:
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


def _clear_dismissed_for_label(label: str) -> None:
    if not os.path.exists(DISMISSED_PATH):
        return
    try:
        with open(DISMISSED_PATH) as f:
            dismissed = json.load(f)
        if label not in dismissed:
            return
        del dismissed[label]
        with open(DISMISSED_PATH, "w") as f:
            json.dump(dismissed, f, indent=2)
    except Exception:
        pass


def dismiss_today(label: str) -> None:
    """Legacy: dismiss + remove from pending. Retained for any stale callers."""
    _write_dismissed_today(label)
    remove_all_for_label(label)


def mark_done(label: str) -> None:
    """Flag all rows for label as done; log one completion per transition."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        already_done = any(
            r.get("label") == label and r.get("status") == "done"
            for r in reminders
        )
        for r in reminders:
            if r.get("label") == label:
                r["status"] = "done"
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
        if not already_done:
            log_fired(label)
    except Exception:
        pass


def mark_dismissed(label: str) -> None:
    """Flag all rows for label as dismissed for today; rows stay in the menu."""
    _write_dismissed_today(label)
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        for r in reminders:
            if r.get("label") == label:
                r["status"] = "dismissed"
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def mark_pending(label: str) -> None:
    """Revert done/dismissed rows for label back to pending; clear any snooze."""
    _clear_dismissed_for_label(label)
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        for r in reminders:
            if r.get("label") == label:
                r["status"] = "pending"
                r.pop("next_fire_at", None)
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


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
    """Snooze all pending reminders for a label by N hours.

    Also reverts status to pending and clears any dismissed-today flag, so
    snoozing acts as "un-done / un-dismissed, fire again in N hours".
    """
    _clear_dismissed_for_label(label)
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        target = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds")
        for r in reminders:
            if r.get("label") == label:
                r["status"] = "pending"
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
