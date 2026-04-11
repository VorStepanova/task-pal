"""Standalone subprocess that owns the pywebview chat window.

This script is spawned by ChatWindow.open() as a separate process so that
pywebview can take the main thread freely — rumps already owns the main
thread in the parent process and macOS does not allow two AppKit event
loops to share a thread.

Do NOT import this module from app.py or any other clippy module. It is
an entry point only; subprocess.Popen is the only caller.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

# Resolve the project root (three levels up: chat_process.py → chat/ → clippy/ → project root)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))

# Load .env before any other clippy imports so API keys are available
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

import webview  # noqa: E402
from clippy.chat.client import ClippyClient  # noqa: E402
from clippy.chat.extractor import Extractor  # noqa: E402

_client = ClippyClient()
_extractor = Extractor()
_window_ref = None  # set after webview.create_window(); used by check-in thread
_INJECT_PATH = os.path.expanduser("~/.clippy_chat_inject.json")

_INDEX_HTML = os.path.join(_HERE, "ui", "index.html")


def _get_response(text: str) -> str:
    response = _client.send(text)

    reminders = _extractor.extract_reminders(text)
    if reminders:
        _save_pending_reminders(reminders)

    known_tasks = ["Meds", "Write the story", "Work on Story Crypt",
                   "Work on Klink", "Curate Local", "Clean your room",
                   "Do your actual job"]
    completions = _extractor.extract_completions(text, known_tasks)
    if completions:
        _save_completions(completions)

    return response


def _save_pending_reminders(reminders: list) -> None:
    """Write extracted reminders to ~/.clippy_pending_reminders.json."""
    import json
    path = os.path.expanduser("~/.clippy_pending_reminders.json")
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
    """Write completed task names to ~/.clippy_completions.json."""
    import json
    path = os.path.expanduser("~/.clippy_completions.json")
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


_IDLE_THRESHOLD_SECS = 1800       # 30 minutes
_APP_DWELL_THRESHOLD_SECS = 7200  # 2 hours
_POLL_INTERVAL_SECS = 900         # 15 minutes
_COOLDOWN_SECS = 3600             # 1 hour per trigger

_last_fired: dict[str, datetime] = {}


def _read_monitor_snapshot() -> dict | None:
    path = os.path.expanduser("~/.clippy_monitor_state.json")
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
    if _window_ref is not None:
        safe = message.replace("\\", "\\\\").replace("'", "\\'")
        _window_ref.evaluate_js(f"injectAssistantMessage('{safe}')")


def _checkin_loop() -> None:
    while True:
        time.sleep(_POLL_INTERVAL_SECS)
        snap = _read_monitor_snapshot()
        if not snap:
            continue

        idle = snap.get("idle_secs", 0)
        duration = snap.get("app_duration_secs", 0)
        app = snap.get("active_app", "that app")

        if idle >= _IDLE_THRESHOLD_SECS and _cooldown_ok("idle"):
            _fire("Hey, you've gone quiet — everything okay? 👀", "idle")
        elif duration >= _APP_DWELL_THRESHOLD_SECS and _cooldown_ok("dwell"):
            _fire(f"You've been in {app} for over 2 hours. Still on track? 🤔", "dwell")


def _inject_loop() -> None:
    while True:
        time.sleep(10)
        if not os.path.exists(_INJECT_PATH):
            continue
        try:
            with open(_INJECT_PATH) as f:
                data = json.load(f)
            message = data.get("message", "")
            if message and _window_ref is not None:
                os.remove(_INJECT_PATH)
                safe = message.replace("\\", "\\\\").replace("'", "\\'")
                _window_ref.evaluate_js(f"injectAssistantMessage('{safe}')")
        except Exception:
            pass


class ClippyBridge:
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


def main() -> None:
    bridge = ClippyBridge()
    window = webview.create_window(
        title="Clippy",
        url=f"file://{_INDEX_HTML}",
        js_api=bridge,
        width=380,
        height=600,
        on_top=True,
        frameless=False,
    )
    global _window_ref
    _window_ref = window
    _checkin_thread = threading.Thread(target=_checkin_loop, daemon=True, name="clippy-checkin")
    _checkin_thread.start()
    _inject_thread = threading.Thread(target=_inject_loop, daemon=True, name="clippy-inject")
    _inject_thread.start()
    webview.start()


if __name__ == "__main__":
    main()
