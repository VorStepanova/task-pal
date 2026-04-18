"""Scheduler — checks pending reminders every 60 seconds and fires due ones.

Runs as a daemon thread started from app.py. Fires a reminder by:
- Sending a macOS notification
- Writing to ~/.taskpal_chat_inject.json for chat_process.py to pick up

Removes fired reminders from the pending file and logs them to
~/.taskpal_completions.json.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

import subprocess

import anthropic

from taskpal.reminders.state import (
    PENDING_PATH,
    log_fired,
    remove_fired,
    resolve_pending,
)
from taskpal.reminders.escalator import escalate

INJECT_QUEUE_PATH = os.path.expanduser("~/.taskpal_inject_queue.json")
_MONITOR_STATE_PATH = os.path.expanduser("~/.taskpal_monitor_state.json")
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_NUDGE_MODEL = "claude-haiku-4-5"
_POLL_INTERVAL = 60  # seconds


def _notify(label: str, message: str) -> None:
    """Send a macOS notification via osascript — safe from any thread."""
    safe_label = label.replace('"', "'")
    safe_message = message.replace('"', "'")
    script = (
        f'display notification "{safe_message}" '
        f'with title "⏰ TaskPal Reminder" '
        f'subtitle "{safe_label}"'
    )
    try:
        subprocess.Popen(["osascript", "-e", script])
    except Exception:
        pass


def _generate_id() -> str:
    return secrets.token_hex(4)


def _enqueue_inject(message: str) -> None:
    """Append a message to the inject queue. Never overwrites existing items."""
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    queue: list[dict] = []
    if os.path.exists(INJECT_QUEUE_PATH):
        try:
            with open(INJECT_QUEUE_PATH) as f:
                queue = json.load(f)
        except Exception:
            queue = []
    # Purge delivered items older than 24 hours
    queue = [
        item for item in queue
        if item.get("delivered_at") is None
        or datetime.fromisoformat(item["delivered_at"]) >= cutoff
    ]
    queue.append({
        "id": _generate_id(),
        "message": message,
        "written_at": now.isoformat(timespec="seconds"),
        "delivered_at": None,
    })
    tmp = INJECT_QUEUE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(queue, f, indent=2)
        os.replace(tmp, INJECT_QUEUE_PATH)
    except Exception:
        pass


def _snooze_reminder(label: str, due_at: str) -> None:
    """Increment snooze_count and set next_fire_at 30 min from now."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        for r in reminders:
            if r.get("label") == label and r.get("due_at") == due_at:
                r["snooze_count"] = r.get("snooze_count", 0) + 1
                r["next_fire_at"] = (
                    datetime.now() + timedelta(minutes=30)
                ).isoformat(timespec="seconds")
                break
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def _defer_next_fire_only(label: str, due_at: str) -> None:
    """Set next_fire_at 30 min from now without changing snooze_count."""
    if not os.path.exists(PENDING_PATH):
        return
    try:
        with open(PENDING_PATH) as f:
            reminders = json.load(f)
        for r in reminders:
            if r.get("label") == label and r.get("due_at") == due_at:
                r["next_fire_at"] = (
                    datetime.now() + timedelta(minutes=30)
                ).isoformat(timespec="seconds")
                break
        with open(PENDING_PATH, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception:
        pass


def _read_idle_secs() -> int:
    """Seconds idle from monitor snapshot; 0 if missing or unreadable."""
    if not os.path.exists(_MONITOR_STATE_PATH):
        return 0
    try:
        with open(_MONITOR_STATE_PATH) as f:
            snap = json.load(f)
        return int(snap.get("idle_secs", 0))
    except Exception:
        return 0


def _generate_nudge(label: str, context: str) -> str:
    """Generate a fresh in-character nudge message using Haiku.

    Falls back to a plain label-based message on any error.
    """
    if not _ANTHROPIC_API_KEY or not context:
        return f"⏰ {label} — time to check in."
    try:
        client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=_NUDGE_MODEL,
            max_tokens=80,
            system=(
                "You are TaskPal, a warm but direct personal accountability "
                "companion. Write ONE short sentence (max 12 words) nudging "
                "the user about their reminder. Use the context provided to "
                "make it personal and specific. Be warm but a little cheeky. "
                "No preamble. No emoji unless it fits naturally."
            ),
            messages=[{
                "role": "user",
                "content": f"Reminder: {label}\nContext: {context}"
            }],
        )
        return f"⏰ {label} — {response.content[0].text.strip()}"
    except Exception:
        return f"⏰ {label} — time to check in."


def _check_and_fire() -> None:
    idle_secs = _read_idle_secs()
    if idle_secs >= 3600:
        return

    escalation_frozen = idle_secs >= 1800

    now = datetime.now()
    pending = resolve_pending()
    for reminder in pending:
        due_at_str = reminder.get("due_at", "")
        label = reminder.get("label", "Reminder")

        # Respect next_fire_at if set (snooze delay)
        next_fire_str = reminder.get("next_fire_at")
        if next_fire_str:
            try:
                if datetime.fromisoformat(next_fire_str) > now:
                    continue
            except ValueError:
                pass

        try:
            due_at = datetime.fromisoformat(due_at_str)
        except ValueError:
            continue

        stale_cutoff = now - timedelta(minutes=60)
        next_fire_dt: datetime | None = None
        if next_fire_str:
            try:
                next_fire_dt = datetime.fromisoformat(next_fire_str)
            except ValueError:
                pass

        if next_fire_dt is not None:
            if next_fire_dt < stale_cutoff:
                remove_fired(label, due_at_str)
                continue
        elif due_at < stale_cutoff:
            remove_fired(label, due_at_str)
            continue

        if due_at <= now:
            if reminder.get("source") == "config":
                context = reminder.get("raw", "")
                nudge = _generate_nudge(label, context)
            else:
                nudge = f"⏰ {label} — How'd it go?"
            snooze_count = reminder.get("snooze_count", 0)
            if snooze_count > 0:
                nudge += f"\n(snoozed {snooze_count}× — getting impatient)"
            _notify(label, nudge)
            _enqueue_inject(nudge)

            if escalation_frozen:
                _defer_next_fire_only(label, due_at_str)
            else:
                acknowledged = escalate(reminder)

                if acknowledged:
                    log_fired(label)
                    remove_fired(label, due_at_str)
                else:
                    _snooze_reminder(label, due_at_str)


def _scheduler_loop() -> None:
    while True:
        time.sleep(_POLL_INTERVAL)
        try:
            _check_and_fire()
        except Exception:
            pass  # never let a transient error kill the scheduler thread


def start() -> None:
    """Start the scheduler daemon thread. Call once from app.py."""
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="taskpal-scheduler")
    t.start()
