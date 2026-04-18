"""Anthropic API client for TaskPal chat.

This is the only file in the project that imports the anthropic SDK.
It maintains conversation history for the lifetime of the process (one
session per subprocess) and prepends a timestamp to every user message
so Claude always knows the current time.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Any

import anthropic

from taskpal.chat.history import save_session, build_handoff_message
from taskpal.config import is_demo


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024
_SYSTEM_PROMPT = (
    "You are TaskPal, a personal accountability companion living in the user's "
    "macOS menu bar. You are warm, direct, and a little opinionated. You help "
    "the user stay on track, think through problems, and remember things. Keep "
    "replies concise — this is a chat window, not an essay. You always know "
    "what time it is because every message includes a timestamp. "
    "You are part of a larger macOS app that handles reminders separately. "
    "When a user asks you to remember something or set a reminder, "
    "acknowledge it warmly and let them know the app has noted it and will "
    "notify them at the right time. You don't fire the notification yourself "
    "— the app does. Do not suggest Siri or other apps."
)

_DEMO_SYSTEM_PROMPT = (
    "You are TaskPal, a personal accountability companion living in the user's "
    "macOS menu bar. You are warm, direct, and a little opinionated. You help "
    "the user stay on track, think through problems, and remember things. Keep "
    "replies concise — this is a chat window, not an essay. You always know "
    "what time it is because every message includes a timestamp. "
    "You are part of a larger macOS app that handles reminders separately. "
    "When a user asks you to remember something or set a reminder, "
    "acknowledge it warmly and let them know the app has noted it and will "
    "notify them at the right time. You don't fire the notification yourself "
    "— the app does. Do not suggest Siri or other apps. "
    "This is a demo session — keep responses natural and friendly. "
    "Do not mention anything overly personal or private. Treat the user "
    "as someone showcasing the app to others."
)


class TaskPalClient:
    """Wraps the Anthropic API and maintains per-session conversation history.

    Each instance represents one chat session. History accumulates with every
    call to send() and can be wiped with clear_history(). Because
    chat_process.py creates exactly one TaskPalClient at module level,
    history naturally resets whenever the window is closed and reopened
    (a fresh subprocess is spawned each time).
    """

    def __init__(self) -> None:
        """Initialise the Anthropic client and an empty message history."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self._history: list[dict[str, Any]] = []
        self._started_at: str = datetime.now().isoformat(timespec="seconds")
        self._api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")

    def send(self, text: str, agenda: list[dict] | None = None) -> str:
        """Send a message to Claude and return the response text.

        Prepends the current timestamp to the user message before sending,
        appends both the user message and the assistant reply to history,
        and returns the assistant's text. Returns a friendly error string
        rather than raising if the API call fails.

        Args:
            text: The raw message the user typed in the chat UI.
            agenda: Optional list of pending reminder dicts to include
                    in the system prompt so Claude is agenda-aware.

        Returns:
            The assistant's reply, or an error string if the call fails.
        """
        if self._client is None:
            return (
                "⚠️ TaskPal can't reach Claude right now. "
                "Check your API key in .env."
            )

        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo("America/New_York"))
        timestamp = now.strftime("%-I:%M %p, %A %-d %b")
        stamped = f"[{timestamp}] {text}"

        self._history.append({"role": "user", "content": stamped})

        base_prompt = _DEMO_SYSTEM_PROMPT if is_demo() else _SYSTEM_PROMPT
        system = base_prompt
        if agenda:
            lines = ["\n\nToday's pending reminders (you are aware of these):"]
            for item in agenda:
                emoji = item.get("emoji", "")
                label = item.get("label", "")
                due = item.get("due_at", "")
                try:
                    from datetime import datetime as dt
                    due_fmt = dt.fromisoformat(due).strftime("%-I:%M %p")
                except Exception:
                    due_fmt = due
                lines.append(f"  - {emoji} {label} at {due_fmt}")
            system = base_prompt + "\n".join(lines)

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=self._history,
            )
            reply = response.content[0].text
        except anthropic.AuthenticationError:
            self._history.pop()
            return (
                "⚠️ TaskPal can't reach Claude right now. "
                "Check your API key in .env."
            )
        except Exception:
            self._history.pop()
            return (
                "⚠️ TaskPal can't reach Claude right now. "
                "Check your API key in .env."
            )

        self._history.append({"role": "assistant", "content": reply})
        return reply

    def clear_history(self) -> None:
        """Reset the conversation history to an empty state."""
        self._history = []

    def inject_assistant(self, text: str) -> None:
        """Add an assistant message to history without an API call.

        Used when the scheduler injects a nudge bubble into the chat UI —
        this ensures Claude's next response has context for what was just said.

        Args:
            text: The message that was injected into the UI as an assistant bubble.
        """
        self._history.append({"role": "assistant", "content": text})

    def new_chat(
        self,
        history_enabled: bool = True,
    ) -> str:
        """Save current session, clear history, and return a handoff message.

        Args:
            history_enabled: Whether to write the session file to disk.

        Returns:
            The handoff message string to inject into the new session.
        """
        handoff = build_handoff_message(self._history, self._api_key)
        save_session(self._history, self._started_at, history_enabled)
        self._history = []
        self._started_at = datetime.now().isoformat(timespec="seconds")
        return handoff
