"""Skincare reminder scheduler.

Reads skincare_config.json and queues AM/PM reminders with Full/Lazy
buttons into ~/.taskpal_inject_queue.json. Runs on boot and re-queues
at midnight. Also handles button action responses.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from taskpal.config import is_demo

_REMINDERS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "reminders",
)


def _config_path() -> str:
    filename = "demo_skincare_config.json" if is_demo() else "skincare_config.json"
    return os.path.join(_REMINDERS_DIR, filename)
_INJECT_QUEUE_PATH = os.path.expanduser("~/.taskpal_inject_queue.json")

_DAY_MAP = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu",
    4: "fri", 5: "sat", 6: "sun",
}


def _load_config() -> dict:
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _generate_id() -> str:
    return secrets.token_hex(4)


def _load_queue() -> list[dict]:
    if not os.path.exists(_INJECT_QUEUE_PATH):
        return []
    try:
        with open(_INJECT_QUEUE_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_queue(queue: list[dict]) -> None:
    tmp = _INJECT_QUEUE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(queue, f, indent=2)
        os.replace(tmp, _INJECT_QUEUE_PATH)
    except Exception:
        pass


def _already_queued(queue: list[dict], action_prefix: str) -> bool:
    """Check if an undelivered item with this action prefix exists."""
    for item in queue:
        if item.get("delivered_at") is not None:
            continue
        for btn in item.get("buttons", []):
            if btn.get("action", "").startswith(action_prefix):
                return True
    return False


def _enqueue(message: str, buttons: list[dict]) -> None:
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    queue = _load_queue()
    queue = [
        item for item in queue
        if item.get("delivered_at") is None
        or datetime.fromisoformat(item["delivered_at"]) >= cutoff
    ]
    queue.append({
        "id": _generate_id(),
        "message": message,
        "buttons": buttons,
        "written_at": now.isoformat(timespec="seconds"),
        "delivered_at": None,
    })
    _save_queue(queue)


def _queue_am(config: dict) -> None:
    queue = _load_queue()
    if _already_queued(queue, "skincare_am"):
        return
    _enqueue(
        "Ready for your morning skincare routine? 🌅",
        [
            {"label": "Full", "action": "skincare_am_full"},
            {"label": "Lazy", "action": "skincare_am_lazy"},
        ],
    )


def _queue_pm(config: dict) -> None:
    today = _DAY_MAP[datetime.now().weekday()]
    pm_routines = config.get("pm_routines", {})
    routine = pm_routines.get(today, {})
    routine_type = routine.get("type", "rest").capitalize()
    extras_allowed = routine.get("extras_allowed", False)
    extras_note = routine.get("extras_note", "")

    queue = _load_queue()
    if _already_queued(queue, "skincare_pm"):
        return

    msg = f"Tonight is your {routine_type} night. 🌙 Ready for your routine?"
    if extras_allowed:
        msg += f"\n({extras_note})"

    buttons = [
        {"label": "Full", "action": f"skincare_pm_full_{today}"},
        {"label": "Lazy", "action": f"skincare_pm_lazy_{today}"},
    ]
    if extras_allowed:
        buttons.append({"label": "Full + Extras", "action": f"skincare_pm_extras_{today}"})

    _enqueue(msg, buttons)


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _loop(config: dict) -> None:
    am_h, am_m = map(int, config.get("remind_at", {}).get("am", "07:30").split(":"))
    pm_h, pm_m = map(int, config.get("remind_at", {}).get("pm", "21:00").split(":"))
    while True:
        secs_am = _seconds_until(am_h, am_m)
        secs_pm = _seconds_until(pm_h, pm_m)
        time.sleep(min(secs_am, secs_pm))
        now_h = datetime.now().hour
        config = _load_config()
        try:
            if now_h < 12:
                _queue_am(config)
            else:
                _queue_pm(config)
        except Exception:
            pass
        time.sleep(60)  # prevent double-firing


def get_action_response(action: str) -> str:
    """Return the routine steps string for a given button action.

    Called by chat_process.py's handle_action bridge method.
    Returns a formatted string to inject as an assistant bubble.
    """
    config = _load_config()
    today = _DAY_MAP[datetime.now().weekday()]

    if action == "skincare_am_full":
        steps = config.get("am_routine", {}).get("full", [])
        lines = ["🌅 Full AM Routine:"]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)

    if action == "skincare_am_lazy":
        steps = config.get("am_routine", {}).get("lazy", [])
        lines = ["🌅 Lazy AM (no judgment):"]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)

    if action.startswith("skincare_pm_"):
        parts = action.split("_")
        mode = parts[2]  # full, lazy, or extras
        day = parts[3] if len(parts) > 3 else today
        routine = config.get("pm_routines", {}).get(day, {})
        routine_type = routine.get("type", "rest").capitalize()

        if mode == "full":
            steps = routine.get("full", [])
            lines = [f"🌙 {routine_type} Night — Full Routine:"]
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            return "\n".join(lines)

        if mode == "lazy":
            steps = routine.get("lazy", [])
            lines = [f"🌙 {routine_type} Night — Lazy PM (no guilt):"]
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            return "\n".join(lines)

        if mode == "extras":
            steps = routine.get("full", [])
            extras = config.get("extras", {})
            lines = [f"🌙 {routine_type} Night — Full + Extras:"]
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")
            lines.append("✨ Bonus extras (after Skinfix):")
            for extra in extras.values():
                if day in extra.get("allowed_days", []):
                    lines.append(f"  • {extra['name']}")
            return "\n".join(lines)

    return "I couldn't find that routine. Check your skincare_config.json."


def start() -> None:
    """Start the skincare scheduler daemon thread."""
    config = _load_config()
    if not config:
        return
    t = threading.Thread(
        target=_loop,
        args=(config,),
        daemon=True,
        name="taskpal-skincare",
    )
    t.start()
