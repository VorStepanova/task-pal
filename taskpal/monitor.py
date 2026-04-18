"""Activity monitor for macOS — samples frontmost app and user idle time.

This module has no imports from within the taskpal package. It is a pure
data-source: the background thread writes state, callers read it through
the public snapshot methods.
"""

from __future__ import annotations

import threading
import time

from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateHIDSystemState,
)

IDLE_THRESHOLD: int = 300  # seconds before a session is considered idle (5 min)
POLL_INTERVAL: int = 5     # seconds between activity samples


class Monitor:
    """Background sampler for macOS activity data.

    Runs a daemon thread that wakes every POLL_INTERVAL seconds and records:
    - which application is currently in focus
    - when that application first became focused (to compute dwell time)
    - how many seconds have elapsed since the last user input event

    All public methods are safe to call from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_app: str = ""
        self._app_start: float = time.monotonic()
        self._idle_secs: float = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True, name="taskpal-monitor")

    def start(self) -> None:
        """Start the background sampling thread.

        Safe to call once. The thread is a daemon and will be killed
        automatically when the main process exits.
        """
        self._thread.start()

    def current_app(self) -> str:
        """Return the name of the application currently in focus.

        Returns an empty string if no application has been sampled yet.
        """
        with self._lock:
            return self._active_app

    def current_app_duration(self) -> int:
        """Return the number of seconds the current app has been continuously in focus.

        Computed from the stored start time at call time so it is accurate
        between poll intervals.
        """
        with self._lock:
            return int(time.monotonic() - self._app_start)

    def is_idle(self) -> bool:
        """Return True if the user has been idle longer than IDLE_THRESHOLD seconds."""
        with self._lock:
            return self._idle_secs >= IDLE_THRESHOLD

    def idle_duration(self) -> int:
        """Return the number of seconds since the last user input event.

        Updated every POLL_INTERVAL seconds; resolution is therefore ±POLL_INTERVAL.
        """
        with self._lock:
            return int(self._idle_secs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sample(self) -> None:
        """Take one activity snapshot and update internal state."""
        info = NSWorkspace.sharedWorkspace().activeApplication()
        app_name: str = info.get("NSApplicationName", "") if info else ""

        idle: float = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateHIDSystemState, kCGAnyInputEventType
        )

        with self._lock:
            if app_name != self._active_app:
                self._active_app = app_name
                self._app_start = time.monotonic()
            self._idle_secs = idle

    def _run(self) -> None:
        """Thread target — poll in a loop until the process exits."""
        while True:
            try:
                self._sample()
            except Exception:
                pass  # never let a transient API error kill the thread
            time.sleep(POLL_INTERVAL)
