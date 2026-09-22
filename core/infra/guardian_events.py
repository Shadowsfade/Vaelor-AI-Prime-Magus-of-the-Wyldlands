"""Bounded, redacted recovery event log for the guardian.

Events are structured, size-capped, and scrubbed before they ever touch
disk. No credentials, environment dumps, private prompts, or model
reasoning can survive ``record()``.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.infra.condition import redact


MAX_EVENTS_ON_DISK = 500
MAX_FIELD_CHARS = 400
EVENT_TYPES = frozenset({
    "guardian_start",
    "guardian_stop",
    "probe_result",
    "restart_attempt",
    "restart_success",
    "restart_failure",
    "budget_exhausted",
    "circuit_open",
    "circuit_close",
    "budget_reset",
    "state_recovered",
    "policy_blocked",
    "duplicate_guardian",
    "duplicate_child",
    "stale_pid_cleared",
    "config_error",
    "child_timeout",
    "child_cleanup",
    "shutdown_requested",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k)[:80]: _clip(v) for k, v in list(value.items())[:20]}
    return str(value)[:MAX_FIELD_CHARS]


@dataclass
class RecoveryEvent:
    """One bounded, structured recovery record."""

    type: str
    detail: str = ""
    data: dict = field(default_factory=dict)
    at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "type": self.type,
            "detail": _clip(self.detail),
            "data": redact(_clip(self.data)),
        }


class RecoveryEventLog:
    """Append-only structured log with a hard cap and redaction.

    Thread-safe. Safe to construct with an unwritable path: the in-memory
    ring still works and persistence degrades to a no-op rather than
    raising during recovery.
    """

    def __init__(self, path: Optional[Path] = None, *,
                 max_events: int = MAX_EVENTS_ON_DISK):
        self.path = Path(path) if path else None
        self.max_events = max(1, int(max_events))
        self._events: list = []
        self._lock = threading.Lock()
        self._persist_ok = True

    def record(self, event_type: str, detail: str = "", *,
               data: Optional[dict] = None) -> RecoveryEvent:
        if event_type not in EVENT_TYPES:
            event_type = "probe_result"
        ev = RecoveryEvent(type=event_type, detail=str(detail or ""),
                           data=dict(data or {}))
        with self._lock:
            self._events.append(ev)
            if len(self._events) > self.max_events:
                overflow = len(self._events) - self.max_events
                del self._events[:overflow]
            self._flush_locked()
        return ev

    def _flush_locked(self) -> None:
        if self.path is None or not self._persist_ok:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = [e.to_dict() for e in self._events]
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # Persisting must never break recovery; stay in memory only.
            self._persist_ok = False

    def events(self) -> list:
        with self._lock:
            return [e.to_dict() for e in self._events]

    def recent(self, n: int = 10) -> list:
        with self._lock:
            return [e.to_dict() for e in self._events[-n:]]

    def count(self, event_type: str) -> int:
        with self._lock:
            return sum(1 for e in self._events if e.type == event_type)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            if self.path and self.path.exists() and self._persist_ok:
                try:
                    self.path.unlink()
                except OSError:
                    self._persist_ok = False

    @property
    def persists(self) -> bool:
        return self.path is not None and self._persist_ok
