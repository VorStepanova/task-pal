"""State management for pending reminders.

Converts raw extractor output (due_in_minutes) into absolute due_at
timestamps and rewrites ~/.clippy_pending_reminders.json in resolved form.
Deduplicates by (label, due_at) so repeated extractions don't stack.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

PENDING_PATH = os.path.expanduser("~/.clippy_pending_reminders.json")


def _load_raw() -> list[dict]:
    if not os.path.exists(PENDING_PATH):
        return []
    try:
        with open(PENDING_PATH) as f:
            return json.load(f)
    except Exception:
        return []


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
