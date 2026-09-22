"""Guardian state: PID/instance files, stale detection, atomic persistence.

Rules enforced here:
- one guardian instance only
- one Vaelor child instance only
- a PID file is acted upon only after it is *proven* stale
- corrupt state fails closed to a clean, reportable state

Proving staleness means the recorded PID either does not exist or does not
match the identity we recorded with it. A live PID with a different
identity is stale; a live PID matching ours is a real conflict.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_process_alive(pid: int) -> bool:
    """Best-effort liveness check that never signals the process."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but not ours: treat as alive, which is the safe answer.
        return True
    except OSError:
        return False
    return True


def _default_identity(pid: int) -> Optional[str]:
    """Read a stable identity for a PID, or None if unavailable.

    Uses ``starttime`` (field 22) of ``/proc/<pid>/stat``: it is fixed for
    the life of the process, so identity does not churn the way scheduling
    state or thread count does, yet it changes whenever a PID is reused.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as fh:
            fields = fh.read().rsplit(")", 1)[-1].split()
        # The rsplit drops `pid (comm)`, so fields[0] is field 3 (state)
        # and field N sits at index N - 3: starttime (22) -> index 19.
        if len(fields) > 19:
            return fields[19]
    except (OSError, IndexError):
        return None
    return None


@dataclass
class PidRecord:
    """Contents of a PID/state file."""

    pid: int
    identity: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    role: str = "child"
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "pid": self.pid,
            "identity": self.identity,
            "created_at": self.created_at,
            "role": self.role,
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, data: dict) -> "PidRecord":
        return cls(
            pid=int(data.get("pid", -1)),
            identity=data.get("identity"),
            created_at=str(data.get("created_at") or _now_iso()),
            role=str(data.get("role") or "child"),
            meta=dict(data.get("meta") or {}),
        )


class PidFile:
    """A PID file with proven-staleness semantics and atomic writes."""

    def __init__(self, path: Path, *, role: str = "child",
                 alive: Callable[[int], bool] = _default_process_alive,
                 identity_of: Callable[[int], Optional[str]] = _default_identity):
        self.path = Path(path)
        self.role = role
        self._alive = alive
        self._identity_of = identity_of
        self._lock = threading.Lock()

    # -- reading ---------------------------------------------------------
    def read(self) -> Optional[PidRecord]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            rec = PidRecord.from_json(data)
            return rec if rec.pid > 0 else None
        except (ValueError, TypeError):
            # Corrupt file: report unreadable rather than guessing.
            return None

    def exists(self) -> bool:
        return self.path.exists()

    def is_corrupt(self) -> bool:
        if not self.path.exists():
            return False
        return self.read() is None

    def status(self) -> str:
        """'absent' | 'corrupt' | 'alive' | 'stale'."""
        if not self.path.exists():
            return "absent"
        rec = self.read()
        if rec is None:
            return "corrupt"
        if not self._alive(rec.pid):
            return "stale"
        if rec.identity:
            current = self._identity_of(rec.pid)
            if current is not None and current != rec.identity:
                return "stale"   # PID reused by something else
        return "alive"

    # -- writing ---------------------------------------------------------
    def write(self, record: PidRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(record.to_json(), indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def clear(self) -> bool:
        with self._lock:
            try:
                self.path.unlink()
                return True
            except FileNotFoundError:
                return False
            except OSError:
                return False

    # -- guarded operations ---------------------------------------------
    def claim(self, pid: int, *, identity: Optional[str] = None,
              meta: Optional[dict] = None) -> tuple:
        """Try to become the recorded owner.

        Returns (ok, reason). Refuses when a live, matching owner exists.
        A corrupt or provably stale file is replaced.
        """
        with self._lock:
            state = self.status()
            if state == "alive":
                return False, "another live instance owns this pid file"
            if state == "corrupt":
                # Corrupt is not proof of a live owner; safe to replace.
                pass
            record = PidRecord(
                pid=pid,
                identity=identity if identity is not None else self._identity_of(pid),
                role=self.role,
                meta=dict(meta or {}),
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(record.to_json(), indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return True, f"claimed over {state} file"

    def release(self, pid: int) -> bool:
        """Clear the file only if we still own it."""
        with self._lock:
            rec = self.read()
            if rec is None:
                return False
            if rec.pid != pid:
                return False
            try:
                self.path.unlink()
                return True
            except OSError:
                return False

    def prove_stale(self) -> tuple:
        """Return (is_stale, reason) without mutating anything."""
        state = self.status()
        if state in ("absent",):
            return True, "no pid file present"
        if state == "corrupt":
            return True, "pid file is corrupt and cannot identify a live owner"
        if state == "stale":
            rec = self.read()
            detail = "recorded pid is not alive" if rec else "unrecorded"
            if rec and self._alive(rec.pid):
                detail = "recorded pid was reused by another process"
            return True, detail
        return False, "recorded pid is alive and identity matches"


@dataclass
class GuardianState:
    """Persisted guardian bookkeeping, tolerant of corruption."""

    path: Path
    guardian_pid: int = 0
    child_pid: int = 0
    child_started_at: Optional[str] = None
    restarts: int = 0
    last_transition: str = ""
    updated_at: str = field(default_factory=_now_iso)
    corrupt: bool = False

    def save(self) -> None:
        payload = {
            "guardian_pid": self.guardian_pid,
            "child_pid": self.child_pid,
            "child_started_at": self.child_started_at,
            "restarts": self.restarts,
            "last_transition": self.last_transition,
            "updated_at": _now_iso(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def load(cls, path: Path) -> "GuardianState":
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path=path)
        except OSError:
            return cls(path=path, corrupt=True)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("state must be an object")
            return cls(
                path=path,
                guardian_pid=int(data.get("guardian_pid", 0) or 0),
                child_pid=int(data.get("child_pid", 0) or 0),
                child_started_at=data.get("child_started_at"),
                restarts=int(data.get("restarts", 0) or 0),
                last_transition=str(data.get("last_transition") or ""),
                updated_at=str(data.get("updated_at") or _now_iso()),
                corrupt=False,
            )
        except (ValueError, TypeError):
            # Fail closed to a clean state, flagged as corrupt.
            return cls(path=path, corrupt=True)


class InstanceGuard:
    """Prevents duplicate guardian processes via a guardian PID file."""

    def __init__(self, path: Path, *, alive=None, identity_of=None):
        kwargs = {}
        if alive is not None:
            kwargs["alive"] = alive
        if identity_of is not None:
            kwargs["identity_of"] = identity_of
        self.pid_file = PidFile(path, role="guardian", **kwargs)
        self._held_pid: Optional[int] = None

    def acquire(self) -> tuple:
        """Return (acquired, reason). Only one guardian may hold the file."""
        ok, reason = self.pid_file.claim(os.getpid())
        if ok:
            self._held_pid = os.getpid()
        return ok, reason

    def release(self) -> None:
        if self._held_pid is not None:
            self.pid_file.release(self._held_pid)
            self._held_pid = None

    def status(self) -> str:
        return self.pid_file.status()

    def __enter__(self):
        ok, reason = self.acquire()
        if not ok:
            raise RuntimeError(f"duplicate guardian: {reason}")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
