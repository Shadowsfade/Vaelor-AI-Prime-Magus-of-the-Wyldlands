"""Durable interval schedules that launch ordinary Vaelor tasks without overlap."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Callable, Optional

from core.project_context import resolve_workspace
from core.tools.git_ops import _auto_ok
from core.tools.shell_exec import _audit


MIN_INTERVAL_SECONDS = 300
MAX_INTERVAL_SECONDS = 30 * 24 * 60 * 60
ACTIVE_TASK_STATES = {"pending", "running", "waiting"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _boolean(value) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError("enabled must be true or false")


class ScheduleStore:
    def __init__(self, path: Optional[Path] = None):
        root = Path(__file__).resolve().parent.parent
        self.path = Path(path or root / "memory" / "schedules.json")
        self._lock = threading.RLock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise ValueError(f"schedule storage is unreadable: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("schedule storage must contain a JSON array")
        return data

    def _write(self, schedules: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(schedules, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _interval(value: int) -> int:
        interval = int(value)
        if not MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
            raise ValueError(
                f"interval_seconds must be {MIN_INTERVAL_SECONDS}-{MAX_INTERVAL_SECONDS}"
            )
        return interval

    def create(self, name: str, prompt: str, interval_seconds: int,
               workspace: Optional[str] = None, enabled: bool = True,
               max_steps: int = 12, max_runtime_seconds: int = 900) -> dict:
        clean_name = " ".join(str(name).strip().split())[:120]
        clean_prompt = str(prompt).strip()[:20000]
        if not clean_name or not clean_prompt:
            raise ValueError("schedule name and prompt are required")
        interval = self._interval(interval_seconds)
        max_steps = max(3, min(int(max_steps), 25))
        max_runtime_seconds = max(10, min(int(max_runtime_seconds), 1200))
        resolved_workspace = str(resolve_workspace(workspace)) if workspace else None
        stamp = _now()
        item = {
            "id": str(uuid.uuid4())[:12],
            "name": clean_name,
            "prompt": clean_prompt,
            "interval_seconds": interval,
            "workspace": resolved_workspace,
            "enabled": _boolean(enabled),
            "max_steps": max_steps,
            "max_runtime_seconds": max_runtime_seconds,
            "created_at": _iso(stamp),
            "updated_at": _iso(stamp),
            "next_run_at": _iso(stamp + timedelta(seconds=interval)),
            "last_run_at": None,
            "last_task_id": None,
            "last_error": None,
            "run_count": 0,
        }
        with self._lock:
            schedules = self._read()
            schedules.append(item)
            self._write(schedules[-200:])
        return deepcopy(item)

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            schedules = sorted(
                self._read(), key=lambda item: item.get("created_at", ""), reverse=True
            )
            return deepcopy(schedules[:max(1, min(int(limit or 50), 200))])

    def get(self, schedule_id: str) -> Optional[dict]:
        with self._lock:
            for item in self._read():
                if item.get("id") == schedule_id:
                    return deepcopy(item)
        return None

    def set_enabled(self, schedule_id: str, enabled: bool) -> dict:
        with self._lock:
            schedules = self._read()
            for item in schedules:
                if item.get("id") != schedule_id:
                    continue
                stamp = _now()
                item["enabled"] = _boolean(enabled)
                item["updated_at"] = _iso(stamp)
                if enabled:
                    item["next_run_at"] = _iso(
                        stamp + timedelta(seconds=self._interval(item["interval_seconds"]))
                    )
                    item["last_error"] = None
                self._write(schedules)
                return deepcopy(item)
        raise KeyError(f"unknown schedule: {schedule_id}")

    def due(self, now: Optional[datetime] = None) -> list[dict]:
        now = now or _now()
        return [
            item for item in self.list(200)
            if item.get("enabled") and _parse(item["next_run_at"]) <= now
        ]

    def claim(self, schedule_id: str, now: Optional[datetime] = None) -> Optional[dict]:
        """Atomically advance a still-due schedule before any task is launched."""
        now = now or _now()
        with self._lock:
            schedules = self._read()
            for item in schedules:
                if item.get("id") != schedule_id:
                    continue
                if not item.get("enabled") or _parse(item["next_run_at"]) > now:
                    return None
                interval = self._interval(item["interval_seconds"])
                item["last_run_at"] = _iso(now)
                item["next_run_at"] = _iso(now + timedelta(seconds=interval))
                item["run_count"] = int(item.get("run_count", 0)) + 1
                item["last_error"] = None
                item["updated_at"] = _iso(now)
                self._write(schedules)
                return deepcopy(item)
        return None

    def record_task(self, schedule_id: str, task_id: Optional[str] = None,
                    error: Optional[str] = None) -> dict:
        with self._lock:
            schedules = self._read()
            for item in schedules:
                if item.get("id") != schedule_id:
                    continue
                if task_id is not None:
                    item["last_task_id"] = str(task_id)[:120]
                item["last_error"] = str(error)[:2000] if error else None
                item["updated_at"] = _iso(_now())
                self._write(schedules)
                return deepcopy(item)
        raise KeyError(f"unknown schedule: {schedule_id}")


class SchedulerService:
    def __init__(self, store: ScheduleStore, brain, poll_seconds: int = 15,
                 thread_factory: Callable = threading.Thread):
        self.store = store
        self.brain = brain
        self.poll_seconds = max(1, int(poll_seconds))
        self.thread_factory = thread_factory
        self._stop = threading.Event()
        self._worker = None

    def run_due_once(self, now: Optional[datetime] = None) -> list[str]:
        launched = []
        for candidate in self.store.due(now):
            previous_id = candidate.get("last_task_id")
            previous = self.brain.get_task(previous_id) if previous_id else None
            if previous and previous.get("status") in ACTIVE_TASK_STATES:
                continue
            claimed = self.store.claim(candidate["id"], now)
            if not claimed:
                continue
            try:
                task = self.brain.prepare_task(
                    claimed["prompt"],
                    session_id=f"schedule:{claimed['id']}",
                    workspace=claimed.get("workspace"),
                    max_runtime_seconds=claimed["max_runtime_seconds"],
                )
                self.store.record_task(claimed["id"], task_id=task["id"])
                if task.get("status") != "waiting":
                    worker = self.thread_factory(
                        target=self.brain.run_prepared_task,
                        args=(task["id"], claimed["max_steps"]),
                        daemon=True,
                    )
                    worker.start()
                launched.append(task["id"])
            except Exception as exc:
                self.store.record_task(claimed["id"], error=str(exc))
        return launched

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            try:
                self.run_due_once()
            except Exception as exc:
                try:
                    _audit({"tool": "scheduler_service", "error": str(exc)[:2000]})
                except Exception:
                    pass

    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = self.thread_factory(target=self._loop, daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=min(2, self.poll_seconds + 0.1))


schedule_store = ScheduleStore()


def create_recurring_task(name: str, prompt: str, interval_seconds: int,
                          workspace: str = "", enabled: bool = True,
                          max_steps: int = 12, max_runtime_seconds: int = 900,
                          confirm: str = "no") -> dict:
    if not _auto_ok(confirm):
        raise PermissionError("creating a recurring task requires confirmation or trusted/admin mode")
    item = schedule_store.create(
        name, prompt, interval_seconds, workspace or None, enabled,
        max_steps, max_runtime_seconds,
    )
    _audit({"tool": "create_recurring_task", "schedule_id": item["id"], "enabled": item["enabled"]})
    return item


def list_recurring_tasks(limit: int = 50) -> list[dict]:
    return schedule_store.list(limit)


def set_recurring_task_enabled(schedule_id: str, enabled: bool,
                               confirm: str = "no") -> dict:
    if not _auto_ok(confirm):
        raise PermissionError("changing a recurring task requires confirmation or trusted/admin mode")
    item = schedule_store.set_enabled(schedule_id, enabled)
    _audit({"tool": "set_recurring_task_enabled", "schedule_id": schedule_id, "enabled": item["enabled"]})
    return item
