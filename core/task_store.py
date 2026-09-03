"""Durable, atomic task lifecycle storage for Vaelor."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Dict, List, Optional


TERMINAL_STATES = {"completed", "failed", "cancelled"}
VALID_STATES = {
    "pending", "running", "waiting", "interrupted", "completed", "failed", "cancelled"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, path: Optional[Path] = None):
        root = Path(__file__).resolve().parent.parent
        self.path = Path(path or root / "memory" / "tasks.json")
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])
        self.recover_interrupted()

    def _read(self) -> List[dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8-sig"))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _write(self, tasks: List[dict]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def create(self, request: str, contract: Optional[dict] = None, session_id: Optional[str] = None) -> dict:
        with self._lock:
            tasks = self._read()
            stamp = _now()
            task = {
                "id": str(uuid.uuid4())[:12],
                "request": request,
                "contract": contract or {},
                "session_id": session_id,
                "status": "pending",
                "created_at": stamp,
                "updated_at": stamp,
                "attempts": 0,
                "events": [],
                "result": None,
            }
            tasks.append(task)
            self._write(tasks[-500:])
            return deepcopy(task)

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for task in self._read():
                if task.get("id") == task_id:
                    return deepcopy(task)
        return None

    def list(self, limit: int = 50) -> List[dict]:
        with self._lock:
            tasks = sorted(self._read(), key=lambda item: item.get("updated_at", ""), reverse=True)
            return deepcopy(tasks[:max(1, min(int(limit or 50), 200))])

    def update(self, task_id: str, status: Optional[str] = None, result: Any = None) -> dict:
        if status is not None and status not in VALID_STATES:
            raise ValueError(f"Invalid task status: {status}")
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                if status is not None:
                    task["status"] = status
                    if status == "running":
                        task["attempts"] = int(task.get("attempts", 0)) + 1
                if result is not None:
                    task["result"] = str(result)[:20000]
                task["updated_at"] = _now()
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def add_event(self, task_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> dict:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                event = {
                    "timestamp": _now(),
                    "type": str(event_type)[:80],
                    "data": self._bounded(data or {}),
                }
                task.setdefault("events", []).append(event)
                task["events"] = task["events"][-250:]
                task["updated_at"] = event["timestamp"]
                self._write(tasks)
                return deepcopy(event)
        raise KeyError(f"Unknown task: {task_id}")

    def cancel(self, task_id: str, reason: str = "Cancelled by user.") -> dict:
        """Request cancellation and persist it atomically with its audit event."""
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                if task.get("status") == "completed":
                    raise ValueError("Completed tasks cannot be cancelled.")
                if task.get("status") == "cancelled":
                    return deepcopy(task)
                stamp = _now()
                task["status"] = "cancelled"
                task["result"] = str(reason)[:20000]
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp,
                    "type": "cancelled",
                    "data": {"reason": str(reason)[:8000]},
                })
                task["events"] = task["events"][-250:]
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def is_cancelled(self, task_id: str) -> bool:
        task = self.get(task_id)
        return bool(task and task.get("status") == "cancelled")

    def recover_interrupted(self) -> int:
        with self._lock:
            tasks = self._read()
            changed = 0
            for task in tasks:
                if task.get("status") == "running":
                    task["status"] = "interrupted"
                    task["updated_at"] = _now()
                    task.setdefault("events", []).append({
                        "timestamp": task["updated_at"],
                        "type": "interrupted",
                        "data": {"reason": "Vaelor restarted before task completion."},
                    })
                    changed += 1
            if changed:
                self._write(tasks)
            return changed

    @staticmethod
    def _bounded(data: Dict[str, Any]) -> Dict[str, Any]:
        safe = {}
        for key, value in data.items():
            if isinstance(value, str):
                safe[str(key)] = value[:8000]
            elif isinstance(value, (int, float, bool)) or value is None:
                safe[str(key)] = value
            else:
                safe[str(key)] = str(value)[:8000]
        return safe
