"""Standalone subprocess that owns the pywebview chat window.

This script is spawned by ChatWindow.open() as a separate process so that
pywebview can take the main thread freely — rumps already owns the main
thread in the parent process and macOS does not allow two AppKit event
loops to share a thread.

Do NOT import this module from app.py or any other taskpal module. It is
an entry point only; subprocess.Popen is the only caller.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

# Resolve the project root (three levels up: chat_process.py → chat/ → taskpal/ → project root)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))

# Load .env before any other taskpal imports so API keys are available.
# override=True so .env wins over inherited shell exports — keeps demo flag
# consistent with the parent process.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)

import webview  # noqa: E402
from taskpal.chat.client import TaskPalClient  # noqa: E402
from taskpal.chat.extractor import Extractor  # noqa: E402
from taskpal.reminders import streak  # noqa: E402

_client = TaskPalClient()
_extractor = Extractor()
_window_ref = None  # set after webview.create_window(); used by check-in thread
_INJECT_QUEUE_PATH = os.path.expanduser("~/.taskpal_inject_queue.json")
_FACE_STATE_PATH = os.path.expanduser("~/.taskpal_face_state.json")

_INDEX_HTML = os.path.join(_HERE, "ui", "index.html")


_AGENDA_KEYWORDS = [
    "agenda", "adgenda", "schedule", "what's on", "whats on", "what is on",
    "what do i have", "what's left", "whats left", "what is left",
    "to do", "todo", "my day", "my plate",
    "what's up", "whats up", "what is up",
    "reminders", "what should i", "what am i doing",
    "what's happening", "whats happening", "what is happening",
    "plan for today", "today's plan", "todays plan",
    "what's today", "whats today",
]


def _is_agenda_query(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _AGENDA_KEYWORDS)


def _load_agenda_items() -> list[dict]:
    """Load pending reminders deduped by label (earliest due_at wins)."""
    from taskpal.reminders.state import load_pending
    seen: dict[str, dict] = {}
    for r in load_pending():
        label = r.get("label", "")
        due = r.get("due_at", "")
        if not label or not due:
            continue
        if label not in seen or due < seen[label].get("due_at", ""):
            seen[label] = r
    items = list(seen.values())
    items.sort(key=lambda x: x.get("due_at", ""))
    return items


def _get_response(text: str) -> str:
    from taskpal.config import is_activity_sharing_enabled
    agenda_items = _load_agenda_items()
    show_buttons = _is_agenda_query(text)
    monitor_snap = _read_monitor_snapshot() if is_activity_sharing_enabled() else None

    response = _client.send(
        text,
        agenda=agenda_items if agenda_items else None,
        monitor=monitor_snap if monitor_snap else None,
    )

    reminders = _extractor.extract_reminders(text)
    if reminders:
        _save_pending_reminders(reminders)

    known_tasks = ["Meds", "Write the story", "Work on Story Crypt",
                   "Work on Klink", "Curate Local", "Clean your room",
                   "Do your actual job"]
    completions = _extractor.extract_completions(text, known_tasks)
    if completions:
        _save_completions(completions)

    if show_buttons and agenda_items:
        payload = {
            "message": response,
            "agenda": [
                {"label": it.get("label", ""), "emoji": it.get("emoji", "")}
                for it in agenda_items
            ],
        }
        return json.dumps(payload)

    return response


def _save_pending_reminders(reminders: list) -> None:
    """Write extracted reminders to ~/.taskpal_pending_reminders.json."""
    import json
    path = os.path.expanduser("~/.taskpal_pending_reminders.json")
    existing = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.extend(reminders)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)


def _save_completions(completions: list) -> None:
    """Write completed task names to ~/.taskpal_completions.json."""
    import json
    path = os.path.expanduser("~/.taskpal_completions.json")
    existing = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass
    from datetime import datetime
    timestamped = [
        {"task": task, "completed_at": datetime.now().isoformat()}
        for task in completions
    ]
    existing.extend(timestamped)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)


_IDLE_THRESHOLD_SECS = 1800            # 30 minutes
_APP_DWELL_THRESHOLD_SECS = 7200       # 2 hours
_AGENDA_IMMINENT_SECS = 1800           # agenda item due within 30 min
_POLL_INTERVAL_SECS = 900              # 15 minutes
_COOLDOWN_SECS = 3600                  # 1 hour between silent pokes
_POLL_MODEL = "claude-haiku-4-5"
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

_last_fired: dict[str, datetime] = {}


def _read_monitor_snapshot() -> dict | None:
    path = os.path.expanduser("~/.taskpal_monitor_state.json")
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _cooldown_ok(key: str) -> bool:
    last = _last_fired.get(key)
    return last is None or datetime.now() - last > timedelta(seconds=_COOLDOWN_SECS)


def _fire(message: str, key: str) -> None:
    global _window_ref
    _last_fired[key] = datetime.now()
    _client.inject_assistant(message)
    if _window_ref is not None:
        safe = message.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        _window_ref.evaluate_js(f"injectAssistantMessage('{safe}')")


def _imminent_agenda(now: datetime) -> list[str]:
    """Labels with due_at within the next _AGENDA_IMMINENT_SECS seconds."""
    out: list[str] = []
    for it in _load_agenda_items():
        due_str = it.get("due_at", "")
        try:
            due = datetime.fromisoformat(due_str)
        except (ValueError, TypeError):
            continue
        delta = (due - now).total_seconds()
        if 0 <= delta <= _AGENDA_IMMINENT_SECS:
            out.append(f"{it.get('label', '')} in {int(delta // 60)} min")
    return out


def _consult_haiku(snap: dict | None, imminent: list[str]) -> str | None:
    """Ask Haiku if it wants to poke the user. Returns message or None for silence."""
    if not _ANTHROPIC_API_KEY:
        return None
    import anthropic
    now = datetime.now()
    agenda_str = "; ".join(imminent) if imminent else "nothing imminent"

    lines = [f"Current time: {now.strftime('%-I:%M %p, %A')}"]
    if snap:
        active_app = (snap.get("active_app") or "").strip() or "unknown"
        try:
            idle_min = int(snap.get("idle_secs") or 0) // 60
        except (TypeError, ValueError):
            idle_min = 0
        try:
            dwell_min = int(snap.get("app_duration_secs") or 0) // 60
        except (TypeError, ValueError):
            dwell_min = 0
        lines.append(f"Active app: {active_app}")
        lines.append(f"Time in that app: {dwell_min} min")
        lines.append(f"User idle for: {idle_min} min")
    lines.append(f"Imminent agenda (next 30 min): {agenda_str}")

    user_content = (
        "\n".join(lines)
        + "\n\nYou are being polled silently in the background. Is there "
        "something genuinely useful or warm to say given this state? If yes, "
        "write ONE sentence (max 14 words). If nothing meaningful to add, "
        "reply with a single dash: -"
    )
    try:
        client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=_POLL_MODEL,
            max_tokens=80,
            system=(
                "You are TaskPal, a warm but direct personal accountability "
                "companion. You run in the user's menu bar. A silent background "
                "check is asking you: anything to say right now? Be personal "
                "and specific; silence is fine — prefer a dash over generic "
                "filler. No preamble. No emoji unless it fits naturally."
            ),
            messages=[{"role": "user", "content": user_content}],
        )
        text = response.content[0].text.strip()
    except Exception:
        return None
    if not text or text == "-":
        return None
    return text


def _checkin_loop() -> None:
    from taskpal.config import is_activity_sharing_enabled
    while True:
        time.sleep(_POLL_INTERVAL_SECS)
        now = datetime.now()
        if 0 <= now.hour < 7:
            continue
        if not _cooldown_ok("silent_poll"):
            continue
        share_activity = is_activity_sharing_enabled()
        snap = _read_monitor_snapshot() if share_activity else None
        imminent = _imminent_agenda(now)

        if share_activity and snap:
            idle = snap.get("idle_secs", 0) or 0
            duration = snap.get("app_duration_secs", 0) or 0
            gated = (
                idle >= _IDLE_THRESHOLD_SECS
                or duration >= _APP_DWELL_THRESHOLD_SECS
                or bool(imminent)
            )
        else:
            # Privacy mode: only agenda imminence can trigger the poll.
            gated = bool(imminent)
        if not gated:
            continue

        message = _consult_haiku(snap, imminent)
        if message:
            _fire(message, "silent_poll")
        else:
            _last_fired["silent_poll"] = now


def _save_queue(queue: list[dict]) -> None:
    """Write the queue back to disk atomically."""
    tmp = _INJECT_QUEUE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(queue, f, indent=2)
        os.replace(tmp, _INJECT_QUEUE_PATH)
    except Exception:
        pass


def _deliver_pending(queue: list[dict]) -> list[dict]:
    """Attempt delivery of all undelivered queue items.

    Only delivers if _window_ref is set. Stamps delivered_at on success.
    Leaves undelivered items untouched for retry on next tick.
    """
    if _window_ref is None:
        return queue
    now = datetime.now().isoformat(timespec="seconds")
    for item in queue:
        if item.get("delivered_at") is not None:
            continue
        message = item.get("message", "")
        if not message:
            item["delivered_at"] = now
            continue
        try:
            _client.inject_assistant(message)
            buttons = item.get("buttons", [])
            if buttons:
                payload = json.dumps({"message": message, "buttons": buttons})
            else:
                payload = message
            safe = payload.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            _window_ref.evaluate_js(f"injectAssistantMessage('{safe}')")
            item["delivered_at"] = now
        except Exception:
            pass  # leave undelivered, retry next tick
    return queue


def _inject_loop() -> None:
    while True:
        time.sleep(10)
        if not os.path.exists(_INJECT_QUEUE_PATH):
            continue
        try:
            with open(_INJECT_QUEUE_PATH) as f:
                queue = json.load(f)
            queue = _deliver_pending(queue)
            _save_queue(queue)
        except Exception:
            pass


def _face_loop() -> None:
    _last_face: str = ""
    while True:
        time.sleep(5)
        if not os.path.exists(_FACE_STATE_PATH):
            continue
        try:
            with open(_FACE_STATE_PATH) as f:
                data = json.load(f)
            emoji = data.get("face", "😊")
            if emoji != _last_face and _window_ref is not None:
                _window_ref.evaluate_js(f"updateHeaderFace('{emoji}')")
                _last_face = emoji
        except Exception:
            pass


class TaskPalBridge:
    """Exposes Python methods to the JS running in the webview.

    Each public method becomes callable from JavaScript as
    ``window.pywebview.api.<method_name>(...)``.
    """

    def send_message(self, text: str) -> str:
        """Receive a message from the UI and return a response.

        Args:
            text: The raw string the user typed in the chat input.

        Returns:
            A reply string. Delegates to _get_response() so Phase 4 can
            swap in the real Claude call without touching this method.
        """
        return _get_response(text)

    def new_chat(self) -> None:
        """Save current session, reset history, inject handoff into new chat."""
        from taskpal.config import Config
        config = Config()
        history_enabled = config.get("history_enabled", True)

        handoff = _client.new_chat(history_enabled=history_enabled)

        def _inject():
            import time
            time.sleep(0.3)  # brief pause so transcript clears first
            if _window_ref is not None:
                safe = handoff.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
                _window_ref.evaluate_js(f"injectAssistantMessage('{safe}')")

        threading.Thread(target=_inject, daemon=True).start()

    def acknowledge_reminder(self, label: str) -> None:
        """Remove a reminder by label and log it as completed.

        Called when the user clicks the ✓ Done button on an injected
        reminder bubble.

        Args:
            label: The reminder label extracted from the bubble text.
        """
        import json
        from datetime import datetime

        pending_path = os.path.expanduser("~/.taskpal_pending_reminders.json")
        completions_path = os.path.expanduser("~/.taskpal_completions.json")

        # Remove all pending reminders matching this label
        try:
            if os.path.exists(pending_path):
                with open(pending_path) as f:
                    reminders = json.load(f)
                reminders = [r for r in reminders if r.get("label") != label]
                with open(pending_path, "w") as f:
                    json.dump(reminders, f, indent=2)
        except Exception:
            pass

        # Log as completed
        try:
            existing = []
            if os.path.exists(completions_path):
                with open(completions_path) as f:
                    existing = json.load(f)
            existing.append({
                "task": label,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "source": "ack_button",
            })
            with open(completions_path, "w") as f:
                json.dump(existing, f, indent=2)
        except Exception:
            pass

    def dismiss_reminder(self, label: str) -> None:
        """Dismiss a reminder for today — stops all further nudges."""
        from taskpal.config import is_demo
        if is_demo():
            return
        from taskpal.reminders.state import mark_dismissed
        mark_dismissed(label)

    def snooze_reminder(self, label: str, hours: int) -> None:
        """Snooze a reminder for N hours."""
        from taskpal.config import is_demo
        if is_demo():
            return
        from taskpal.reminders.state import snooze_for_hours
        snooze_for_hours(label, hours)

    def handle_action(self, action: str) -> None:
        """Handle a button action from an injected bubble."""
        from taskpal.reminders.skincare_scheduler import get_action_response
        from taskpal.reminders.scheduler import _enqueue_inject
        response = get_action_response(action)
        if response:
            _enqueue_inject(response)


def main() -> None:
    bridge = TaskPalBridge()
    window = webview.create_window(
        title="TaskPal",
        url=f"file://{_INDEX_HTML}",
        js_api=bridge,
        width=380,
        height=600,
        on_top=False,
        easy_drag=False,
        text_select=True,
        frameless=False,
    )
    global _window_ref
    _window_ref = window
    _checkin_thread = threading.Thread(target=_checkin_loop, daemon=True, name="taskpal-checkin")
    _checkin_thread.start()
    _inject_thread = threading.Thread(target=_inject_loop, daemon=True, name="taskpal-inject")
    _inject_thread.start()
    _face_thread = threading.Thread(target=_face_loop, daemon=True, name="taskpal-face")
    _face_thread.start()
    streak.start()
    webview.start()


if __name__ == "__main__":
    main()
