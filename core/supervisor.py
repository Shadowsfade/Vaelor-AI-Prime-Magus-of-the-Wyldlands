"""Durable, single-process supervisor queue for autonomous task continuation."""
from __future__ import annotations
from datetime import datetime, timezone
import os
import threading
import time
from typing import Callable, Optional

class SupervisorRunner:
    """Consume durable TaskStore decisions one bounded task execution at a time."""
    def __init__(self, store, brain=None, owner: Optional[str] = None,
                 clock: Callable[[], datetime] = None, sleeper: Callable[[float], None] = None,
                 preflight: Optional[Callable[[dict], object]] = None,
                 verifier: Optional[Callable[[dict], object]] = None,
                 max_tasks_per_cycle: int = 10, backoff_base_seconds: float = 5.0,
                 backoff_cap_seconds: float = 300.0, thread_factory: Callable = threading.Thread):
        self.store = store
        self.brain = brain
        self.owner = owner or f"supervisor-{os.getpid()}-{id(self)}"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleeper = sleeper or time.sleep
        self.preflight = preflight
        self.verifier = verifier
        self.max_tasks_per_cycle = max(1, int(max_tasks_per_cycle))
        self.backoff_base_seconds = max(0.0, float(backoff_base_seconds))
        self.backoff_cap_seconds = max(self.backoff_base_seconds, float(backoff_cap_seconds))
        self._stop = threading.Event()
        self.thread_factory = thread_factory
        self._worker = None

    def _now(self):
        value = self.clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _time(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def eligible(self, now: Optional[datetime] = None):
        current = now or self._now()
        result = []
        for task in self.store.list(limit=200):
            status = str(task.get("status", "pending"))
            if status not in {"pending", "interrupted"}:
                continue
            lease = task.get("lease") or {}
            expiry = self._time(lease.get("lease_expires_at"))
            if lease.get("owner") and expiry and expiry > current and lease.get("owner") != self.owner:
                continue
            decision = (task.get("recovery") or {}).get("decision")
            if decision in {"WAIT_FOR_APPROVAL", "BLOCKED", "TERMINAL_FAILURE"}:
                continue
            retry = task.get("retry") or {}
            retry_at = self._time(retry.get("next_retry_at"))
            if retry_at and retry_at > current:
                continue
            if retry and not retry.get("retryable", True) and decision not in {"RESUME_SAFE", "VERIFY_BEFORE_RETRY"}:
                continue
            result.append(task)
        return sorted(result, key=lambda item: (item.get("created_at", ""), item.get("id", "")))

    def _event(self, task_id, name, data=None):
        try:
            self.store.add_event(task_id, name, data or {})
        except Exception:
            pass

    def _preflight(self, task):
        self._event(task["id"], "preflight_started", {"owner": self.owner})
        if self.preflight is not None:
            result = self.preflight(task)
            if result is False:
                return False, "Preflight rejected task prerequisites."
            if isinstance(result, str):
                return False, result
        workspace = task.get("workspace")
        if workspace and not os.path.exists(workspace):
            return False, f"Task workspace does not exist: {workspace}"
        return True, ""

    def _verify_uncertain(self, task):
        self._event(task["id"], "recovery_started", {"decision": "VERIFY_BEFORE_RETRY"})
        self._event(task["id"], "verification_required", {"reason": "uncertain mutation"})
        if self.verifier is None:
            return False, "No independent verifier is available for the uncertain mutation."
        result = self.verifier(task)
        passed = result.get("status") in {"passed", "verified", True} if isinstance(result, dict) else result is True
        try:
            self.store.record_recovery_verification(task["id"], passed)
        except AttributeError:
            self._event(task["id"], "recovery_verified", {"passed": passed})
        return passed, "" if passed else "Independent verification did not establish the expected outcome."

    def _block(self, task_id, reason, event="task_blocked"):
        self.store.set_recovery(task_id, "BLOCKED", reason, status="waiting")
        self._event(task_id, event, {"reason": reason})

    def run_task(self, task):
        task_id = task["id"]
        if (task.get("recovery") or {}).get("decision") == "VERIFY_BEFORE_RETRY":
            passed, reason = self._verify_uncertain(task)
            if not passed:
                self._block(task_id, reason)
                return self.store.get(task_id)
            task = self.store.set_recovery(task_id, "RETRY_SAFE", "Independent verification passed.", status="interrupted")
        ok, reason = self._preflight(task)
        if not ok:
            self._block(task_id, reason, "preflight_failed")
            return self.store.get(task_id)
        claimed = self.store.claim(task_id, self.owner)
        if not claimed:
            return None
        self._event(task_id, "task_claimed", {"owner": self.owner})
        try:
            if self.store.is_cancelled(task_id):
                return self.store.get(task_id)
            if self.brain is None:
                raise RuntimeError("Supervisor runner has no Brain executor.")
            result = self.brain.act(claimed.get("request", ""), session_id=claimed.get("session_id"),
                task_contract=claimed.get("contract"), task_id=task_id, workspace=claimed.get("workspace"),
                max_runtime_seconds=claimed.get("max_runtime_seconds") or 900, owner=self.owner)
            final = str(result or "")
            if "WAITING_APPROVAL" in final.upper():
                self._event(task_id, "approval_required", {})
            elif "CANCELLED" in final.upper() or self.store.is_cancelled(task_id):
                self._event(task_id, "task_cancelled", {})
            elif final.upper().startswith("FINAL_SUMMARY: SUCCESS"):
                self._event(task_id, "task_succeeded", {})
            else:
                self._event(task_id, "task_failed", {"summary": final[:1000]})
            return self.store.get(task_id)
        except Exception as exc:
            try:
                self.store.record_runner_failure(task_id, self.owner, str(exc),
                    self.backoff_base_seconds, self.backoff_cap_seconds)
            except Exception:
                self._event(task_id, "runner_task_failure", {"error": str(exc)[:1000]})
            return self.store.get(task_id)
        finally:
            try:
                self.store.release(task_id, self.owner, "Supervisor cycle finished.")
            except Exception:
                pass

    def run_once(self, now: Optional[datetime] = None):
        processed = []
        for task in self.eligible(now)[:self.max_tasks_per_cycle]:
            try:
                result = self.run_task(task)
                if result:
                    processed.append(result)
            except Exception as exc:
                self._event(task["id"], "runner_task_isolated", {"error": str(exc)[:1000]})
        return processed

    def start(self, poll_interval_seconds: float = 5.0):
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        worker = self.thread_factory(
            target=self.run_forever,
            args=(poll_interval_seconds,),
            daemon=True,
            name="vaelor-supervisor",
        )
        try:
            worker.start()
        except Exception:
            self._stop.set()
            self._worker = None
            raise
        self._worker = worker

    def stop(self, timeout_seconds: float = 2.0):
        self._stop.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(0.1, float(timeout_seconds)))
        if worker is None or not worker.is_alive():
            self._worker = None

    def run_forever(self, poll_interval_seconds: float = 5.0):
        interval = max(0.1, float(poll_interval_seconds))
        while not self._stop.is_set():
            processed = self.run_once()
            if not processed:
                self._stop.wait(interval)

    def request_stop(self):
        self._stop.set()
