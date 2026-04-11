"""Reminder and completion extraction from chat messages.

Makes a separate lightweight Anthropic API call to extract structured data
from user messages. Intentionally isolated — no imports from within clippy/.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic


_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 256

_REMINDER_SYSTEM = (
    "You extract time-sensitive reminders from chat messages. Return ONLY "
    "a JSON object. If no reminders are found, return {\"reminders\": []}. "
    "Shape: {\"reminders\": [{\"label\": string, \"due_in_minutes\": integer, "
    "\"raw\": string}]}. Only extract explicit time references "
    "(\"in 20 minutes\", \"at 3pm\", \"before bed\"). Convert \"at 3pm\" to "
    "minutes from now using the current time in the message timestamp if "
    "present. Do not invent reminders. No markdown fences."
)

_COMPLETION_SYSTEM = (
    "Given a list of task names and a user message, return ONLY a JSON "
    "object listing which tasks the user is confirming they completed. "
    "Shape: {\"completed\": [\"task name\"]}. Only include tasks explicitly "
    "confirmed. No markdown fences."
)

_MEDS_PHRASES = {"took them", "took my meds", "meds done", "took my medication"}


class Extractor:
    """Parses user messages for reminder candidates and auto-complete signals.

    Makes lightweight, isolated Anthropic API calls — completely separate from
    the conversation history in ClippyClient. Returns empty results on any
    error so the chat is never disrupted.
    """

    def __init__(self) -> None:
        """Initialise a lightweight Anthropic client from ANTHROPIC_API_KEY."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

    def extract_reminders(self, user_text: str) -> list[dict]:
        """Parse a user message for time-sensitive commitments.

        Args:
            user_text: The raw message the user typed.

        Returns:
            A list of reminder dicts with keys ``label``, ``due_in_minutes``,
            and ``raw``. Empty list if none found or on any error.
        """
        if self._client is None:
            return []
        try:
            import json
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_REMINDER_SYSTEM,
                messages=[{"role": "user", "content": user_text}],
            )
            data: dict[str, Any] = json.loads(response.content[0].text)
            return data.get("reminders", [])
        except Exception:
            return []

    def extract_completions(self, user_text: str, known_tasks: list[str]) -> list[str]:
        """Check if the user message implies completing any known tasks.

        Always detects hard-coded Meds phrases regardless of AI extraction.

        Args:
            user_text: The raw message the user typed.
            known_tasks: List of task label strings to check against.

        Returns:
            List of task names the user has confirmed completing. Empty list
            on any error.
        """
        completed: list[str] = []

        if user_text.strip().lower() in _MEDS_PHRASES and "Meds" in known_tasks:
            completed.append("Meds")

        if self._client is None:
            return completed

        try:
            import json
            prompt = (
                f"Tasks: {json.dumps(known_tasks)}\n"
                f"Message: {user_text}"
            )
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_COMPLETION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            data: dict[str, Any] = json.loads(response.content[0].text)
            ai_completed: list[str] = data.get("completed", [])
            for task in ai_completed:
                if task not in completed:
                    completed.append(task)
        except Exception:
            pass

        return completed
