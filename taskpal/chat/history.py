"""Session history — writes chat sessions to disk and generates handoffs.

Each session is saved as a JSON file in ~/.taskpal_history/ when the user
starts a new chat. History is only written when history_enabled is True
in config. The handoff summary is always generated regardless of whether
history is saved.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import anthropic

HISTORY_DIR = os.path.expanduser("~/.taskpal_history")
COMPLETIONS_PATH = os.path.expanduser("~/.taskpal_completions.json")
PENDING_PATH = os.path.expanduser("~/.taskpal_pending_reminders.json")

_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 512

_HANDOFF_SYSTEM = (
    "Write a 2-3 sentence summary of this chat session for handoff. "
    "Output ONLY the summary sentences — no preamble, no explanation, "
    "no meta-commentary about your role. Just the sentences. "
    "Focus on: what the user was working on, decisions made, anything "
    "unresolved. Do not mention reminders or wins/losses."
)


def _load_completions_last_12h() -> list[dict]:
    """Return completions from the last 12 hours."""
    cutoff = datetime.now() - timedelta(hours=12)
    if not os.path.exists(COMPLETIONS_PATH):
        return []
    try:
        with open(COMPLETIONS_PATH) as f:
            all_completions = json.load(f)
        return [
            c for c in all_completions
            if datetime.fromisoformat(c.get("completed_at", "1970-01-01")) >= cutoff
        ]
    except Exception:
        return []


def _load_pending() -> list[dict]:
    """Return all pending reminders."""
    if not os.path.exists(PENDING_PATH):
        return []
    try:
        with open(PENDING_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _categorize(completions: list[dict], pending: list[dict]) -> dict:
    """Sort completions and pending into wins, pending losses, and losses."""
    wins = [c["task"] for c in completions]
    pending_losses = [
        r["label"] for r in pending
        if r.get("snooze_count", 0) < 3
    ]
    losses = [
        r["label"] for r in pending
        if r.get("snooze_count", 0) >= 3
    ]
    return {"wins": wins, "pending_losses": pending_losses, "losses": losses}


def _format_scorecard(categories: dict) -> str:
    """Format wins/losses as a readable string for the handoff message."""
    lines = []
    for task in categories["wins"]:
        lines.append(f"✅ {task}")
    for task in categories["pending_losses"]:
        lines.append(f"⚠️ {task} — you're about to lose this one!")
    for task in categories["losses"]:
        lines.append(f"❌ {task} — this one got away from you")
    return "\n".join(lines) if lines else "Nothing logged in the last 12 hours."


def _format_pending_reminders(pending: list[dict]) -> str:
    """Format pending reminders for the handoff message."""
    if not pending:
        return "No active reminders."
    lines = []
    for r in pending:
        label = r.get("label", "Reminder")
        raw_time = r.get("next_fire_at") or r.get("due_at")
        if raw_time:
            try:
                dt = datetime.fromisoformat(raw_time)
                time_str = dt.strftime("%-I:%M %p")
            except ValueError:
                time_str = raw_time
        else:
            time_str = "?"
        snooze = r.get("snooze_count", 0)
        snooze_str = f" (snoozed {snooze}x)" if snooze else ""
        lines.append(f"⏰ {label} — next up {time_str}{snooze_str}")
    return "\n".join(lines)


def _generate_conversation_summary(
    messages: list[dict], api_key: str | None
) -> str:
    """Call Haiku to summarize the conversation in 2-3 sentences."""
    if not api_key or not messages:
        return "Fresh start — no previous conversation."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        transcript = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages[-20:]
        )
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_HANDOFF_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        return response.content[0].text.strip()
    except Exception:
        return "Fresh start — no previous conversation."


def save_session(
    messages: list[dict],
    started_at: str,
    history_enabled: bool,
) -> None:
    """Write the session to disk if history is enabled."""
    if not history_enabled or not messages:
        return
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        safe_name = started_at.replace(":", "-")
        path = os.path.join(HISTORY_DIR, f"{safe_name}.json")
        with open(path, "w") as f:
            json.dump({
                "started_at": started_at,
                "ended_at": datetime.now().isoformat(timespec="seconds"),
                "messages": messages,
            }, f, indent=2)
    except Exception:
        pass


def build_handoff_message(
    messages: list[dict],
    api_key: str | None,
) -> str:
    """Generate the full handoff message for injection into the new session.

    Args:
        messages: The conversation history from the previous session.
        api_key: Anthropic API key for Haiku summarization.

    Returns:
        A formatted string ready to inject as the opening assistant bubble.
    """
    completions = _load_completions_last_12h()
    pending = _load_pending()
    categories = _categorize(completions, pending)
    scorecard = _format_scorecard(categories)
    reminders = _format_pending_reminders(pending)
    summary = _generate_conversation_summary(messages, api_key)

    return (
        f"👋 New chat! Here's where things stand:\n\n"
        f"**Last session:**\n{summary}\n\n"
        f"**Last 12 hours:**\n{scorecard}\n\n"
        f"**Active reminders:**\n{reminders}"
    )
