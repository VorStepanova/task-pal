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
    mark_done,
    resolve_pending,
)
from taskpal.reminders.escalator import escalate

INJECT_QUEUE_PATH = os.path.expanduser("~/.taskpal_inject_queue.json")
_MONITOR_STATE_PATH = os.path.expanduser("~/.taskpal_monitor_state.json")
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_NUDGE_MODEL = "claude-haiku-4-5"
_POLL_INTERVAL = 60  # seconds

# Notification sound for scheduler fires. Kept distinct from cursor_nanny's
# palette (Tink / Ping / Sosumi) so the two tools are audibly separable.
# Swap to any of: Basso, Blow, Bottle, Frog, Funk, Glass, Hero, Morse,
# Pop, Purr, Submarine — all live in /System/Library/Sounds/.
_NOTIFY_SOUND = "Hero"


def _notify(label: str, message: str) -> None:
    """Send a macOS notification via osascript — safe from any thread."""
    safe_label = label.replace('"', "'")
    safe_message = message.replace('"', "'")
    script = (
        f'display notification "{safe_message}" '
        f'with title "⏰ TaskPal Reminder" '
        f'subtitle "{safe_label}" '
        f'sound name "{_NOTIFY_SOUND}"'
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


def _read_monitor_snapshot() -> dict:
    """Full monitor snapshot; empty dict if missing or unreadable."""
    if not os.path.exists(_MONITOR_STATE_PATH):
        return {}
    try:
        with open(_MONITOR_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _read_idle_secs() -> int:
    """Seconds idle from monitor snapshot; 0 if missing or unreadable."""
    snap = _read_monitor_snapshot()
    try:
        return int(snap.get("idle_secs", 0))
    except (TypeError, ValueError):
        return 0


def _remaining_agenda(now: datetime, current_label: str) -> list[str]:
    """Other pending reminders still upcoming today, for prompt context."""
    out: list[str] = []
    try:
        with open(PENDING_PATH) as f:
            rows = json.load(f)
    except Exception:
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("label") == current_label:
            continue
        if r.get("status") in ("done", "dismissed"):
            continue
        due_str = r.get("due_at", "")
        try:
            due = datetime.fromisoformat(due_str)
        except (ValueError, TypeError):
            continue
        if due.date() != now.date() or due < now:
            continue
        out.append(f"{r.get('label', '')} at {due.strftime('%-I:%M %p')}")
    return out


def _generate_nudge(label: str, context: str) -> str:
    """Ask Haiku if it wants to add commentary to this reminder fire.

    Supplies current time, the user's active-app/idle snapshot, and today's
    remaining agenda so Claude's addition can be contextual. If Claude
    returns an empty string (nothing worth saying), we fall back to a plain
    label-only nudge.
    """
    plain = f"⏰ {label} — time to check in."
    if not _ANTHROPIC_API_KEY:
        return plain
    from taskpal.config import is_activity_sharing_enabled
    share_activity = is_activity_sharing_enabled()
    now = datetime.now()
    agenda = _remaining_agenda(now, label)
    agenda_str = "; ".join(agenda) if agenda else "nothing else today"

    lines = [
        f"Reminder about to fire: {label}",
        f"Static context for this reminder: {context or '(none)'}",
        f"Current time: {now.strftime('%-I:%M %p, %A')}",
    ]
    if share_activity:
        snap = _read_monitor_snapshot()
        active_app = snap.get("active_app") or "unknown"
        try:
            idle_min = int(snap.get("idle_secs", 0)) // 60
        except (TypeError, ValueError):
            idle_min = 0
        lines.append(f"Active app: {active_app}")
        lines.append(f"User idle for: {idle_min} min")
    lines.append(f"Remaining agenda today: {agenda_str}")

    user_content = (
        "\n".join(lines)
        + "\n\nIf you have something genuinely useful or warm to add, write "
        "ONE sentence (max 14 words). If you have nothing meaningful to add, "
        "reply with a single dash: -"
    )

    try:
        client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=_NUDGE_MODEL,
            max_tokens=80,
            system=(
                "You are TaskPal, a warm but direct personal accountability "
                "companion. A scheduled reminder is about to fire. You're "
                "being asked: anything to add? Use the context to decide. "
                "Be personal, specific, and a little cheeky when you speak. "
                "Silence is fine — prefer a dash over generic filler. "
                "No preamble. No emoji unless it fits naturally."
            ),
            messages=[{"role": "user", "content": user_content}],
        )
        reply = response.content[0].text.strip()
    except Exception:
        return plain

    if not reply or reply == "-":
        return plain
    return f"⏰ {label} — {reply}"


def _check_and_fire() -> None:
    # Idle only freezes *escalation* (modals + voice) — a notification still
    # fires and the inject queue still gets the message, so when the user
    # returns nothing has been silently lost.
    escalation_frozen = _read_idle_secs() >= 1800

    now = datetime.now()
    pending = resolve_pending()
    for reminder in pending:
        # Done/dismissed rows stay in the menu for UX, but must not fire.
        if reminder.get("status") in ("done", "dismissed"):
            continue

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
                    mark_done(label)
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
