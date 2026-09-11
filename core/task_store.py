"""Durable, atomic task lifecycle storage for Vaelor."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Dict, List, Optional


TERMINAL_STATES = {"completed", "failed", "cancelled"}
LEASE_SECONDS = 60
MAX_STEPS = 100
STEP_STATES = {"pending", "running", "succeeded", "failed", "interrupted", "verifying", "blocked"}
FAILURE_CATEGORIES = {"TRANSIENT", "RECOVERABLE", "REQUIRES_ACTION", "TERMINAL"}
RECOVERY_DECISIONS = {
    "RESUME_SAFE", "RETRY_SAFE", "VERIFY_BEFORE_RETRY",
    "WAIT_FOR_APPROVAL", "BLOCKED", "TERMINAL_FAILURE",
}
VALID_STATES = {"pending", "running", "waiting", "interrupted", "completed", "failed", "cancelled"}
STATE_TRANSITIONS = {
    "pending": {"pending", "running", "waiting", "cancelled"},
    "running": {"running", "waiting", "interrupted", "completed", "failed", "cancelled"},
    "waiting": {"waiting", "pending", "running", "failed", "cancelled"},
    "interrupted": {"interrupted", "pending", "running", "failed", "cancelled"},
    "completed": {"completed"},
    "failed": {"failed", "pending", "running", "cancelled"},
    "cancelled": {"cancelled"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_transition(current: str, target: str) -> None:
    if current not in VALID_STATES or target not in VALID_STATES:
        raise ValueError(f"Invalid task state: {current} -> {target}")
    if target not in STATE_TRANSITIONS[current]:
        raise ValueError(f"Invalid task transition: {current} -> {target}")


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

    def create(self, request: str, contract: Optional[dict] = None, session_id: Optional[str] = None,
               workspace: Optional[str] = None, max_runtime_seconds: Optional[int] = None) -> dict:
        with self._lock:
            tasks = self._read()
            stamp = _now()
            task = {
                "id": str(uuid.uuid4())[:12],
                "request": request,
                "contract": contract or {},
                "session_id": session_id,
                "workspace": workspace,
                "max_runtime_seconds": max_runtime_seconds,
                "status": "pending",
                "created_at": stamp,
                "updated_at": stamp,
                "attempts": 0,
                "events": [],
                "result": None,
                "pending_approval": None,
                "authorized_action": None,
                "lease": None,
                "steps": [],
                "recovery": None,
                "retry": None,
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
                    _validate_transition(str(task.get("status", "pending")), status)
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

    def record_verification(self, task_id: str, record: Dict[str, Any]) -> dict:
        """Persist one bounded, serialization-safe independent verification record."""
        allowed = {
            key: record.get(key) for key in (
                "task_id", "step_id", "governed_fingerprint", "evidence_id",
                "verifier_identity", "status", "reason", "fresh_observed_evidence",
            ) if key in record
        }
        bounded = self._bounded(allowed)
        # A persisted record is an audit event, never a mutable task field.
        return self.add_event(task_id, "verification_recorded", bounded)

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
                _validate_transition(str(task.get("status", "pending")), "cancelled")
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

    def request_approval(self, task_id: str, action: Dict[str, Any]) -> dict:
        """Pause for one exact action without widening the task's autonomy policy."""
        raw_requirement = action.get("verification_requirement") if isinstance(action, dict) else None
        if raw_requirement is not None:
            from core.verification import VerificationRequirement
            VerificationRequirement.from_dict(raw_requirement)
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                _validate_transition(str(task.get("status", "pending")), "waiting")
                stamp = _now()
                task["status"] = "waiting"
                task["waiting_reason"] = "approval"
                task["pending_approval"] = deepcopy(action)
                task["authorized_action"] = None
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp,
                    "type": "approval_required",
                    "data": self._bounded(action),
                })
                task["events"] = task["events"][-250:]
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def approve_action(self, task_id: str, fingerprint: str) -> dict:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                pending = task.get("pending_approval") or {}
                if task.get("status") != "waiting" or task.get("waiting_reason") != "approval":
                    raise ValueError("Task is not waiting for action approval.")
                if not fingerprint or fingerprint != pending.get("fingerprint"):
                    raise ValueError("Approval fingerprint is stale or does not match the pending action.")
                _validate_transition(str(task.get("status", "pending")), "pending")
                stamp = _now()
                task["authorized_action"] = fingerprint
                task["authorized_state_binding"] = pending.get("state_binding")
                task["authorized_invocation"] = deepcopy(pending)
                task["pending_approval"] = None
                task["waiting_reason"] = None
                task["status"] = "pending"
                task["result"] = None
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp, "type": "action_approved",
                    "data": {"fingerprint": fingerprint},
                })
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def consume_action_approval(self, task_id: str, fingerprint: str, state_binding: Optional[str] = None,
                                invocation: Optional[dict] = None) -> bool:
        """Atomically consume a matching one-time authorization."""
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                if task.get("authorized_action") != fingerprint:
                    return False
                expected_state = task.get("authorized_state_binding")
                if expected_state and (state_binding is None or expected_state != state_binding):
                    return False
                stored_invocation = task.get("authorized_invocation") or {}
                if invocation is not None:
                    for key in ("tool", "arguments", "target", "scope", "effects", "task_id", "step_id", "provenance_ids", "verification_requirement"):
                        if stored_invocation.get(key) != invocation.get(key):
                            return False
                    from core.verification import VerificationRequirement
                    raw_requirement = stored_invocation.get("verification_requirement")
                    try:
                        requirement = VerificationRequirement.from_dict(raw_requirement)
                    except (TypeError, ValueError):
                        return False
                    if requirement.task_id != str(task_id) or requirement.action_fingerprint != stored_invocation.get("governed_fingerprint"):
                        return False
                task["authorized_action"] = None
                task["authorized_state_binding"] = None
                task["authorized_invocation"] = None
                task["updated_at"] = _now()
                task.setdefault("events", []).append({
                    "timestamp": task["updated_at"], "type": "approval_consumed",
                    "data": {"fingerprint": fingerprint},
                })
                self._write(tasks)
                return True
        raise KeyError(f"Unknown task: {task_id}")

    def reject_action(self, task_id: str, fingerprint: str) -> dict:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                pending = task.get("pending_approval") or {}
                if task.get("status") != "waiting" or pending.get("fingerprint") != fingerprint:
                    raise ValueError("Rejection fingerprint is stale or does not match the pending action.")
                _validate_transition(str(task.get("status", "pending")), "cancelled")
                stamp = _now()
                task["status"] = "cancelled"
                task["waiting_reason"] = None
                task["pending_approval"] = None
                task["authorized_action"] = None
                task["result"] = "Action rejected by user."
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp, "type": "action_rejected",
                    "data": {"fingerprint": fingerprint},
                })
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def revise(self, task_id: str, request: str, contract: dict) -> dict:
        """Replace a waiting task's definition while preserving identity and history."""
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                if task.get("status") != "waiting":
                    raise ValueError("Only tasks waiting for clarification can be revised.")
                _validate_transition(str(task.get("status", "pending")), "pending")
                stamp = _now()
                task["request"] = str(request)
                task["contract"] = deepcopy(contract)
                task["status"] = "pending"
                task["waiting_reason"] = None
                task["result"] = None
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp,
                    "type": "clarification_received",
                    "data": {},
                })
                task["events"] = task["events"][-250:]
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def keep_waiting(self, task_id: str, request: str, contract: dict, question: str) -> dict:
        """Persist an insufficient answer and the refined clarification contract."""
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                if task.get("status") != "waiting":
                    raise ValueError("Task is not waiting for clarification.")
                _validate_transition(str(task.get("status", "pending")), "waiting")
                stamp = _now()
                task["request"] = str(request)
                task["contract"] = deepcopy(contract)
                task["result"] = str(question)[:20000]
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp,
                    "type": "clarification_insufficient",
                    "data": {"question": str(question)[:8000]},
                })
                task["events"] = task["events"][-250:]
                self._write(tasks)
                return deepcopy(task)
        raise KeyError(f"Unknown task: {task_id}")

    def claim(self, task_id: str, owner: str, lease_seconds: int = LEASE_SECONDS,
              now: Optional[datetime] = None) -> Optional[dict]:
        """Atomically claim a task for one supervisor lease."""
        if not owner:
            raise ValueError("A supervisor owner is required.")
        current = now or datetime.now(timezone.utc)
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                status = str(task.get("status", "pending"))
                if status in TERMINAL_STATES or status == "waiting":
                    return None
                recovery = task.get("recovery") or {}
                if recovery.get("decision") in {"VERIFY_BEFORE_RETRY", "WAIT_FOR_APPROVAL",
                                                "BLOCKED", "TERMINAL_FAILURE"}:
                    return None
                lease = task.get("lease") or {}
                expiry = self._parse_time(lease.get("lease_expires_at"))
                if lease.get("owner") and expiry and expiry > current and lease.get("owner") != owner:
                    return None
                reclaimed = bool(lease.get("owner") and lease.get("owner") != owner)
                stamp = current.isoformat()
                expiry_stamp = (current + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
                task["lease"] = {
                    "task_id": task_id,
                    "owner": str(owner)[:200],
                    "claimed_at": lease.get("claimed_at") if lease.get("owner") == owner else stamp,
                    "lease_expires_at": expiry_stamp,
                    "last_heartbeat": stamp,
                    "attempt": int(task.get("attempts", 0)) + 1,
                }
                if status != "running":
                    _validate_transition(status, "running")
                    task["status"] = "running"
                    task["attempts"] = int(task.get("attempts", 0)) + 1
                task["updated_at"] = stamp
                event_type = "lease_reclaimed" if reclaimed else "lease_claimed"
                task.setdefault("events", []).append({
                    "timestamp": stamp, "type": event_type,
                    "data": {"owner": str(owner)[:200], "lease_expires_at": expiry_stamp},
                })
                task["events"] = task["events"][-250:]
                self._write(tasks)
                return deepcopy(task)
            raise KeyError(f"Unknown task: {task_id}")

    def heartbeat(self, task_id: str, owner: str, lease_seconds: int = LEASE_SECONDS,
                  now: Optional[datetime] = None) -> bool:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                lease = task.get("lease") or {}
                expiry = self._parse_time(lease.get("lease_expires_at"))
                if lease.get("owner") != owner or (expiry and expiry <= current):
                    return False
                stamp = current.isoformat()
                lease["last_heartbeat"] = stamp
                lease["lease_expires_at"] = (current + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
                task["lease"] = lease
                task["updated_at"] = stamp
                self._write(tasks)
                return True
            raise KeyError(f"Unknown task: {task_id}")

    def release(self, task_id: str, owner: str, reason: str = "Supervisor finished.") -> bool:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                lease = task.get("lease") or {}
                if lease.get("owner") != owner:
                    return False
                task["lease"] = None
                stamp = _now()
                task["updated_at"] = stamp
                self._write(tasks)
                return True
            raise KeyError(f"Unknown task: {task_id}")

    def begin_step(self, task_id: str, owner: str, executor: str, action_category: str,
                   step_id: Optional[str] = None, retry_limit: int = 2) -> dict:
        """Persist a bounded operational step before its action begins."""
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                lease = task.get("lease") or {}
                expiry = self._parse_time(lease.get("lease_expires_at"))
                if lease.get("owner") != owner or (expiry and expiry <= datetime.now(timezone.utc)):
                    raise ValueError("Task is not owned by a valid supervisor lease.")
                step_id = step_id or str(uuid.uuid4())[:12]
                if any(step.get("id") == step_id for step in task.get("steps", [])):
                    raise ValueError(f"Step already exists: {step_id}")
                steps = task.setdefault("steps", [])
                step = {
                    "id": step_id, "task_id": task_id, "sequence": len(steps) + 1,
                    "executor": str(executor)[:200], "action_category": str(action_category)[:200],
                    "state": "running", "started_at": _now(), "completed_at": None,
                    "attempt": len([x for x in steps if x.get("action_category") == action_category]) + 1,
                    "retry_limit": max(0, int(retry_limit)), "result_summary": None,
                    "error_category": None, "verification_state": "not_started",
                    "retry_eligible": False, "error": None,
                }
                steps.append(step)
                task["steps"] = steps[-MAX_STEPS:]
                task["updated_at"] = step["started_at"]
                self._write(tasks)
                return deepcopy(step)
            raise KeyError(f"Unknown task: {task_id}")

    def finish_step(self, task_id: str, owner: str, step_id: str, state: str,
                    result_summary: Optional[str] = None, error_category: Optional[str] = None,
                    verification_state: str = "not_required", retry_eligible: bool = False,
                    error: Optional[str] = None) -> dict:
        if state not in STEP_STATES:
            raise ValueError(f"Invalid step state: {state}")
        if error_category is not None and error_category not in FAILURE_CATEGORIES:
            raise ValueError(f"Invalid failure category: {error_category}")
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task.get("id") != task_id:
                    continue
                lease = task.get("lease") or {}
                if lease.get("owner") != owner:
                    raise ValueError("Step update requires the active supervisor lease.")
                for step in task.get("steps", []):
                    if step.get("id") != step_id:
                        continue
                    step.update({
                        "state": state, "completed_at": _now() if state in {"succeeded", "failed", "blocked"} else None,
                        "result_summary": str(result_summary)[:4000] if result_summary is not None else None,
                        "error_category": error_category, "verification_state": str(verification_state)[:100],
                        "retry_eligible": bool(retry_eligible), "error": str(error)[:8000] if error else None,
                    })
                    task["updated_at"] = _now()
                    self._write(tasks)
                    return deepcopy(step)
                raise KeyError(f"Unknown step: {step_id}")
            raise KeyError(f"Unknown task: {task_id}")

    @staticmethod
    def classify_failure(raw_error: Any, category: Optional[str] = None, attempt: int = 1,
                         retry_limit: int = 2, mutation: bool = False,
                         verification_state: str = "not_required") -> dict:
        text = str(raw_error or "")
        upper = text.upper()
        if category is None:
            if any(word in upper for word in ("APPROVAL", "CREDENTIAL", "AMBIGUOUS", "GOVERNANCE")):
                category = "REQUIRES_ACTION"
            elif any(word in upper for word in ("TIMEOUT", "CONNECTION", "NETWORK", "LOCKED", "UNAVAILABLE")):
                category = "TRANSIENT"
            elif any(word in upper for word in ("WORKER DIED", "SESSION DISAPPEARED", "STALE LEASE", "PROCESS DISAPPEARED")):
                category = "RECOVERABLE"
            else:
                category = "TERMINAL"
        if category not in FAILURE_CATEGORIES:
            raise ValueError(f"Invalid failure category: {category}")
        safe_retry = category in {"TRANSIENT", "RECOVERABLE"} and int(attempt) < max(0, int(retry_limit))
        if mutation and verification_state not in {"passed", "verified"}:
            safe_retry = False
        return {
            "category": category, "retryable": safe_retry, "attempt": int(attempt),
            "retry_limit": max(0, int(retry_limit)),
            "next_retry_at": (_now() if safe_retry else None),
            "summary": text[:1000] or category.replace("_", " ").title(),
            "raw_error": text[:8000],
        }

    def record_failure(self, task_id: str, owner: str, step_id: str, raw_error: Any,
                       category: Optional[str] = None, mutation: bool = False,
                       verification_state: str = "not_required") -> dict:
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        step = next((x for x in task.get("steps", []) if x.get("id") == step_id), None)
        if step is None:
            raise KeyError(f"Unknown step: {step_id}")
        failure = self.classify_failure(raw_error, category, step.get("attempt", 1),
                                         step.get("retry_limit", 2), mutation, verification_state)
        self.finish_step(task_id, owner, step_id, "failed", failure["summary"], failure["category"],
                         verification_state, failure["retryable"], failure["raw_error"])
        with self._lock:
            tasks = self._read()
            for item in tasks:
                if item.get("id") != task_id:
                    continue
                item["retry"] = failure
                if mutation and verification_state not in {"passed", "verified"}:
                    decision, reason = "VERIFY_BEFORE_RETRY", "Mutation completion is uncertain."
                    target = "interrupted"
                elif failure["category"] == "REQUIRES_ACTION":
                    decision, reason, target = "WAIT_FOR_APPROVAL", failure["summary"], "waiting"
                    item["waiting_reason"] = "action_required"
                elif failure["retryable"]:
                    decision, reason, target = "RETRY_SAFE", failure["summary"], "interrupted"
                else:
                    decision, reason, target = "TERMINAL_FAILURE", failure["summary"], "failed"
                _validate_transition(str(item.get("status", "pending")), target)
                item["status"] = target
                item["recovery"] = {"decision": decision, "reason": reason, "at": _now()}
                item["updated_at"] = _now()
                self._write(tasks)
                return deepcopy(failure)
        raise KeyError(f"Unknown task: {task_id}")

    def recover_interrupted(self) -> int:
        with self._lock:
            tasks = self._read()
            changed = 0
            for task in tasks:
                if task.get("status") != "running":
                    continue
                _validate_transition("running", "interrupted")
                task["status"] = "interrupted"
                last_step = (task.get("steps") or [])[-1:]
                uncertain = bool(last_step and last_step[0].get("state") in {"running", "verifying"}
                                 and last_step[0].get("action_category") in {"mutation", "write", "delete"})
                decision = "VERIFY_BEFORE_RETRY" if uncertain else "RESUME_SAFE"
                stamp = _now()
                task["lease"] = None
                task["recovery"] = {
                    "decision": decision,
                    "reason": "Vaelor restarted before task completion.",
                    "at": stamp,
                }
                task["updated_at"] = stamp
                task.setdefault("events", []).append({
                    "timestamp": stamp, "type": "interrupted",
                    "data": {"reason": "Vaelor restarted before task completion.", "recovery": decision},
                })
                task["events"] = task["events"][-250:]
                changed += 1
            if changed:
                self._write(tasks)
            return changed

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

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
