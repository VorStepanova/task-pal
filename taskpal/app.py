"""TaskPal menu bar application — orchestration layer.

This module owns the rumps event loop, all timers, and the wiring between
every other module. It is the single place where observations (from monitor,
reminders, chat) get turned into UI decisions.
"""

import json
import os
import sys
from datetime import datetime

import rumps

from taskpal.config import Config
from taskpal.face import Face
from taskpal.monitor import Monitor
from taskpal.chat.window import ChatWindow
from taskpal.reminders import scheduler
from taskpal.reminders import config_scheduler
from taskpal.reminders import skincare_scheduler
from taskpal.reminders.state import (
    clear_all_pending, load_pending, mark_done, mark_dismissed, mark_pending,
    snooze_for_hours,
)


class TaskPalApp(rumps.App):
    """rumps application — boots all subsystems and owns the timer loop.

    Instantiates Config, Monitor, and Face; starts the monitor thread; and
    updates the menu bar icon on every timer tick.
    """

    def __init__(self) -> None:
        super().__init__("📎", quit_button=None)
        self._config = Config()
        self._monitor = Monitor()
        self._monitor.start()
        self._face = Face(self._config, self._monitor)
        self._tick_timer = rumps.Timer(self._tick, 5)
        self._tick_timer.start()
        self._chat_window = ChatWindow()
        scheduler.start()
        config_scheduler.start()
        skincare_scheduler.start()
        self._history_item = rumps.MenuItem(
            self._history_label(),
            callback=self._toggle_history
        )
        self._retention_item = rumps.MenuItem(
            self._retention_label(),
            callback=self._toggle_retention
        )
        self.menu = [
            "💬 Open Chat",
            rumps.separator,
            self._history_item,
            self._retention_item,
            rumps.separator,
            "🗑️ Clear pending",
            rumps.separator,
            "🔄 Restart",
            "Quit",
        ]
        self._pending_menu_keys: list[str] = []
        self._sync_pending_menu()

    def _pending_rows_deduped(self) -> list[dict]:
        """One row per label — the earliest valid due_at wins."""
        seen: dict[str, dict] = {}
        for r in load_pending():
            if not isinstance(r, dict):
                continue
            due = r.get("due_at")
            if not due or not isinstance(due, str):
                continue
            try:
                datetime.fromisoformat(due)
            except (ValueError, TypeError):
                continue
            label = r.get("label", "Reminder")
            if label not in seen or due < seen[label].get("due_at", ""):
                seen[label] = r
        rows = list(seen.values())
        rows.sort(key=lambda x: x.get("due_at", ""))
        return rows

    @staticmethod
    def _row_status(r: dict) -> str:
        """Return 'done', 'dismissed', 'snoozed', or 'pending' for one row."""
        s = r.get("status")
        if s in ("done", "dismissed"):
            return s
        next_fire = r.get("next_fire_at")
        if next_fire:
            try:
                if datetime.fromisoformat(next_fire) > datetime.now():
                    return "snoozed"
            except (ValueError, TypeError):
                pass
        return "pending"

    _STATUS_PREFIX = {
        "pending": "",
        "snoozed": "💤 ",
        "done": "✅ ",
        "dismissed": "❌ ",
    }

    def _sync_pending_menu(self) -> None:
        """Rebuild Pending section above Quit from ~/.taskpal_pending_reminders.json."""
        for key in self._pending_menu_keys:
            try:
                del self.menu[key]
            except KeyError:
                pass
        self._pending_menu_keys.clear()

        rows = self._pending_rows_deduped()
        if not rows:
            return

        to_insert: list[rumps.MenuItem] = []
        for r in rows:
            label = r.get("label", "Reminder")
            emoji = r.get("emoji", "")
            status = self._row_status(r)
            prefix = self._STATUS_PREFIX.get(status, "")
            title = f"{prefix}{emoji} {label}".strip()

            parent = rumps.MenuItem(title)

            def _done_cb(_sender, lb=label) -> None:
                mark_done(lb)
                self._sync_pending_menu()

            def _not_today_cb(_sender, lb=label) -> None:
                mark_dismissed(lb)
                self._sync_pending_menu()

            def _snooze_cb(_sender, lb=label, hrs=1) -> None:
                snooze_for_hours(lb, hrs)
                self._sync_pending_menu()

            def _snooze_3h_cb(_sender, lb=label) -> None:
                snooze_for_hours(lb, 3)
                self._sync_pending_menu()

            def _pending_cb(_sender, lb=label) -> None:
                mark_pending(lb)
                self._sync_pending_menu()

            parent["✓ Done"] = rumps.MenuItem("✓ Done", callback=_done_cb)
            parent["Not today"] = rumps.MenuItem("Not today", callback=_not_today_cb)
            parent["Snooze 1h"] = rumps.MenuItem("Snooze 1h", callback=_snooze_cb)
            parent["Snooze 3h"] = rumps.MenuItem("Snooze 3h", callback=_snooze_3h_cb)
            if status != "pending":
                parent["↩︎ Mark pending"] = rumps.MenuItem(
                    "↩︎ Mark pending", callback=_pending_cb
                )

            to_insert.append(parent)

        for item in to_insert:
            self.menu.insert_after("🗑️ Clear pending", item)
            self._pending_menu_keys.append(item.title)

    def _tick(self, _sender: rumps.Timer) -> None:
        """Timer callback — fires every 5 seconds on the main thread.

        Updates the menu bar icon based on current monitor state and config.
        """
        self.title = self._face.current_icon()
        self._write_monitor_snapshot()
        self._push_chat_face()
        self._sync_pending_menu()

    def _write_monitor_snapshot(self) -> None:
        snapshot = {
            "active_app": self._monitor.current_app(),
            "app_duration_secs": self._monitor.current_app_duration(),
            "idle_secs": self._monitor.idle_duration(),
            "sampled_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = os.path.expanduser("~/.taskpal_monitor_state.json")
        try:
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
        except Exception:
            pass  # never let a write failure crash the main thread

    def _push_chat_face(self) -> None:
        """Write the current chat face emoji to ~/.taskpal_face_state.json."""
        try:
            emoji = self._face.current_chat_face()
            path = os.path.expanduser("~/.taskpal_face_state.json")
            with open(path, "w") as f:
                import json
                json.dump({"face": emoji}, f)
        except Exception:
            pass

    def _history_label(self) -> str:
        enabled = self._config.get("history_enabled", True)
        check = "✓ " if enabled else "   "
        return f"{check}Save chat history"

    def _retention_label(self) -> str:
        days = self._config.get("history_retention_days", None)
        if days is None:
            return "   History: unlimited"
        return f"   History: {days} days"

    def _toggle_history(self, _) -> None:
        enabled = self._config.get("history_enabled", True)
        self._config.set("history_enabled", not enabled)
        self._history_item.title = self._history_label()

    def _toggle_retention(self, _) -> None:
        days = self._config.get("history_retention_days", None)
        # Cycle: unlimited → 30 days → 7 days → unlimited
        if days is None:
            self._config.set("history_retention_days", 30)
        elif days == 30:
            self._config.set("history_retention_days", 7)
        else:
            self._config.set("history_retention_days", None)
        self._retention_item.title = self._retention_label()

    @rumps.clicked("💬 Open Chat")
    def _open_chat(self, _) -> None:
        self._chat_window.open()

    @rumps.clicked("🗑️ Clear pending")
    def _clear_pending(self, _) -> None:
        """Wipe pending + dismissed state; config scheduler will re-queue today."""
        clear_all_pending()
        self._sync_pending_menu()

    @rumps.clicked("🔄 Restart")
    def _restart(self, _) -> None:
        """Spawn a fresh TaskPal process, then quit this one."""
        self._chat_window.close()
        import subprocess
        env = os.environ.copy()
        subprocess.Popen(
            [sys.executable] + sys.argv,
            cwd=os.getcwd(),
            env=env,
            start_new_session=True,
        )
        rumps.quit_application()

    @rumps.clicked("Quit")
    def _quit(self, _) -> None:
        """Terminate the chat subprocess cleanly before quitting."""
        self._chat_window.close()
        rumps.quit_application()
