"""Anthropic API client for Clippy chat.

This is the only file in the project that imports the anthropic SDK.
It maintains conversation history for the lifetime of the process (one
session per subprocess) and prepends a timestamp to every user message
so Claude always knows the current time.
"""

import os
from datetime import datetime
from typing import Any

import anthropic


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024
_SYSTEM_PROMPT = (
    "You are Clippy, a personal accountability companion living in the user's "
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


class ClippyClient:
    """Wraps the Anthropic API and maintains per-session conversation history.

    Each instance represents one chat session. History accumulates with every
    call to send() and can be wiped with clear_history(). Because
    chat_process.py creates exactly one ClippyClient at module level,
    history naturally resets whenever the window is closed and reopened
    (a fresh subprocess is spawned each time).
    """

    def __init__(self) -> None:
        """Initialise the Anthropic client and an empty message history."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self._history: list[dict[str, Any]] = []

    def send(self, text: str) -> str:
        """Send a message to Claude and return the response text.

        Prepends the current timestamp to the user message before sending,
        appends both the user message and the assistant reply to history,
        and returns the assistant's text. Returns a friendly error string
        rather than raising if the API call fails.

        Args:
            text: The raw message the user typed in the chat UI.

        Returns:
            The assistant's reply, or an error string if the call fails.
        """
        if self._client is None:
            return (
                "⚠️ Clippy can't reach Claude right now. "
                "Check your API key in .env."
            )

        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo("America/New_York"))
        timestamp = now.strftime("%-I:%M %p, %A %-d %b")
        stamped = f"[{timestamp}] {text}"

        self._history.append({"role": "user", "content": stamped})

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=self._history,
            )
            reply = response.content[0].text
        except anthropic.AuthenticationError:
            self._history.pop()
            return (
                "⚠️ Clippy can't reach Claude right now. "
                "Check your API key in .env."
            )
        except Exception:
            self._history.pop()
            return (
                "⚠️ Clippy can't reach Claude right now. "
                "Check your API key in .env."
            )

        self._history.append({"role": "assistant", "content": reply})
        return reply

    def clear_history(self) -> None:
        """Reset the conversation history to an empty state."""
        self._history = []
