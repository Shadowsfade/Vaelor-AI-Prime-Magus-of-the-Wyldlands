"""Out-of-process Vaelor guardian (R0.2 Phase 2).

Runs independently of the Vaelor API process, so it can restart that
process when it dies. It never restarts itself, and it never executes a
command supplied by a model, task, memory record, web response, or
conversation: only the trusted local config's argv is ever spawned.

Design invariants:
- no shell interpolation (subprocess argv arrays only)
- bounded, redacted, structured recovery events
- exponential backoff with jitter, restart budget, circuit breaker
- stable healthy interval before the budget resets
- one guardian instance, one Vaelor child instance
- stale PID files handled only after proven stale
- clean shutdown on SIGTERM/SIGINT
- remains useful with the model provider unavailable
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from core.infra.condition import bounded_error, redact
from core.infra.guardian_backoff import (
    BackoffPolicy,
    CircuitBreaker,
    RecoveryController,
    RestartBudget,
)
from core.infra.guardian_config import GuardianConfig, GuardianConfigError, load_guardian_config
from core.infra.guardian_events import RecoveryEventLog
from core.infra.guardian_state import GuardianState, InstanceGuard, PidFile, PidRecord
from core.infra.health_contract import HealthReport, assess_health
from core.infra.recovery_authority import Authority, RecoveryAuthorityMatrix
from core.infra.service_adapters import ServiceManagerAdapter


class GuardianError(RuntimeError):
    """Raised for guardian lifecycle problems."""


@dataclass
class ProbeResult:
    """Outcome of one liveness/readiness probe cycle."""

    process_alive: bool
    api_responsive: bool
    ready: bool
    health: Optional[HealthReport] = None
    error: Optional[str] = None
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def state(self) -> str:
        """absent | unhealthy | healthy | unknown."""
        if self.error and not self.process_alive and not self.api_responsive:
            return "unknown"
        if not self.process_alive and not self.api_responsive:
            return "absent"
        if self.process_alive and self.api_responsive and self.ready:
            return "healthy"
        if self.process_alive or self.api_responsive:
            return "unhealthy"
        return "unknown"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "process_alive": self.process_alive,
            "api_responsive": self.api_responsive,
            "ready": self.ready,
            "error": self.error,
            "at": self.at,
            "health": self.health.to_dict() if self.health else None,
        }


class Guardian:
    """Out-of-process supervisor for the configured local Vaelor service."""

    def __init__(self,
                 config: GuardianConfig,
                 *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 spawner: Optional[Callable] = None,
                 probe_fn: Optional[Callable] = None,
                 process_alive_fn: Optional[Callable[[int], bool]] = None,
                 authority: Optional[RecoveryAuthorityMatrix] = None,
                 service_adapter: Optional[ServiceManagerAdapter] = None,
                 rng=None):
        self.config = config
        self._clock = clock
        self._sleep = sleep
        self._spawner = spawner or self._default_spawn
        self._probe_fn = probe_fn or self._default_probe
        self._process_alive = process_alive_fn or self._default_alive
        self.authority = authority or RecoveryAuthorityMatrix()
        self.service_adapter = service_adapter

        self.events = RecoveryEventLog(config.event_log_path,
                                       max_events=config.event_log_max)
        self.state = GuardianState.load(config.state_path)
        self.child_pid_file = PidFile(config.child_pid_path, role="child",
                                      alive=self._process_alive)
        self.instance_guard = InstanceGuard(config.guardian_pid_path,
                                            alive=self._process_alive)

        self.controller = RecoveryController(
            backoff=BackoffPolicy(
                base_seconds=config.backoff_base_seconds,
                max_seconds=config.backoff_max_seconds,
            ),
            budget=RestartBudget(
                max_restarts=config.max_restarts,
                healthy_interval_seconds=config.healthy_interval_seconds,
            ),
            breaker=CircuitBreaker(
                failure_threshold=config.circuit_failure_threshold,
                cooldown_seconds=config.circuit_cooldown_seconds,
            ),
            clock=clock,
            rng=rng,
        )

        self._child: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._acquired = False
        self._last_state = "unknown"

    # ------------------------------------------------------------------
    # process helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _default_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _default_spawn(self, argv, **kwargs) -> "subprocess.Popen":
        # argv arrays only; never shell=True, never string interpolation.
        # ``shell`` is rejected outright rather than merely left unset, so
        # no future caller can reintroduce shell interpretation.
        if "shell" in kwargs:
            raise TypeError("guardian spawn never uses a shell")
        return subprocess.Popen(
            list(argv),
            cwd=str(self.config.worktree),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # probing
    # ------------------------------------------------------------------
    def _http_ok(self, url: str) -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(
                    url=req, timeout=self.config.probe_timeout_seconds) as resp:
                return 200 <= resp.getcode() < 300
        except Exception:      # noqa: BLE001
            return False

    def _default_probe(self) -> ProbeResult:
        api_ok = self._http_ok(self.config.health_url)
        ready_ok = self._http_ok(self.config.readiness_url)
        pid_rec = self.child_pid_file.read()
        pid_alive = bool(pid_rec and self._process_alive(pid_rec.pid))
        process_alive = pid_alive or api_ok
        health = None
        if api_ok:
            try:
                health = assess_health(
                    process_alive=process_alive,
                    health_url=self.config.health_url,
                    readiness_url=self.config.readiness_url,
                    timeout=self.config.probe_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                return ProbeResult(process_alive, api_ok, False,
                                   error=bounded_error(exc))
        return ProbeResult(process_alive, api_ok, ready_ok and api_ok, health=health)

    def probe(self) -> ProbeResult:
        """Run one probe cycle, converting any failure to a bounded result."""
        try:
            result = self._probe_fn()
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(False, False, False, error=bounded_error(exc))
        if not isinstance(result, ProbeResult):
            return ProbeResult(False, False, False,
                               error="probe returned non-ProbeResult")
        return result

    # ------------------------------------------------------------------
    # child lifecycle
    # ------------------------------------------------------------------
    def _stale_child_pid(self) -> tuple:
        """Return (is_stale, reason) for the child PID file, proven."""
        return self.child_pid_file.prove_stale()

    def _clear_stale_child_pid(self) -> None:
        stale, reason = self._stale_child_pid()
        if stale and self.child_pid_file.exists():
            self.child_pid_file.clear()
            self.events.record("stale_pid_cleared", reason,
                               data={"role": "child"})

    def _child_instance_running(self) -> bool:
        """True if a live, identity-matching child PID file exists."""
        return self.child_pid_file.status() == "alive"

    def _supervisor_duplicate_child(self) -> bool:
        # A verified listener or responsive API means a child exists even
        # if our PID file is missing.
        res = self.probe()
        return res.api_responsive or res.process_alive

    def start_child(self) -> tuple:
        """Start the configured Vaelor service.

        Returns (started, reason). Refuses if a live child already exists.
        """
        if self._child_instance_running():
            self.events.record("duplicate_child",
                               "live child PID already recorded")
            return False, "duplicate child already running"

        if self._supervisor_duplicate_child():
            self.events.record("duplicate_child",
                               "responsive API implies a running instance")
            return False, "vaelor API already responsive"

        decision = self.authority.consult(
            "start_local_vaelor",
            command=tuple(self.config.start_command),
            source="guardian",
        )
        if not decision.may_auto_execute:
            self.events.record("policy_blocked",
                               f"start blocked: {decision.reason}",
                               data=decision.to_dict())
            return False, f"policy blocked: {decision.reason}"

        if not self.config.enabled:
            return False, "guardian disabled by configuration"

        try:
            proc = self._spawner(tuple(self.config.start_command))
        except FileNotFoundError as exc:
            self.events.record("config_error",
                               "configured executable not found",
                               data={"error": bounded_error(exc)})
            return False, "missing executable"
        except Exception as exc:  # noqa: BLE001
            self.events.record("restart_failure", "spawn failed",
                               data={"error": bounded_error(exc)})
            return False, "spawn failed"

        self._child = proc
        pid = getattr(proc, "pid", None)
        if pid:
            self.child_pid_file.write(PidRecord(pid=int(pid), role="child"))
        self.state.child_pid = int(pid or 0)
        self.state.child_started_at = datetime.now(timezone.utc).isoformat()
        # Durable counter: survives this process, so recovery history is
        # not lost every time the guardian is invoked afresh.
        self.state.restarts += 1
        self.state.save()

        self.events.record("restart_attempt", "child spawned",
                           data={"pid": pid})
        return True, "started"

    def stop_child(self, timeout: float = 10.0) -> bool:
        """Terminate the child we own, then reap it. Bounded wait."""
        proc = self._child
        if proc is None:
            rec = self.child_pid_file.read()
            if rec and self._process_alive(rec.pid):
                try:
                    os.kill(rec.pid, signal.SIGTERM)
                except OSError:
                    pass
            return True

        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.events.record("child_cleanup", "force-kill did not reap")
                return False
        except Exception as exc:  # noqa: BLE001
            self.events.record("child_cleanup", "wait raised",
                               data={"error": bounded_error(exc)})
        self._child = None
        self.child_pid_file.clear()
        return True

    # ------------------------------------------------------------------
    # recovery decisions
    # ------------------------------------------------------------------
    def decide(self, probe: ProbeResult) -> dict:
        """Deterministically decide what to do for one probe result."""
        state = probe.state

        if state == "healthy":
            return {"action": "none", "reason": "healthy",
                    "authority": Authority.AUTOMATIC.value}

        if state == "unknown":
            return {
                "action": "diagnose",
                "reason": probe.error or "insufficient evidence",
                "authority": Authority.DIAGNOSE_ONLY.value,
            }

        if state == "absent":
            blocked = self.controller.blocked_reason
            if blocked:
                if self.controller.budget.exhausted:
                    # Budget exhaustion is its own observable outcome.
                    return {"action": "budget_exhausted",
                            "reason": blocked,
                            "authority": Authority.DIAGNOSE_ONLY.value}
                return {"action": "wait", "reason": blocked,
                        "authority": Authority.DIAGNOSE_ONLY.value}
            decision = self.authority.consult(
                "restart_local_vaelor",
                command=tuple(self.config.start_command),
                source="guardian",
            )
            if not decision.may_auto_execute:
                return {"action": "request_approval",
                        "reason": decision.reason,
                        "authority": decision.authority.value}
            return {"action": "restart", "reason": "process absent",
                    "authority": Authority.AUTOMATIC.value,
                    "delay_seconds": round(self.controller.next_delay(), 3)}

        # state == unhealthy
        if self.authority.consult("restart_local_vaelor",
                                  blockers=["repeated_crash_loop"]
                                  if self.controller.budget.exhausted else [],
                                  source="guardian").authority \
                is Authority.DIAGNOSE_ONLY:
            return {"action": "diagnose",
                    "reason": "repeated crash loop; automatic restart refused",
                    "authority": Authority.DIAGNOSE_ONLY.value}
        return {"action": "restart", "reason": "process unhealthy",
                "authority": Authority.AUTOMATIC.value,
                "delay_seconds": round(self.controller.next_delay(), 3)}

    # ------------------------------------------------------------------
    # one cycle
    # ------------------------------------------------------------------
    def run_once(self) -> dict:
        """Execute exactly one probe -> decide -> act cycle.

        Read-only with respect to anything outside this guardian's own
        child process and state files.
        """
        probe = self.probe()
        decision = self.decide(probe)
        self.events.record("probe_result",
                           f"state={probe.state} action={decision['action']}",
                           data={"state": probe.state,
                                 "action": decision["action"],
                                 "ready": probe.ready})

        action = decision.get("action")
        outcome = {"probe": probe.to_dict(), "decision": decision,
                   "performed": None}

        if action == "none":
            self.controller.on_child_success()
            if self.controller.tick_healthy():
                self.events.record("budget_reset",
                                   "healthy interval elapsed; budget reset")
            self._last_state = "healthy"
            outcome["performed"] = "none"
            return outcome

        if action in ("diagnose", "wait", "request_approval"):
            self.events.record(
                "policy_blocked" if action != "diagnose" else "state_recovered",
                decision["reason"], data=decision)
            outcome["performed"] = action
            return outcome

        if action == "budget_exhausted":
            self.events.record("budget_exhausted",
                               decision["reason"],
                               data=self.controller.budget.to_dict())
            outcome["performed"] = "budget_exhausted"
            return outcome

        if action == "restart":
            delay = float(decision.get("delay_seconds") or 0)
            if delay > 0:
                self._sleep(min(delay, self.config.backoff_max_seconds))
            if not self.controller.on_restart_attempt():
                self.events.record("budget_exhausted",
                                   "restart budget exhausted",
                                   data=self.controller.budget.to_dict())
                outcome["performed"] = "budget_exhausted"
                return outcome
            started, reason = self.start_child()
            if started:
                self.events.record("restart_success", reason)
                self.controller.on_child_success()
                outcome["performed"] = "restart"
            else:
                self.controller.on_child_failure()
                if self.controller.breaker.state.value == "OPEN":
                    self.events.record("circuit_open",
                                       "circuit breaker opened",
                                       data=self.controller.breaker.to_dict())
                self.events.record("restart_failure", reason)
                outcome["performed"] = "restart_failed"
            return outcome

        outcome["performed"] = "noop"
        return outcome

    # ------------------------------------------------------------------
    # loop / lifecycle
    # ------------------------------------------------------------------
    def status(self) -> dict:
        probe = self.probe()
        # Report the PID that actually holds the guardian lock, not this
        # observer's own PID: ``status`` runs in its own short-lived
        # process and would otherwise print a misleading PID.
        instance = self.instance_guard.status()
        held = (self.instance_guard.pid_file.read()
                if instance == "alive" else None)
        return {
            "enabled": self.config.enabled,
            "guardian_pid": (held.pid if held and held.role == "guardian"
                             else 0),
            "instance": instance,
            "child_pid_status": self.child_pid_file.status(),
            "last_state": self._last_state,
            "probe": probe.to_dict(),
            "decision": self.decide(probe),
            "controller": self.controller.to_dict(),
            "authority_history": self.authority.history()[-20:],
            "recent_events": self.events.recent(10),
            "service_adapter": (self.service_adapter.status()
                                if self.service_adapter else None),
            "config": self.config.to_dict(),
        }

    def acquire(self) -> tuple:
        ok, reason = self.instance_guard.acquire()
        self._acquired = ok
        if ok:
            self.events.record("guardian_start", "guardian instance acquired",
                               data={"pid": os.getpid()})
        else:
            self.events.record("duplicate_guardian", reason)
        return ok, reason

    def release(self) -> None:
        if self._acquired:
            self.instance_guard.release()
            self._acquired = False

    def request_stop(self) -> None:
        self._stop.set()
        self.events.record("shutdown_requested", "stop requested")

    def run(self, max_cycles: Optional[int] = None) -> int:
        """Run the supervision loop until stopped.

        Returns 0 on clean shutdown, 2 if another guardian already owns
        the instance lock (duplicate prevention).
        """
        ok, reason = self.acquire()
        if not ok:
            print(f"guardian not started: {reason}", file=sys.stderr)
            return 2

        cycles = 0
        try:
            while not self._stop.is_set():
                self.run_once()
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    break
                # Wake in small slices so shutdown stays responsive.
                remaining = self.config.poll_interval_seconds
                while remaining > 0 and not self._stop.is_set():
                    slice_s = min(0.25, remaining)
                    self._sleep(slice_s)
                    remaining -= slice_s
        except KeyboardInterrupt:
            self.events.record("shutdown_requested", "keyboard interrupt")
        finally:
            self.events.record("guardian_stop",
                               f"stopped after {cycles} cycles")
            # Every exit path lands here. Releasing only the lock would
            # orphan a live child nobody supervises and leave a stale
            # ``vaelor.pid`` behind — the documented clean shutdown is
            # stop child -> persist state -> release lock.
            self._teardown()
        return 0

    def _teardown(self) -> None:
        """Stop the supervised child, persist state, then release the lock."""
        self.stop_child()
        self.state.last_transition = "shutdown"
        self.state.save()
        self.release()

    def shutdown(self) -> None:
        """Graceful teardown: stop the child, persist state, release lock."""
        self.request_stop()
        self._teardown()

    # ------------------------------------------------------------------
    # signal wiring
    # ------------------------------------------------------------------
    def install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            self.request_stop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Not the main thread, or unsupported platform.
                pass


# ---------------------------------------------------------------------------
# CLI-facing helpers
# ---------------------------------------------------------------------------

def build_guardian(root: Optional[Path] = None,
                   config_path: Optional[Path] = None) -> Guardian:
    cfg = load_guardian_config(root, explicit=config_path)
    return Guardian(cfg)


def guardian_status(root: Optional[Path] = None,
                    config_path: Optional[Path] = None) -> dict:
    try:
        g = build_guardian(root, config_path)
    except GuardianConfigError as exc:
        return {"error": bounded_error(exc), "overall": "MISCONFIGURED"}
    try:
        return g.status()
    except Exception as exc:  # noqa: BLE001
        return {"error": bounded_error(exc), "overall": "UNKNOWN"}


def guardian_run_once(root: Optional[Path] = None,
                      config_path: Optional[Path] = None) -> dict:
    try:
        g = build_guardian(root, config_path)
    except GuardianConfigError as exc:
        return {"error": bounded_error(exc), "overall": "MISCONFIGURED"}
    try:
        return g.run_once()
    except Exception as exc:  # noqa: BLE001
        return {"error": bounded_error(exc), "overall": "UNKNOWN"}


def guardian_run(root: Optional[Path] = None,
                 config_path: Optional[Path] = None,
                 max_cycles: Optional[int] = None) -> int:
    try:
        g = build_guardian(root, config_path)
    except GuardianConfigError as exc:
        print(f"guardian configuration error: {exc}", file=sys.stderr)
        return 2
    g.install_signal_handlers()
    return g.run(max_cycles=max_cycles)
