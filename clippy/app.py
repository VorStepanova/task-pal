"""Clippy menu bar application — orchestration layer.

This module owns the rumps event loop, all timers, and the wiring between
every other module. It is the single place where observations (from monitor,
reminders, chat) get turned into UI decisions.
"""

import json
import os
from datetime import datetime

import rumps

from clippy.config import Config
from clippy.face import Face
from clippy.monitor import Monitor
from clippy.chat.window import ChatWindow
from clippy.reminders import scheduler


class ClippyApp(rumps.App):
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
        self.menu = ["💬 Open Chat", "Quit"]

    def _tick(self, _sender: rumps.Timer) -> None:
        """Timer callback — fires every 5 seconds on the main thread.

        Updates the menu bar icon based on current monitor state and config.
        """
        self.title = self._face.current_icon()
        self._write_monitor_snapshot()

    def _write_monitor_snapshot(self) -> None:
        snapshot = {
            "active_app": self._monitor.current_app(),
            "app_duration_secs": self._monitor.current_app_duration(),
            "idle_secs": self._monitor.idle_duration(),
            "sampled_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = os.path.expanduser("~/.clippy_monitor_state.json")
        try:
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
        except Exception:
            pass  # never let a write failure crash the main thread

    @rumps.clicked("💬 Open Chat")
    def _open_chat(self, _) -> None:
        self._chat_window.open()

    @rumps.clicked("Quit")
    def _quit(self, _) -> None:
        """Terminate the chat subprocess cleanly before quitting."""
        self._chat_window.close()
        rumps.quit_application()
