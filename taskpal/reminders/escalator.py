"""Escalation logic for ignored reminders.

Called by scheduler.py after every reminder fire. Returns True if the user
acknowledged (scheduler should remove the reminder), False if not
(scheduler should snooze: increment snooze_count, set next_fire_at).

Escalation ladder (by snooze_count):
  0 — no-op, return False (first fire, notification was enough)
  1 — sound once, return False
  2 — sound once + modal, return modal result
  3+ — sound 3x rapid + modal + say, return modal result
"""

from __future__ import annotations

import subprocess
import time


def _play_sound(times: int = 1) -> None:
    sound = "/System/Library/Sounds/Sosumi.aiff"
    for i in range(times):
        if i > 0:
            time.sleep(0.05)
        try:
            subprocess.Popen(["afplay", sound])
        except Exception:
            pass


def _show_modal(label: str) -> bool:
    script = "\n".join([
        'try',
        '    display dialog '
        f'"\\n⏰  {label}\\n\\nThis reminder has been waiting for you." '
        'with title "TaskPal — Action Required" '
        'buttons {"Got it"} '
        'default button "Got it" '
        'with icon stop',
        '    return "ok"',
        'on error',
        '    return "error"',
        'end try',
    ])
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            check=False, capture_output=True, text=True, timeout=300
        )
        return "ok" in proc.stdout
    except Exception:
        return False


def _speak() -> None:
    try:
        subprocess.Popen(["say", "-v", "Samantha", "-r", "150", "Hey, check in with me."])
    except Exception:
        pass


def escalate(reminder: dict) -> bool:
    """Run the escalation action for a snoozed reminder.

    Args:
        reminder: A resolved reminder dict with at least 'label' and
                  'snooze_count' keys.

    Returns:
        True if the user acknowledged (remove from pending).
        False if not acknowledged (snooze: increment count, set next_fire_at).
    """
    count = reminder.get("snooze_count", 0)
    label = reminder.get("label", "Reminder")

    if count == 0:
        return False

    if count == 1:
        _play_sound(times=1)
        return False

    if count == 2:
        _play_sound(times=1)
        return _show_modal(label)

    # count >= 3
    _play_sound(times=3)
    acknowledged = _show_modal(label)
    _speak()
    return acknowledged
