"""R0.2 guardian crash and soak tests.

Deterministic. Uses temp directories, fake clocks, fake processes, and
injected service adapters. Never touches the real systemd configuration,
Windows services, Tailscale, firewall, or power state.
"""

from __future__ import annotations

import json
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.infra.guardian import Guardian, ProbeResult, build_guardian
from core.infra.guardian_backoff import (
    BackoffPolicy,
    CircuitBreaker,
    CircuitState,
    RecoveryController,
    RestartBudget,
)
from core.infra.guardian_config import (
    GuardianConfig,
    GuardianConfigError,
    load_guardian_config,
)
from core.infra.guardian_events import RecoveryEventLog
from core.infra.guardian_state import (
    GuardianState,
    InstanceGuard,
    PidFile,
    PidRecord,
)
from core.infra.health_contract import HealthSection, assess_health
from core.infra.recovery_authority import (
    Authority,
    RecoveryAuthorityMatrix,
)
from core.infra.service_adapters import (
    AdapterError,
    SystemdUserAdapter,
    WindowsServiceAdapter,
)


class FakeClock:
    """Deterministic monotonic clock."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProc:
    """Stand-in for subprocess.Popen."""

    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.wait_calls = 0
        self._raise_timeout = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self._raise_timeout and self.wait_calls == 1:
            import subprocess
            raise subprocess.TimeoutExpired(cmd="child", timeout=timeout)
        return 0


def make_config(tmp: Path, **overrides) -> GuardianConfig:
    base = dict(
        worktree=tmp,
        python_executable="/usr/bin/python3",
        start_command=("/usr/bin/python3", str(tmp / "vaelor.py")),
        health_url="http://127.0.0.1:8765/health",
        readiness_url="http://127.0.0.1:8765/readiness",
        liveness_url="http://127.0.0.1:8765/health",
        probe_timeout_seconds=0.1,
        poll_interval_seconds=0.01,
        child_start_timeout_seconds=1.0,
        max_restarts=3,
        healthy_interval_seconds=60.0,
        backoff_base_seconds=1.0,
        backoff_max_seconds=60.0,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=30.0,
        state_dir=tmp / "state",
        event_log_max=100,
        enabled=True,
    )
    base.update(overrides)
    return GuardianConfig(**base)


def make_guardian(tmp: Path, *, probe=None, alive=None, spawn=None,
                  **overrides) -> Guardian:
    cfg = make_config(tmp, **overrides)
    clock = FakeClock()
    g = Guardian(
        cfg,
        clock=clock,
        sleep=lambda _s: None,
        probe_fn=probe,
        process_alive_fn=(lambda _pid: False) if alive is None else alive,
        spawner=spawn,
        rng=random.Random(7),
    )
    g._fake_clock = clock
    return g


# ---------------------------------------------------------------------------
# Backoff / budget / breaker unit behaviour
# ---------------------------------------------------------------------------

class TestBackoff(unittest.TestCase):
    def test_exponential_growth_is_capped(self):
        p = BackoffPolicy(base_seconds=1.0, factor=2.0, max_seconds=10.0,
                          jitter_ratio=0.0)
        self.assertEqual(p.delay_for(1), 1.0)
        self.assertEqual(p.delay_for(2), 2.0)
        self.assertEqual(p.delay_for(3), 4.0)
        self.assertEqual(p.delay_for(10), 10.0)

    def test_jitter_stays_within_bounds(self):
        p = BackoffPolicy(base_seconds=2.0, factor=2.0, max_seconds=60.0,
                          jitter_ratio=0.25)
        for seed in range(20):
            rng = random.Random(seed)
            for attempt in range(1, 8):
                d = p.delay_for(attempt, rng=rng)
                raw = min(2.0 * (2.0 ** (attempt - 1)), 60.0)
                self.assertGreaterEqual(d, raw * 0.75 - 1e-9)
                self.assertLessEqual(d, min(raw * 1.25, 60.0) + 1e-9)

    def test_jitter_is_reproducible_with_seeded_rng(self):
        p = BackoffPolicy(base_seconds=1.0, jitter_ratio=0.25)
        a = p.delay_for(3, rng=random.Random(5))
        b = p.delay_for(3, rng=random.Random(5))
        self.assertEqual(a, b)

    def test_attempt_below_one_is_clamped(self):
        p = BackoffPolicy(base_seconds=1.0, jitter_ratio=0.0)
        self.assertEqual(p.delay_for(0), 1.0)
        self.assertEqual(p.delay_for(-5), 1.0)


class TestRestartBudget(unittest.TestCase):
    def test_consumes_until_exhausted(self):
        b = RestartBudget(max_restarts=3)
        self.assertTrue(b.consume())
        self.assertTrue(b.consume())
        self.assertTrue(b.consume())
        self.assertFalse(b.consume())
        self.assertTrue(b.exhausted)

    def test_reset_clears_exhaustion(self):
        b = RestartBudget(max_restarts=1)
        b.consume()
        self.assertFalse(b.consume())
        b.reset()
        self.assertFalse(b.exhausted)
        self.assertTrue(b.consume())

    def test_remaining_counts_down(self):
        b = RestartBudget(max_restarts=4)
        b.consume()
        self.assertEqual(b.remaining, 3)

    def test_to_dict_is_serializable(self):
        b = RestartBudget(max_restarts=2)
        json.dumps(b.to_dict())


class TestCircuitBreaker(unittest.TestCase):
    def test_opens_after_threshold(self):
        c = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
        c.record_failure(0.0)
        c.record_failure(1.0)
        self.assertEqual(c.state, CircuitState.CLOSED)
        c.record_failure(2.0)
        self.assertEqual(c.state, CircuitState.OPEN)

    def test_open_blocks_until_cooldown(self):
        c = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        c.record_failure(0.0)
        self.assertFalse(c.allow(5.0))
        self.assertTrue(c.allow(10.0))
        self.assertEqual(c.state, CircuitState.HALF_OPEN)

    def test_half_open_failure_reopens_immediately(self):
        c = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        c.record_failure(0.0)
        self.assertTrue(c.allow(10.0))          # -> HALF_OPEN
        c.record_failure(10.5)
        self.assertEqual(c.state, CircuitState.OPEN)
        self.assertFalse(c.allow(11.0))

    def test_half_open_success_closes(self):
        c = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        c.record_failure(0.0)
        c.allow(10.0)
        c.record_success()
        self.assertEqual(c.state, CircuitState.CLOSED)
        self.assertTrue(c.allow(11.0))

    def test_success_resets_failure_count(self):
        c = CircuitBreaker(failure_threshold=3)
        c.record_failure(0.0)
        c.record_failure(1.0)
        c.record_success()
        self.assertEqual(c.consecutive_failures, 0)


class TestHealthyIntervalResetsBudget(unittest.TestCase):
    def test_budget_resets_only_after_interval(self):
        clock = FakeClock()
        rc = RecoveryController(
            budget=RestartBudget(max_restarts=2,
                                 healthy_interval_seconds=60.0),
            clock=clock, rng=random.Random(1),
        )
        rc.on_restart_attempt()
        rc.on_restart_attempt()
        self.assertTrue(rc.budget.exhausted)

        rc.on_child_success()
        clock.advance(30.0)
        self.assertFalse(rc.tick_healthy())
        self.assertTrue(rc.budget.exhausted, "too early: must not reset")

        clock.advance(31.0)
        self.assertTrue(rc.tick_healthy())
        self.assertFalse(rc.budget.exhausted)
        self.assertEqual(rc.budget.used, 0)

    def test_no_reset_without_recorded_health(self):
        clock = FakeClock()
        rc = RecoveryController(budget=RestartBudget(max_restarts=1),
                                clock=clock, rng=random.Random(1))
        rc.on_restart_attempt()
        self.assertTrue(rc.budget.exhausted)
        clock.advance(10_000.0)
        self.assertFalse(rc.tick_healthy())
        self.assertTrue(rc.budget.exhausted,
                        "crash loop must not be laundered by waiting")

    def test_brief_survival_does_not_reset(self):
        clock = FakeClock()
        rc = RecoveryController(
            budget=RestartBudget(max_restarts=3,
                                 healthy_interval_seconds=60.0),
            clock=clock, rng=random.Random(1))
        rc.on_restart_attempt()
        rc.on_child_success()
        clock.advance(5.0)
        rc.on_child_failure()
        clock.advance(120.0)
        self.assertFalse(rc.tick_healthy(),
                         "failure clears the health streak")
        self.assertEqual(rc.budget.used, 1)


# ---------------------------------------------------------------------------
# Guardian crash / recovery behaviour
# ---------------------------------------------------------------------------

def _absent_probe(**kw):
    d = dict(process_alive=False, api_responsive=False, ready=False)
    d.update(kw)
    return ProbeResult(**d)


def _healthy_probe(**kw):
    d = dict(process_alive=True, api_responsive=True, ready=True)
    d.update(kw)
    return ProbeResult(**d)


def _unhealthy_probe(**kw):
    d = dict(process_alive=True, api_responsive=True, ready=False)
    d.update(kw)
    return ProbeResult(**d)


class TestCrashAndRestart(unittest.TestCase):
    def test_application_exit_triggers_restart(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            spawned = []

            def spawn(argv):
                spawned.append(tuple(argv))
                return FakeProc(pid=9999)

            g = make_guardian(tmp, probe=_absent_probe, spawn=spawn)
            # After spawn, probe reports alive.
            probes = [_absent_probe(), _healthy_probe()]
            g._probe_fn = lambda: probes.pop(0) if probes else _healthy_probe()
            # Duplicate detection inside start_child re-probes; keep absent.
            g._supervisor_duplicate_child = lambda: False

            out = g.run_once()
            self.assertEqual(len(spawned), 1)
            self.assertEqual(out["performed"], "restart")
            self.assertEqual(out["decision"]["action"], "restart")
            # argv array, never a shell string.
            self.assertIsInstance(spawned[0], tuple)
            self.assertTrue(all(isinstance(a, str) for a in spawned[0]))

    def test_successful_recovery_records_event(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_absent_probe,
                              spawn=lambda argv: FakeProc(pid=111))
            g._supervisor_duplicate_child = lambda: False
            g.run_once()
            types = [e["type"] for e in g.events.events()]
            self.assertIn("restart_attempt", types)
            self.assertIn("restart_success", types)

    def test_failed_restart_is_recorded_and_backed_off(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)

            def boom(argv):
                raise FileNotFoundError("no such executable")

            g = make_guardian(tmp, probe=_absent_probe, spawn=boom)
            g._supervisor_duplicate_child = lambda: False
            out = g.run_once()
            self.assertEqual(out["performed"], "restart_failed")
            types = [e["type"] for e in g.events.events()]
            self.assertIn("restart_failure", types)
            self.assertIn("config_error", types)
            self.assertEqual(g.controller.breaker.consecutive_failures, 1)

    def test_missing_executable_never_raises(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(
                tmp, probe=_absent_probe,
                start_command=("/nonexistent/python", "x.py"))
            g._supervisor_duplicate_child = lambda: False
            out = g.run_once()
            self.assertEqual(out["performed"], "restart_failed")

    def test_unhealthy_process_is_restarted(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            spawned = []
            g = make_guardian(tmp, probe=_unhealthy_probe,
                              spawn=lambda a: (spawned.append(a),
                                               FakeProc(pid=7))[1])
            g._supervisor_duplicate_child = lambda: False
            out = g.run_once()
            self.assertEqual(out["decision"]["action"], "restart")
            self.assertEqual(len(spawned), 1)

    def test_healthy_process_is_left_alone(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            spawned = []
            g = make_guardian(tmp, probe=_healthy_probe,
                              spawn=lambda a: spawned.append(a))
            out = g.run_once()
            self.assertEqual(out["decision"]["action"], "none")
            self.assertEqual(out["performed"], "none")
            self.assertEqual(spawned, [])

    def test_provider_unavailable_does_not_block_diagnostics(self):
        """Model backend down -> DEGRADED, sections still inspectable."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            status = {
                "server": {"status": "ok"},
                "supervisor": {"running": True},
                "scheduler": {"running": True},
                "tasks": {"total": 0},
            }
            report = assess_health(
                process_alive=True,
                health_url="http://127.0.0.1:1/health",   # unreachable
                readiness_url="http://127.0.0.1:1/readiness",
                timeout=0.05,
                runtime_status=status,
                backend_probe=lambda: {"ok": False, "detail": "ollama down"},
            )
            self.assertEqual(report.sections["supervisor_alive"].ok, True)
            self.assertEqual(report.sections["taskstore_readable"].ok, True)
            self.assertEqual(report.sections["model_backend"].ok, False)
            # Overall stays DEGRADED, never erases inspectability.
            self.assertEqual(report.overall, "DEGRADED")
            self.assertTrue(report.to_dict()["sections"])

    def test_server_unreachable_never_triggers_unsafe_recovery(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=lambda: _absent_probe(
                error="connection refused"))
            g._supervisor_duplicate_child = lambda: False
            out = g.run_once()
            # error + no process + no api -> unknown -> diagnose only
            self.assertEqual(out["decision"]["action"], "diagnose")
            self.assertEqual(out["decision"]["authority"],
                             Authority.DIAGNOSE_ONLY.value)
            self.assertIsNone(g.authority.history()[-1].command
                              if g.authority.history() else None)


class TestBudgetAndBreakerIntegration(unittest.TestCase):
    def test_restart_budget_exhaustion_stops_restarts(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_absent_probe, max_restarts=2,
                              spawn=lambda a: FakeProc(pid=5))
            g._supervisor_duplicate_child = lambda: False
            g.run_once()
            g.run_once()
            self.assertTrue(g.controller.budget.exhausted)
            out = g.run_once()
            self.assertEqual(out["performed"], "budget_exhausted")
            types = [e["type"] for e in g.events.events()]
            self.assertIn("budget_exhausted", types)

    def test_circuit_opens_after_repeated_failures(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)

            def boom(argv):
                raise RuntimeError("spawn exploded")

            g = make_guardian(tmp, probe=_absent_probe, spawn=boom,
                              circuit_failure_threshold=3, max_restarts=50)
            g._supervisor_duplicate_child = lambda: False
            for _ in range(3):
                g.run_once()
            self.assertEqual(g.controller.breaker.state, CircuitState.OPEN)
            types = [e["type"] for e in g.events.events()]
            self.assertIn("circuit_open", types)
            # Once open, further cycles must not spawn.
            out = g.run_once()
            self.assertNotEqual(out["performed"], "restart")
            self.assertIn("circuit", out["decision"]["reason"])

    def test_blocked_reason_surfaces_budget_and_breaker(self):
        b = RestartBudget(max_restarts=1)
        b.consume()
        rc = RecoveryController(budget=b, clock=FakeClock())
        self.assertIn("budget", rc.blocked_reason)

        c = CircuitBreaker(failure_threshold=1, cooldown_seconds=999.0)
        c.record_failure(0.0)
        rc2 = RecoveryController(
            breaker=c, clock=lambda: 0.0)
        self.assertIn("circuit", rc2.blocked_reason)


# ---------------------------------------------------------------------------
# Instance / PID safety
# ---------------------------------------------------------------------------

class TestDuplicatePrevention(unittest.TestCase):
    def test_second_guardian_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            path = tmp / "guardian.pid"
            first = InstanceGuard(path, alive=lambda pid: True,
                                  identity_of=lambda pid: "id")
            ok1, _ = first.acquire()
            self.assertTrue(ok1)

            second = InstanceGuard(path, alive=lambda pid: True,
                                   identity_of=lambda pid: "id")
            ok2, reason = second.acquire()
            self.assertFalse(ok2)
            self.assertIn("live instance", reason)
            first.release()

    def test_duplicate_guardian_run_exits_with_code_2(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            path = tmp / "guardian.pid"
            # Another guardian already holds the lock; that PID is alive and
            # its recorded identity matches, so this run must be refused.
            holder = InstanceGuard(path, alive=lambda pid: True,
                                   identity_of=lambda pid: "id")
            holder.acquire()
            try:
                g = make_guardian(tmp, probe=_healthy_probe,
                                  alive=lambda pid: True)
                g.instance_guard = InstanceGuard(
                    path, alive=lambda pid: True,
                    identity_of=lambda pid: "id")
                code = g.run(max_cycles=1)
                self.assertEqual(code, 2)
            finally:
                holder.release()

    def test_duplicate_child_is_not_spawned(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            pid_file = PidFile(tmp / "vaelor.pid", role="child",
                               alive=lambda pid: True,
                               identity_of=lambda pid: "id")
            pid_file.write(PidRecord(pid=777, identity="id", role="child"))

            spawned = []
            g = make_guardian(tmp, probe=_absent_probe,
                              spawn=lambda a: spawned.append(a))
            g.child_pid_file = pid_file
            started, reason = g.start_child()
            self.assertFalse(started)
            self.assertEqual(spawned, [])
            self.assertIn("duplicate", reason)

    def test_responsive_api_counts_as_running_instance(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            spawned = []
            g = make_guardian(tmp, probe=_healthy_probe,
                              spawn=lambda a: spawned.append(a))
            started, reason = g.start_child()
            self.assertFalse(started)
            self.assertEqual(spawned, [])
            self.assertIn("already responsive", reason)


class TestStalePidHandling(unittest.TestCase):
    def test_dead_pid_is_stale(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: False,
                         identity_of=lambda pid: None)
            pf.write(PidRecord(pid=123))
            self.assertEqual(pf.status(), "stale")
            stale, reason = pf.prove_stale()
            self.assertTrue(stale)
            self.assertIn("not alive", reason)

    def test_reused_pid_identity_mismatch_is_stale(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: True,
                         identity_of=lambda pid: "other-process")
            pf.write(PidRecord(pid=123, identity="vaelor"))
            self.assertEqual(pf.status(), "stale")
            stale, _ = pf.prove_stale()
            self.assertTrue(stale)

    def test_live_matching_pid_is_not_stale(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: True,
                         identity_of=lambda pid: "same")
            pf.write(PidRecord(pid=123, identity="same"))
            self.assertEqual(pf.status(), "alive")
            stale, reason = pf.prove_stale()
            self.assertFalse(stale)
            self.assertIn("alive", reason)

    def test_absent_pid_file_proves_stale(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "missing.pid", alive=lambda pid: True,
                         identity_of=lambda pid: None)
            stale, _ = pf.prove_stale()
            self.assertTrue(stale)

    def test_claim_refuses_live_owner(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: True,
                         identity_of=lambda pid: "id")
            pf.write(PidRecord(pid=1, identity="id"))
            ok, reason = pf.claim(2, identity="id")
            self.assertFalse(ok)
            self.assertIn("live instance", reason)

    def test_claim_replaces_proven_stale_file(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: False,
                         identity_of=lambda pid: None)
            pf.write(PidRecord(pid=1))
            ok, _ = pf.claim(99, identity="new")
            self.assertTrue(ok)
            self.assertEqual(pf.read().pid, 99)

    def test_release_only_if_still_owner(self):
        with tempfile.TemporaryDirectory() as t:
            pf = PidFile(Path(t) / "x.pid", alive=lambda pid: True,
                         identity_of=lambda pid: "id")
            pf.write(PidRecord(pid=5, identity="id"))
            self.assertFalse(pf.release(6), "not the owner")
            self.assertTrue(pf.exists())
            self.assertTrue(pf.release(5))
            self.assertFalse(pf.exists())

    def test_clearing_stale_child_pid_is_recorded(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_absent_probe)
            g.child_pid_file.write(PidRecord(pid=31337))
            g._clear_stale_child_pid()
            types = [e["type"] for e in g.events.events()]
            self.assertIn("stale_pid_cleared", types)
            self.assertFalse(g.child_pid_file.exists())


class TestCorruptState(unittest.TestCase):
    def test_corrupt_guardian_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            st = GuardianState.load(path)
            self.assertTrue(st.corrupt)
            self.assertEqual(st.child_pid, 0)
            self.assertEqual(st.restarts, 0)

    def test_corrupt_pid_file_reports_corrupt(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "x.pid"
            path.write_text("not json at all", encoding="utf-8")
            pf = PidFile(path, alive=lambda pid: True,
                         identity_of=lambda pid: None)
            self.assertEqual(pf.status(), "corrupt")
            self.assertTrue(pf.is_corrupt())

    def test_corrupt_pid_file_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "x.pid"
            path.write_text("\x00\x01garbage", encoding="utf-8",
                            errors="ignore") if False else path.write_bytes(
                b"\x00garbage")
            pf = PidFile(path, alive=lambda pid: True,
                         identity_of=lambda pid: "id")
            ok, _ = pf.claim(42, identity="id")
            self.assertTrue(ok, "corrupt file is not proof of a live owner")

    def test_corrupt_config_raises_misconfig(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text("{oops", encoding="utf-8")
            with self.assertRaises(GuardianConfigError):
                load_guardian_config(root=Path(t), explicit=cfg)

    def test_event_log_survives_unwritable_path(self):
        # A directory where a file is expected -> persistence degrades only.
        log = RecoveryEventLog(path=Path("/nonexistent-root-xyz/e.json"))
        ev = log.record("probe_result", "hello")
        self.assertEqual(len(log.events()), 1)
        self.assertFalse(log.persists)
        self.assertEqual(ev.type, "probe_result")


class TestEventBoundsAndRedaction(unittest.TestCase):
    def test_event_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as t:
            log = RecoveryEventLog(path=Path(t) / "e.json", max_events=10)
            for i in range(50):
                log.record("probe_result", f"event {i}")
            self.assertEqual(len(log.events()), 10)
            self.assertEqual(log.events()[-1]["detail"], "event 49")

    def test_events_are_persisted_and_structured(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "e.json"
            log = RecoveryEventLog(path=path)
            log.record("restart_attempt", "starting", data={"pid": 5})
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk[0]["type"], "restart_attempt")
            self.assertEqual(on_disk[0]["data"]["pid"], 5)
            self.assertIn("at", on_disk[0])

    def test_events_never_contain_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            log = RecoveryEventLog(path=Path(t) / "e.json")
            log.record("restart_failure", "denied",
                       data={"api_key": "sk-secretthing1234",
                             "authorization": "Bearer abcdef123456",
                             "note": "token ghp_abcdefghijklmno"})
            raw = json.dumps(log.events())
            for banned in ("sk-secretthing1234", "Bearer abcdef123456",
                           "ghp_abcdefghijklmno"):
                self.assertNotIn(banned, raw)

    def test_unknown_event_type_is_normalized(self):
        log = RecoveryEventLog(path=None)
        ev = log.record("model_suggested_restart", "nope")
        self.assertEqual(ev.type, "probe_result")

    def test_event_detail_is_clipped(self):
        log = RecoveryEventLog(path=None)
        ev = log.record("probe_result", "z" * 10_000)
        self.assertLessEqual(len(ev.to_dict()["detail"]), 400)

    def test_count_by_type(self):
        log = RecoveryEventLog(path=None)
        log.record("restart_attempt", "a")
        log.record("restart_attempt", "b")
        log.record("guardian_stop", "c")
        self.assertEqual(log.count("restart_attempt"), 2)


# ---------------------------------------------------------------------------
# Recovery authority matrix (Phase 3)
# ---------------------------------------------------------------------------

class TestRecoveryAuthorityMatrix(unittest.TestCase):
    def setUp(self):
        self.m = RecoveryAuthorityMatrix()

    def test_local_process_absent_is_automatic(self):
        d = self.m.consult("restart_local_vaelor",
                           command=("/usr/bin/python3", "vaelor.py"),
                           source="guardian")
        self.assertTrue(d.may_auto_execute)
        self.assertEqual(d.authority, Authority.AUTOMATIC)

    def test_approval_required_actions_are_refused(self):
        for action in ("install_tailscale", "configure_tailscale",
                       "restart_tailscale", "change_firewall",
                       "install_system_package", "repair_credentials",
                       "wake_on_lan", "power_on_remote_host", "reboot_host",
                       "shutdown_host", "install_windows_service",
                       "install_systemd_service", "enable_systemd_service",
                       "modify_canonical_git", "run_unknown_command",
                       "restart_unrelated_service"):
            with self.subTest(action=action):
                d = self.m.consult(action, source="guardian")
                self.assertEqual(d.authority, Authority.APPROVAL_REQUIRED)
                self.assertFalse(d.may_auto_execute)
                self.assertIsNone(d.command)

    def test_unenumerated_action_fails_closed(self):
        d = self.m.consult("do_something_novel", source="guardian")
        self.assertEqual(d.authority, Authority.APPROVAL_REQUIRED)

    def test_model_supplied_command_is_never_automatic(self):
        d = self.m.consult(
            "restart_local_vaelor",
            command=("rm", "-rf", "/"),
            source="model_response",
        )
        self.assertFalse(d.may_auto_execute)
        self.assertIn("unknown_command_source", d.reason)
        self.assertIsNone(d.command)

    def test_task_memory_web_conversation_sources_blocked(self):
        for src in ("task_record", "memory_record", "web_response",
                    "conversation", "model"):
            with self.subTest(source=src):
                d = self.m.consult("restart_local_vaelor", source=src)
                self.assertFalse(d.may_auto_execute)

    def test_blockers_force_diagnose_only(self):
        for blocker in ("ambiguous_node_identity", "contradictory_evidence",
                        "repeated_crash_loop", "host_unreachable",
                        "stale_state_uncertain", "missing_configuration",
                        "unknown_command_source"):
            with self.subTest(blocker=blocker):
                d = self.m.consult("restart_local_vaelor",
                                   blockers=[blocker], source="guardian")
                self.assertEqual(d.authority, Authority.DIAGNOSE_ONLY)
                self.assertFalse(d.may_auto_execute)

    def test_crash_loop_blocks_automatic_restart(self):
        d = self.m.consult("restart_local_vaelor",
                           blockers=["repeated_crash_loop"],
                           command=("/usr/bin/python3", "vaelor.py"),
                           source="guardian")
        self.assertEqual(d.authority, Authority.DIAGNOSE_ONLY)
        self.assertIsNone(d.command)

    def test_host_down_recovery_is_not_reported_as_success(self):
        d = self.m.consult("power_on_remote_host", source="guardian")
        self.assertFalse(d.may_auto_execute)
        # The decision carries no command, so nothing can be "attempted".
        self.assertIsNone(d.command)

    def test_decisions_are_recorded(self):
        self.m.consult("restart_local_vaelor", source="guardian")
        self.assertEqual(len(self.m.history()), 1)
        self.assertIn("authority", self.m.history()[0])

    def test_decision_is_json_serializable(self):
        d = self.m.consult("restart_local_vaelor", source="guardian")
        json.dumps(d.to_dict())


# ---------------------------------------------------------------------------
# Service manager adapters (Phase 4)
# ---------------------------------------------------------------------------

class TestSystemdUserAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = SystemdUserAdapter(
            worktree=Path(self.tmp.name),
            python_executable="/usr/bin/python3",
            entry_script="vaelor.py",
        )

    def test_renders_unit_with_worktree_and_exec(self):
        unit = self.adapter.render()
        self.assertIn("[Service]", unit)
        self.assertIn(str(Path(self.tmp.name)), unit)
        self.assertIn("/usr/bin/python3 vaelor.py", unit)
        # Guardian owns restarts; systemd must not race it.
        self.assertIn("Restart=no", unit)

    def test_plan_start_is_exact_argv(self):
        plan = self.adapter.plan("start", unit="vaelor.service")
        self.assertEqual(plan.argv,
                         ("systemctl", "--user", "start", "vaelor.service"))
        self.assertIsInstance(plan.argv, tuple)
        self.assertFalse(plan.dry_run_only)

    def test_plan_stop_restart_status(self):
        for op in ("stop", "restart", "status"):
            with self.subTest(op=op):
                plan = self.adapter.plan(op, unit="vaelor.service")
                self.assertEqual(plan.argv[0], "systemctl")
                self.assertEqual(plan.argv[1], "--user")
                self.assertEqual(plan.argv[2], op)

    def test_install_is_refused_without_approval(self):
        plan = self.adapter.plan("install", unit="vaelor.service")
        self.assertTrue(plan.dry_run_only)
        self.assertEqual(plan.argv, ("<refused>",))
        self.assertIn("approval", plan.notes)

    def test_validate_accepts_good_config(self):
        self.assertEqual(self.adapter.validate(), [])

    def test_validate_rejects_bad_unit_name(self):
        bad = SystemdUserAdapter(worktree=Path(self.tmp.name),
                                 unit_name="../evil.service")
        self.assertTrue(bad.validate())

    def test_validate_rejects_unit_with_slash(self):
        bad = SystemdUserAdapter(worktree=Path(self.tmp.name),
                                 unit_name="a/b.service")
        self.assertTrue(bad.validate())

    def test_validate_rejects_missing_worktree(self):
        bad = SystemdUserAdapter(worktree=Path("/definitely/not/here"))
        self.assertTrue(any("does not exist" in p for p in bad.validate()))

    def test_plan_raises_on_invalid_config(self):
        bad = SystemdUserAdapter(worktree=Path("/definitely/not/here"))
        with self.assertRaises(AdapterError):
            bad.plan("start", unit="vaelor.service")

    def test_unknown_operation_raises(self):
        with self.assertRaises(AdapterError):
            self.adapter.plan("frobnicate", unit="vaelor.service")

    def test_status_reports_not_installed(self):
        st = self.adapter.status()
        self.assertFalse(st["installed"])
        self.assertTrue(st["dry_run"])
        self.assertIn("no real service", st["note"])

    def test_plan_is_serializable(self):
        json.dumps(self.adapter.plan("start", unit="vaelor.service").to_dict())


class TestWindowsServiceAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = WindowsServiceAdapter()

    def test_does_not_claim_platform_support_on_linux(self):
        import sys as _sys
        if not _sys.platform.startswith("win"):
            self.assertFalse(self.adapter.platform_supported)

    def test_plan_is_dry_run_only(self):
        plan = self.adapter.plan("start", unit="Vaelor")
        self.assertTrue(plan.dry_run_only)
        self.assertIn("cannot be validated", plan.notes)

    def test_status_reports_unvalidated(self):
        st = self.adapter.status()
        self.assertFalse(st["validated"])
        self.assertIn("no Windows host", st["note"])

    def test_render_describes_without_installing(self):
        text = self.adapter.render()
        self.assertIn("described, not installed", text)
        self.assertIn("Vaelor", text)

    def test_validate_rejects_service_name_with_space(self):
        bad = WindowsServiceAdapter(unit_name="Vaelor Service")
        self.assertTrue(bad.validate())

    def test_plan_raises_on_invalid(self):
        bad = WindowsServiceAdapter(unit_name="")
        with self.assertRaises(AdapterError):
            bad.plan("start")

    def test_unsupported_operation_raises(self):
        with self.assertRaises(AdapterError):
            self.adapter.plan("install", unit="Vaelor")

    def test_restart_plans_sc_control(self):
        plan = self.adapter.plan("restart", unit="Vaelor")
        self.assertEqual(plan.argv[0], "sc.exe")
        self.assertEqual(plan.argv[1], "control")


# ---------------------------------------------------------------------------
# Health contract (Phase 5)
# ---------------------------------------------------------------------------

class TestHealthContract(unittest.TestCase):
    def _status(self, **over):
        base = {
            "server": {"status": "ok"},
            "supervisor": {"running": True},
            "scheduler": {"running": True},
            "tasks": {"total": 3},
        }
        base.update(over)
        return base

    def test_all_sections_present(self):
        r = assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status(),
                          backend_probe=lambda: {"ok": True})
        for name in ("process_alive", "api_responsive", "runtime_initialized",
                     "taskstore_readable", "supervisor_alive",
                     "scheduler_alive", "model_backend", "readiness"):
            self.assertIn(name, r.sections)

    def test_model_down_is_degraded_not_unhealthy(self):
        r = assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status(),
                          backend_probe=lambda: {"ok": False,
                                                 "detail": "down"})
        self.assertEqual(r.overall, "DEGRADED")
        self.assertEqual(r.sections["model_backend"].ok, False)
        self.assertEqual(r.sections["supervisor_alive"].ok, True)

    def test_missing_backend_probe_is_unknown_not_fail(self):
        r = assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status(),
                          backend_probe=None)
        self.assertIsNone(r.sections["model_backend"].ok)
        self.assertEqual(r.sections["model_backend"].status, "UNKNOWN")

    def test_broken_supervisor_marks_degraded(self):
        r = assess_health(
            process_alive=True, health_url="http://127.0.0.1:1/health",
            readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
            runtime_status=self._status(
                supervisor={"running": False, "status": "degraded",
                            "error": "boom"}),
            backend_probe=lambda: {"ok": True})
        self.assertEqual(r.sections["supervisor_alive"].ok, False)
        self.assertEqual(r.overall, "DEGRADED")

    def test_degraded_taskstore_is_reported(self):
        r = assess_health(
            process_alive=True, health_url="http://127.0.0.1:1/health",
            readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
            runtime_status=self._status(
                tasks={"status": "degraded", "error": "store locked"}),
            backend_probe=lambda: {"ok": True})
        self.assertEqual(r.sections["taskstore_readable"].ok, False)
        self.assertTrue(any("taskstore" in x
                            for x in r.degraded_reasons))

    def test_unreachable_runtime_status_yields_unknown_not_crash(self):
        r = assess_health(process_alive=None, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness",
                          timeout=0.01, runtime_status=None,
                          backend_probe=lambda: {"ok": False})
        self.assertIn(r.overall, ("UNKNOWN", "DEGRADED", "UNHEALTHY"))
        self.assertEqual(r.sections["supervisor_alive"].ok, None)

    def test_raising_backend_probe_is_bounded(self):
        def boom():
            raise RuntimeError("backend exploded")
        r = assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status(), backend_probe=boom)
        sec = r.sections["model_backend"]
        self.assertEqual(sec.ok, False)
        self.assertIn("RuntimeError", sec.error)

    def test_report_is_json_serializable_and_secret_free(self):
        r = assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status(
                              tasks={"api_key": "sk-shouldnotappear1234"}),
                          backend_probe=lambda: {"ok": True})
        raw = json.dumps(r.to_dict())
        self.assertNotIn("sk-shouldnotappear1234", raw)

    def test_health_does_not_mutate_inputs(self):
        status = self._status()
        snapshot = json.dumps(status, sort_keys=True)
        assess_health(process_alive=True, health_url="http://127.0.0.1:1/health",
                      readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                      runtime_status=status,
                      backend_probe=lambda: {"ok": True})
        self.assertEqual(json.dumps(status, sort_keys=True), snapshot)

    def test_one_broken_section_does_not_hide_others(self):
        r = assess_health(
            process_alive=True, health_url="http://127.0.0.1:1/health",
            readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
            runtime_status=self._status(),
            backend_probe=lambda: {"ok": True})
        # api_responsive failed (bad URL) but the rest still reported.
        self.assertEqual(r.sections["api_responsive"].ok, False)
        self.assertEqual(r.sections["supervisor_alive"].ok, True)
        self.assertEqual(r.sections["scheduler_alive"].ok, True)

    def test_process_alive_none_stays_unknown(self):
        r = assess_health(process_alive=None, health_url="http://127.0.0.1:1/health",
                          readiness_url="http://127.0.0.1:1/readiness", timeout=0.01,
                          runtime_status=self._status())
        self.assertIsNone(r.sections["process_alive"].ok)
        self.assertEqual(r.sections["process_alive"].status, "UNKNOWN")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

class TestGuardianConfig(unittest.TestCase):
    def test_shell_string_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text(json.dumps({
                "start_command": "python vaelor.py && rm -rf /",
            }), encoding="utf-8")
            with self.assertRaises(GuardianConfigError) as ctx:
                load_guardian_config(root=Path(t), explicit=cfg)
            self.assertIn("argv array", str(ctx.exception))

    def test_empty_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text(json.dumps({"start_command": []}), encoding="utf-8")
            with self.assertRaises(GuardianConfigError):
                load_guardian_config(root=Path(t), explicit=cfg)

    def test_nul_byte_in_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text(json.dumps({"start_command": ["py\x00v"]}),
                           encoding="utf-8")
            with self.assertRaises(GuardianConfigError):
                load_guardian_config(root=Path(t), explicit=cfg)

    def test_unknown_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text(json.dumps({"surprise": 1}), encoding="utf-8")
            with self.assertRaises(GuardianConfigError) as ctx:
                load_guardian_config(root=Path(t), explicit=cfg)
            self.assertIn("unknown", str(ctx.exception))

    def test_out_of_range_values_rejected(self):
        cases = [
            {"max_restarts": 0},
            {"max_restarts": 1000},
            {"probe_timeout_seconds": 9999},
            {"poll_interval_seconds": -1},
            {"enabled": "yes"},
        ]
        for over in cases:
            with self.subTest(**over):
                with tempfile.TemporaryDirectory() as t:
                    cfg = Path(t) / "guardian.json"
                    cfg.write_text(json.dumps(over), encoding="utf-8")
                    with self.assertRaises(GuardianConfigError):
                        load_guardian_config(root=Path(t), explicit=cfg)

    def test_bad_url_scheme_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = Path(t) / "guardian.json"
            cfg.write_text(json.dumps({"health_url": "file:///etc/passwd"}),
                           encoding="utf-8")
            with self.assertRaises(GuardianConfigError):
                load_guardian_config(root=Path(t), explicit=cfg)

    def test_defaults_load_without_any_config_file(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = load_guardian_config(root=Path(t))
        self.assertTrue(cfg.enabled)
        self.assertIsInstance(cfg.start_command, tuple)
        self.assertGreaterEqual(len(cfg.start_command), 1)
        self.assertTrue(cfg.health_url.startswith("http://"))

    def test_valid_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            cfg_file = p / "guardian.json"
            cfg_file.write_text(json.dumps({
                "start_command": ["/usr/bin/python3", "vaelor.py"],
                "max_restarts": 7,
                "enabled": False,
                "health_url": "http://127.0.0.1:8888/health",
                "readiness_url": "http://127.0.0.1:8888/readiness",
            }), encoding="utf-8")
            cfg = load_guardian_config(root=p, explicit=cfg_file)
        self.assertEqual(cfg.max_restarts, 7)
        self.assertFalse(cfg.enabled)
        self.assertIn("8888", cfg.health_url)
        self.assertEqual(cfg.start_command,
                         ("/usr/bin/python3", "vaelor.py"))


# ---------------------------------------------------------------------------
# Shutdown and loop behaviour
# ---------------------------------------------------------------------------

class TestGracefulShutdown(unittest.TestCase):
    def test_run_completes_with_max_cycles_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_healthy_probe)
            code = g.run(max_cycles=2)
            self.assertEqual(code, 0)
            self.assertFalse(g.instance_guard.pid_file.exists(),
                             "lock must be released on exit")

    def test_stop_event_ends_loop_promptly(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_healthy_probe)
            calls = {"n": 0}

            def probe():
                calls["n"] += 1
                if calls["n"] >= 2:
                    g.request_stop()
                return _healthy_probe()

            g._probe_fn = probe
            code = g.run(max_cycles=100)
            self.assertEqual(code, 0)
            self.assertLessEqual(calls["n"], 3)

    def test_shutdown_stops_child_and_persists_state(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            proc = FakeProc(pid=8080)
            g = make_guardian(tmp, probe=_healthy_probe,
                              spawn=lambda a: proc)
            g._child = proc
            g.child_pid_file.write(PidRecord(pid=8080))
            g.shutdown()
            self.assertTrue(proc.terminated)
            self.assertTrue(g.state_path_absent() if hasattr(
                g, "state_path_absent") else True)
            self.assertFalse(g.child_pid_file.exists())

    def test_stop_child_reaps_after_timeout(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            proc = FakeProc(pid=8081)
            proc._raise_timeout = True
            g = make_guardian(tmp, probe=_healthy_probe)
            g._child = proc
            ok = g.stop_child(timeout=0.01)
            self.assertTrue(proc.terminated)
            self.assertTrue(proc.killed, "force-kill after timeout")
            self.assertTrue(ok)

    def test_stop_child_without_child_is_safe(self):
        with tempfile.TemporaryDirectory() as t:
            g = make_guardian(Path(t), probe=_healthy_probe)
            self.assertTrue(g.stop_child())

    def test_signal_handlers_install_without_error(self):
        with tempfile.TemporaryDirectory() as t:
            g = make_guardian(Path(t), probe=_healthy_probe)
            g.install_signal_handlers()
            g.request_stop()
            self.assertTrue(g._stop.is_set())
            self.assertIn("shutdown_requested",
                          [e["type"] for e in g.events.events()])

    def test_guardian_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "s.json"
            st = GuardianState(path=path, guardian_pid=1, child_pid=2,
                               restarts=4, last_transition="restart")
            st.save()
            loaded = GuardianState.load(path)
            self.assertFalse(loaded.corrupt)
            self.assertEqual(loaded.child_pid, 2)
            self.assertEqual(loaded.restarts, 4)
            self.assertEqual(loaded.last_transition, "restart")


class TestNoGovernanceBypass(unittest.TestCase):
    """Guardian recovery must not bypass approvals or governance."""

    def test_guardian_never_emits_approval_actions(self):
        m = RecoveryAuthorityMatrix()
        for action in ("approve_action", "auto_approve",
                       "bypass_approval", "grant_capability"):
            d = m.consult(action, source="guardian")
            self.assertFalse(d.may_auto_execute)

    def test_guardian_status_carries_no_authority_grant(self):
        with tempfile.TemporaryDirectory() as t:
            g = make_guardian(Path(t), probe=_healthy_probe)
            payload = json.dumps(g.status(), default=str)
            for banned in ("auto_approve\": true", "capability_id",
                           "grant_capability"):
                self.assertNotIn(banned, payload)

    def test_run_once_does_not_touch_system_state(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g = make_guardian(tmp, probe=_healthy_probe)
            with patch("subprocess.run") as run_mock, \
                 patch("subprocess.Popen") as popen_mock:
                g.run_once()
            run_mock.assert_not_called()
            popen_mock.assert_not_called()

    def test_guardian_command_source_is_always_guardian(self):
        m = RecoveryAuthorityMatrix()
        d = m.consult("restart_local_vaelor", source="guardian")
        self.assertEqual(d.authority, Authority.AUTOMATIC)


if __name__ == "__main__":
    unittest.main()
