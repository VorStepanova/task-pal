"""pywebview window lifecycle for the TaskPal chat UI.

This module owns the chat window's process lifecycle: spawning chat_process.py
as a subprocess and detecting whether it is still running. The Python↔JS
bridge now lives entirely in chat_process.py, which runs on its own main
thread free from rumps.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional


_CHAT_PROCESS = os.path.join(os.path.dirname(__file__), "chat_process.py")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class ChatWindow:
    """Manages the lifecycle of the chat window subprocess.

    A single ``ChatWindow`` instance can be opened and closed repeatedly.
    Each call to ``open()`` spawns a fresh subprocess; if the previous
    one is still alive, open() is a no-op.
    """

    def __init__(self) -> None:
        """Initialise with no subprocess running."""
        self._process: Optional[subprocess.Popen] = None

    def open(self) -> None:
        """Spawn chat_process.py as a subprocess if not already running.

        Uses sys.executable so the subprocess inherits the same Poetry venv.
        Does nothing if the window process is already alive.
        """
        if self.is_open():
            return

        env = os.environ.copy()
        env["PYTHONPATH"] = _PROJECT_ROOT

        self._process = subprocess.Popen(
            [sys.executable, _CHAT_PROCESS],
            cwd=_PROJECT_ROOT,
            env=env,
        )

    def is_open(self) -> bool:
        """Return whether the chat window subprocess is currently running.

        Returns:
            True if the subprocess exists and has not yet exited.
        """
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        """Terminate the chat window subprocess if it is running."""
        if self.is_open():
            self._process.terminate()
            self._process = None
