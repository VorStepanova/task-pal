# TaskPal

A personal judgy AI-powered accountability companion that lives in your macOS menu bar.

TaskPal is a solo project built to solve a specific problem: I needed something 
that could hear me, not just remind me. Scheduled reminders don't know that 
you're stressed, or that you mentioned something important in passing, or that 
you've been in the same app for four hours. TaskPal does.

---

## What It Does

- **Lives in the menu bar** with an icon that changes based on mood and state
- **Chat window** — talk to Claude directly; TaskPal reads your context and responds
- **Time-aware** — every message is timestamped so TaskPal knows what time it is 
  and can reason about it
- **Ad-hoc reminders** — mention something time-sensitive in chat and TaskPal 
  extracts it and fires a real reminder when the time comes
- **Activity monitoring** — watches which app is in focus, how long, and when 
  you've gone idle
- **Scheduled reminders** — replaces nudge.py; same escalation modals, streaks, 
  and snooze logic, just bigger
- **Escalation** — if you ignore something long enough, TaskPal stops asking nicely

---

## Project Structure

```
.
├── main.py              # Entry point
├── taskpal/
│   ├── app.py           # rumps menubar app, menu building, orchestration
│   ├── monitor.py       # Activity monitoring: app focus, idle detection, duration
│   ├── face.py          # Icon logic and mood states
│   ├── config.py        # Loads and saves config
│   ├── chat/
│   │   ├── window.py    # pywebview setup and Python↔JS bridge
│   │   ├── client.py    # Anthropic API calls
│   │   ├── extractor.py # Pulls reminders and tasks out of AI responses
│   │   └── ui/
│   │       ├── index.html
│   │       ├── style.css
│   │       └── chat.js
│   └── reminders/
│       ├── scheduler.py # Scheduled reminder logic (absorbed from nudge.py)
│       ├── escalator.py # Escalation modals
│       └── state.py     # Daily state and history
└── assets/
    └── faces/           # Menu bar icons
```

---

## Stack

- Python 3.13.3 (pyenv)
- Poetry for dependency management
- rumps — macOS menubar
- pywebview — native chat window (HTML/CSS/JS, not a browser tab)
- anthropic — Claude integration

---

## Running It

```bash
poetry install
poetry run python main.py
```

---

*This is a personal tool. It is not on the App Store. It will tell you to go 
to bed and not know what time it is if you open a new chat. That's a known 
issue and also kind of the point.*