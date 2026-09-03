"""Lifecycle-bound durable heartbeat supervision for long-running tasks."""
from __future__ import annotations

import threading
import time


class TaskHeartbeat:
    def __init__(self, store, task_id: str, interval_seconds: float = 30.0):
        self.store = store
        self.task_id = task_id
        self.interval = max(0.01, float(interval_seconds))
        self._stop = threading.Event()
        self._thread = None
        self._started = None

    def __enter__(self):
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=min(1.0, self.interval + 0.1))

    def _run(self):
        while not self._stop.wait(self.interval):
            task = self.store.get(self.task_id)
            if not task or task.get("status") != "running":
                return
            elapsed = max(0, int(time.monotonic() - self._started))
            try:
                self.store.add_event(
                    self.task_id,
                    "heartbeat",
                    {"elapsed_seconds": elapsed, "message": "Vaelor is still working."},
                )
            except Exception:
                # Visibility must never become a new task failure mode.
                pass
