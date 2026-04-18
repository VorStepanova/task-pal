"""Streak awareness — detects project gaps and wins across history files.

Runs twice daily (9 AM and 6 PM) as a daemon thread. Writes proactive
messages to ~/.taskpal_chat_inject.json for chat_process.py to pick up.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta

HISTORY_DIR = os.path.expanduser("~/.taskpal_history")
COMPLETIONS_PATH = os.path.expanduser("~/.taskpal_completions.json")
INJECT_PATH = os.path.expanduser("~/.taskpal_chat_inject.json")

_STORY_CRYPT_KEYWORDS = {
    "story crypt", "storycrypt", "tiptap", "world bible", "bootstrap",
    "dramaturg", "pgvector", "celery", "drf",
}
_STORY_CRYPT_EXPLICIT = {
    "working on story crypt", "story crypt session", "work on story crypt",
}
_GHOST_VESSEL_KEYWORDS = {
    "ghost vessel", "ria", "julian", "emmeline", "calista", "billous",
    "rohbin", "theren", "vivienne", "monroe", "gregory",
}
_GHOST_VESSEL_EXPLICIT = {
    "working on ghost vessel", "ghost vessel session", "wrote today",
    "writing session", "work on the story", "write the story",
}


def _load_completions() -> list[dict]:
    if not os.path.exists(COMPLETIONS_PATH):
        return []
    try:
        with open(COMPLETIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _load_history_sessions(since: datetime) -> list[dict]:
    """Load all history sessions updated after `since`."""
    if not os.path.exists(HISTORY_DIR):
        return []
    sessions = []
    try:
        for fname in os.listdir(HISTORY_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(HISTORY_DIR, fname)
            try:
                with open(path) as f:
                    session = json.load(f)
                ended_at = session.get("ended_at", "")
                if ended_at and datetime.fromisoformat(ended_at) >= since:
                    sessions.append(session)
            except Exception:
                continue
    except Exception:
        pass
    return sessions


def _session_mentions(session: dict, explicit: set, keywords: set) -> str:
    """Return 'explicit', 'keyword', or '' based on what's found in session."""
    text = " ".join(
        m.get("content", "").lower()
        for m in session.get("messages", [])
    )
    for phrase in explicit:
        if phrase in text:
            return "explicit"
    for kw in keywords:
        if kw in text:
            return "keyword"
    return ""


def _last_project_session(
    explicit: set, keywords: set, days_back: int = 14
) -> tuple[str, int] | None:
    """Find the most recent session mentioning a project.

    Returns (confidence, days_ago) or None if no session found.
    """
    since = datetime.now() - timedelta(days=days_back)
    sessions = _load_history_sessions(since)
    best: tuple[str, int] | None = None
    for session in sessions:
        confidence = _session_mentions(session, explicit, keywords)
        if not confidence:
            continue
        ended_at = session.get("ended_at", "")
        try:
            ended = datetime.fromisoformat(ended_at)
            days_ago = (datetime.now() - ended).days
            if best is None or days_ago < best[1]:
                best = (confidence, days_ago)
        except Exception:
            continue
    return best


def _completions_for(task: str, since: datetime) -> list[dict]:
    completions = _load_completions()
    return [
        c for c in completions
        if c.get("task") == task
        and datetime.fromisoformat(
            c.get("completed_at", "1970-01-01")
        ) >= since
    ]


def _write_inject(message: str) -> None:
    try:
        with open(INJECT_PATH, "w") as f:
            json.dump({
                "message": message,
                "written_at": datetime.now().isoformat(timespec="seconds"),
            }, f, indent=2)
        time.sleep(15)  # give inject_loop time to pick it up before next msg
    except Exception:
        pass


def _check_streaks(is_pm: bool) -> None:
    now = datetime.now()
    messages: list[str] = []

    # ── Story Crypt ───────────────────────────────────────────────────────
    sc = _last_project_session(_STORY_CRYPT_EXPLICIT, _STORY_CRYPT_KEYWORDS)
    if sc is None or sc[1] >= 2:
        days = sc[1] if sc else 99
        messages.append(
            f"Hey. You haven't touched Story Crypt in {days} days. "
            f"That's not great. 😤"
        )
    elif sc[1] == 0:
        # session today — check for streak
        streak_sessions = _load_history_sessions(now - timedelta(days=3))
        streak_days = set()
        for s in streak_sessions:
            conf = _session_mentions(
                s, _STORY_CRYPT_EXPLICIT, _STORY_CRYPT_KEYWORDS
            )
            if conf:
                try:
                    d = datetime.fromisoformat(s.get("ended_at", ""))
                    streak_days.add(d.date())
                except Exception:
                    pass
        if len(streak_days) >= 3:
            messages.append(
                "STORY CRYPT THREE DAYS RUNNING. You're actually doing it. 🥳"
            )

    # ── Ghost Vessel ──────────────────────────────────────────────────────
    gv = _last_project_session(_GHOST_VESSEL_EXPLICIT, _GHOST_VESSEL_KEYWORDS)
    if gv is None or gv[1] >= 5:
        days = gv[1] if gv else 99
        messages.append(
            f"It's been {days} days since you wrote anything for "
            f"Ghost Vessel. Ria is waiting. 😤"
        )
    elif gv[1] == 0:
        messages.append(
            "You wrote! Ghost Vessel is happening! Ria appreciates it. 🥳"
        )

    # Friday weekly warning
    if now.weekday() == 4:  # Friday
        week_start = now - timedelta(days=now.weekday())
        gv_this_week = _last_project_session(
            _GHOST_VESSEL_EXPLICIT, _GHOST_VESSEL_KEYWORDS, days_back=7
        )
        if gv_this_week is None or gv_this_week[1] >= (now - week_start).days:
            messages.append(
                "It's Friday and you haven't had a Ghost Vessel session "
                "this week. Your writing coach will ask. 😬"
            )

    # ── Meds ─────────────────────────────────────────────────────────────
    meds_today = _completions_for("Meds", now - timedelta(hours=26))
    if not meds_today:
        messages.append(
            "Did you take your meds today? I don't see it logged. "
            "This one's important. 😡"
        )
    else:
        # Check streak
        meds_3d = _completions_for("Meds", now - timedelta(days=3))
        days_with_meds = set(
            datetime.fromisoformat(c["completed_at"]).date()
            for c in meds_3d
        )
        if len(days_with_meds) >= 3:
            messages.append(
                "Meds three days in a row. This is huge, genuinely. 😎"
            )

    # ── Water (PM only) ───────────────────────────────────────────────────
    if is_pm:
        water_today = _completions_for(
            "Drink Water", now.replace(hour=0, minute=0, second=0)
        )
        if len(water_today) < 2:
            messages.append(
                "You've barely logged any water today. The headaches "
                "are self-inflicted at this point. 💧"
            )

    # Fire messages one at a time with a gap so inject_loop can keep up
    for msg in messages:
        _write_inject(msg)


def _seconds_until(hour: int) -> float:
    """Return seconds until the next occurrence of `hour`:00."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def _streak_loop() -> None:
    while True:
        secs_9am = _seconds_until(9)
        secs_6pm = _seconds_until(18)
        wait = min(secs_9am, secs_6pm)
        time.sleep(wait)
        is_pm = datetime.now().hour >= 12
        try:
            _check_streaks(is_pm=is_pm)
        except Exception:
            pass
        time.sleep(60)  # prevent double-firing within the same minute


def start() -> None:
    """Start the streak checker daemon thread. Call once from chat_process.py."""
    t = threading.Thread(
        target=_streak_loop, daemon=True, name="taskpal-streaks"
    )
    t.start()
