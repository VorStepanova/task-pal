"""Clippy menu bar application — orchestration layer.

This module owns the rumps event loop, all timers, and the wiring between
every other module. It is the single place where observations (from monitor,
reminders, chat) get turned into UI decisions.
"""

import rumps

from clippy.config import Config
from clippy.face import Face
from clippy.monitor import Monitor
from clippy.chat.window import ChatWindow


class ClippyApp(rumps.App):
    """rumps application — boots all subsystems and owns the timer loop.

    Instantiates Config, Monitor, and Face; starts the monitor thread; and
    updates the menu bar icon on every timer tick.
    """

    def __init__(self) -> None:
        super().__init__("📎", quit_button="Quit")
        self._config = Config()
        self._monitor = Monitor()
        self._monitor.start()
        self._face = Face(self._config, self._monitor)
        self._tick_timer = rumps.Timer(self._tick, 5)
        self._tick_timer.start()
        self._chat_window = ChatWindow()
        self.menu = ["💬 Open Chat"]

    def _tick(self, _sender: rumps.Timer) -> None:
        """Timer callback — fires every 5 seconds on the main thread.

        Updates the menu bar icon based on current monitor state and config.
        """
        self.title = self._face.current_icon()

    @rumps.clicked("💬 Open Chat")
    def _open_chat(self, _) -> None:
        self._chat_window.open()
