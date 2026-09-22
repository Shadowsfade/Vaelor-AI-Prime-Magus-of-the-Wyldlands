"""R0.2 node identity and observation semantics regression tests.

Covers: local/remote evidence separation, contradictory probes, missing
configuration, partial probe failure, timeouts, and secret-free evidence.

All tests are read-only and touch no real OS service, Tailscale config,
firewall, or power state.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from core.infra.condition import (
    NodeCondition,
    bounded_error,
    condition_to_state,
    redact,
    resolve_condition,
)
from core.infra.node_config import (
    NodeConfigError,
    NodeIdentity,
    NodeRegistry,
    load_node_registry,
)
from core.infra.observation import build_local_observation
from core.infra.status import NodeObservation, NodeState, ProbeEvidence


def _reg(observer: str = "legiongo", target: str = "legiongo",
         extra: dict = None) -> NodeRegistry:
    nodes = {
        observer: NodeIdentity(name=observer, hostname=observer, is_local=True),
    }
    for name, spec in (extra or {}).items():
        nodes[name] = NodeIdentity(
            name=name,
            hostname=spec.get("hostname", name),
            tailscale_ip=spec.get("tailscale_ip"),
            is_local=False,
        )
    return NodeRegistry(observer=nodes[observer], nodes=nodes,
                        default_target=target, source="test")


class TestLocalRemoteSeparation(unittest.TestCase):
    """Local process/model evidence must never reach a remote target."""

    def test_remote_target_withholds_local_probes(self):
        reg = _reg(observer="legiongo", extra={
            "skyai": {"hostname": "skyai", "tailscale_ip": "100.64.0.1"},
        })
        with patch("core.infra.probes.run_all_local_probes") as mocked:
            scoped = build_local_observation(reg, target_name="skyai")
            # Local probes must not even run when the target is remote.
            mocked.assert_not_called()

        self.assertEqual(scoped.scope, "remote")
        self.assertEqual(scoped.node, "skyai")
        self.assertEqual(scoped.condition, NodeCondition.UNKNOWN)
        self.assertIsNone(scoped.observation.host_reachable)
        self.assertIsNone(scoped.observation.vaelor_health)
        self.assertIsNone(scoped.observation.model_backend)
        # Evidence present, but explicitly marked withheld.
        self.assertTrue(scoped.observation.evidence)
        raw = scoped.observation.evidence[0].raw or {}
        self.assertEqual(raw.get("evidence_scope"), "withheld")

    def test_remote_summary_never_asserts_down(self):
        reg = _reg(observer="legiongo", extra={"skyai": {"hostname": "skyai"}})
        scoped = build_local_observation(reg, target_name="skyai")
        self.assertNotIn("DOWN", scoped.condition.value)
        self.assertEqual(scoped.state, NodeState.UNKNOWN)

    def test_local_target_keeps_observer_and_target_distinct(self):
        reg = _reg(observer="legiongo")
        with patch("core.infra.probes.run_all_local_probes", return_value=[]):
            scoped = build_local_observation(reg)
        self.assertEqual(scoped.scope, "local")
        self.assertEqual(scoped.observer.name, "legiongo")
        self.assertEqual(scoped.target.name, "legiongo")
        self.assertEqual(scoped.observation.observer_node, "legiongo")
        self.assertEqual(scoped.observation.node, "legiongo")

    def test_evidence_records_both_observer_and_target(self):
        ev = ProbeEvidence(probe="host_uptime", observer_node="legiongo",
                           target_node="legiongo", status="ok")
        d = ev.to_dict()
        self.assertEqual(d["observer_node"], "legiongo")
        self.assertEqual(d["target_node"], "legiongo")
        self.assertIn("observed_at", d)

    def test_observation_dict_exposes_identity_fields(self):
        reg = _reg(observer="legiongo", extra={"skyai": {"hostname": "sky-ai"}})
        scoped = build_local_observation(reg, target_name="skyai")
        d = scoped.to_dict()
        for key in ("condition", "scope", "configured_hostname", "observer",
                    "target", "explanation", "contradictions", "timeout_ms"):
            self.assertIn(key, d)
        self.assertEqual(d["configured_hostname"], "sky-ai")
        self.assertEqual(d["observer"]["name"], "legiongo")
        self.assertEqual(d["target"]["name"], "skyai")


class TestContradictoryEvidence(unittest.TestCase):
    """Contradictions resolve to UNKNOWN/DEGRADED with an explanation."""

    def test_host_down_but_health_ok_is_unknown(self):
        cond, expl = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=False, vaelor_health=True,
            vaelor_process_alive=None, model_backend=True,
            contradictions=["host unreachable but health endpoint answered"],
        )
        self.assertEqual(cond, NodeCondition.UNKNOWN)
        self.assertIn("contradictory", expl)
        self.assertIn("health endpoint", expl)

    def test_contradiction_never_becomes_confident_down(self):
        cond, _ = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=False, vaelor_health=True,
            vaelor_process_alive=None, model_backend=None,
            contradictions=["something inconsistent"],
        )
        self.assertNotIn(cond, {
            NodeCondition.HOST_UNREACHABLE,
            NodeCondition.NETWORK_PATH_UNAVAILABLE,
            NodeCondition.VAELOR_PROCESS_DOWN,
        })

    def test_misconfiguration_fails_closed(self):
        cond, expl = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=True, vaelor_health=True,
            vaelor_process_alive=True, model_backend=True,
            misconfigured="no target configured",
        )
        self.assertEqual(cond, NodeCondition.MISCONFIGURED)
        self.assertIn("misconfigured", expl)

    def test_conditions_map_to_coarse_states(self):
        self.assertEqual(condition_to_state(NodeCondition.HEALTHY),
                         NodeState.HEALTHY)
        self.assertEqual(condition_to_state(NodeCondition.MISCONFIGURED),
                         NodeState.UNKNOWN)
        self.assertEqual(condition_to_state(NodeCondition.VAELOR_PROCESS_DOWN),
                         NodeState.DEGRADED)
        self.assertEqual(condition_to_state(NodeCondition.HOST_UNREACHABLE),
                         NodeState.UNREACHABLE)
        self.assertEqual(
            condition_to_state(NodeCondition.NETWORK_PATH_UNAVAILABLE),
            NodeState.UNREACHABLE)


class TestScopeDistinctions(unittest.TestCase):
    """HOST_UNREACHABLE vs NETWORK_PATH_UNAVAILABLE vs service states."""

    def test_local_host_down_is_host_unreachable(self):
        cond, _ = resolve_condition(
            scope="local", observer="legiongo", target="legiongo",
            host_reachable=False, vaelor_health=None,
            vaelor_process_alive=None, model_backend=None)
        self.assertEqual(cond, NodeCondition.HOST_UNREACHABLE)

    def test_remote_unreachable_is_network_path(self):
        cond, expl = resolve_condition(
            scope="remote", observer="legiongo", target="skyai",
            host_reachable=False, vaelor_health=None,
            vaelor_process_alive=None, model_backend=None)
        self.assertEqual(cond, NodeCondition.NETWORK_PATH_UNAVAILABLE)
        self.assertIn("cannot be distinguished", expl)

    def test_process_down_distinct_from_unhealthy(self):
        down, _ = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=True, vaelor_health=False,
            vaelor_process_alive=False, model_backend=True)
        unhealth, _ = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=True, vaelor_health=False,
            vaelor_process_alive=True, model_backend=True)
        self.assertEqual(down, NodeCondition.VAELOR_PROCESS_DOWN)
        self.assertEqual(unhealth, NodeCondition.VAELOR_UNHEALTHY)

    def test_model_backend_down_is_degraded_not_dead(self):
        cond, expl = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=True, vaelor_health=True,
            vaelor_process_alive=True, model_backend=False)
        self.assertEqual(cond, NodeCondition.MODEL_BACKEND_DOWN)
        self.assertIn("remain usable", expl)

    def test_no_evidence_is_unknown(self):
        cond, _ = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=None, vaelor_health=None,
            vaelor_process_alive=None, model_backend=None)
        self.assertEqual(cond, NodeCondition.UNKNOWN)


class TestMissingConfiguration(unittest.TestCase):
    """Absent config falls back safely; invalid config fails closed."""

    def test_absent_config_uses_builtin_local_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = load_node_registry(root=Path(tmp))
        self.assertEqual(reg.source, "builtin")
        self.assertTrue(reg.observer.is_local)
        self.assertEqual(reg.default_target, reg.observer.name)

    def test_invalid_json_raises_misconfig(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config" / "nodes.json"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("{not json", encoding="utf-8")
            with self.assertRaises(NodeConfigError):
                load_node_registry(root=Path(tmp))

    def test_missing_observer_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config" / "nodes.json"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps({
                "observer": "ghost",
                "nodes": {"legiongo": {"hostname": "legiongo"}},
            }), encoding="utf-8")
            with self.assertRaises(NodeConfigError):
                load_node_registry(root=Path(tmp))

    def test_unknown_default_target_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config" / "nodes.json"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps({
                "observer": "legiongo",
                "default_target": "nowhere",
                "nodes": {"legiongo": {"hostname": "legiongo"}},
            }), encoding="utf-8")
            with self.assertRaises(NodeConfigError):
                load_node_registry(root=Path(tmp))

    def test_unknown_target_request_is_misconfigured(self):
        reg = _reg(observer="legiongo")
        scoped = build_local_observation(reg, target_name="not-a-node")
        self.assertEqual(scoped.condition, NodeCondition.MISCONFIGURED)
        self.assertEqual(scoped.state, NodeState.UNKNOWN)

    def test_valid_config_roundtrips_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config" / "nodes.json"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps({
                "observer": "legiongo",
                "default_target": "skyai",
                "nodes": {
                    "legiongo": {"hostname": "legiongo", "role": "operator"},
                    "skyai": {"hostname": "skyai",
                              "tailscale_ip": "100.64.0.9",
                              "role": "host"},
                },
            }), encoding="utf-8")
            reg = load_node_registry(root=Path(tmp))
        self.assertEqual(reg.observer.name, "legiongo")
        target = reg.target("skyai")
        self.assertEqual(target.tailscale_ip, "100.64.0.9")
        self.assertFalse(target.is_local)
        self.assertEqual(reg.default_target, "skyai")


class TestPartialProbeFailure(unittest.TestCase):
    """A failed optional probe must not collapse the whole host to DOWN."""

    def test_required_none_stays_unknown(self):
        obs = NodeObservation(
            node="n", observer_node="n", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True,
            vaelor_health=None, ssh_service=True)
        from core.infra.classifier import NodeExpectations, classify_observation
        state = classify_observation(obs, NodeExpectations.for_node("skyai"))
        self.assertEqual(state, NodeState.UNKNOWN)

    def test_model_backend_failure_keeps_host_reachable(self):
        cond, _ = resolve_condition(
            scope="local", observer="n", target="n",
            host_reachable=True, vaelor_health=None,
            vaelor_process_alive=None, model_backend=False)
        self.assertNotEqual(cond, NodeCondition.HOST_UNREACHABLE)
        self.assertNotEqual(cond, NodeCondition.NETWORK_PATH_UNAVAILABLE)

    def test_health_ok_without_listener_is_contradictory(self):
        from core.infra.observation import _contradictions
        obs = NodeObservation(node="n", observer_node="n",
                              state=NodeState.UNKNOWN,
                              host_reachable=True, vaelor_health=True)
        found = _contradictions(obs)
        self.assertTrue(any("no listener" in c for c in found))

    def test_partial_evidence_yields_degraded_or_unknown_not_down(self):
        for kwargs in (
            dict(host_reachable=True, vaelor_health=None,
                 vaelor_process_alive=None, model_backend=False),
            dict(host_reachable=True, vaelor_health=True,
                 vaelor_process_alive=None, model_backend=None),
        ):
            cond, _ = resolve_condition(scope="local", observer="n",
                                        target="n", **kwargs)
            self.assertNotIn(cond, {
                NodeCondition.HOST_UNREACHABLE,
                NodeCondition.NETWORK_PATH_UNAVAILABLE,
            })


class TestTimeoutsAndBoundedEvidence(unittest.TestCase):
    """Timeouts are bounded and evidence stays within limits."""

    def test_timeout_ms_present_in_observation_dict(self):
        reg = _reg()
        with patch("core.infra.probes.run_all_local_probes", return_value=[]):
            scoped = build_local_observation(reg, timeout_ms=2000.0)
        self.assertEqual(scoped.to_dict()["timeout_ms"], 2000.0)

    def test_probe_latency_is_recorded(self):
        ev = ProbeEvidence(probe="p", observer_node="n", target_node="n",
                           status="ok", latency_ms=12.5)
        self.assertEqual(ev.to_dict()["latency_ms"], 12.5)

    def test_bounded_error_truncates(self):
        msg = bounded_error(RuntimeError("x" * 5000), limit=100)
        self.assertLessEqual(len(msg), 100)

    def test_bounded_error_keeps_exception_type(self):
        msg = bounded_error(ValueError("bad thing"))
        self.assertIn("ValueError", msg)
        self.assertIn("bad thing", msg)

    def test_long_detail_is_truncated_in_redact(self):
        out = redact({"detail": "y" * 4000})
        self.assertLess(len(out["detail"]), 4000)
        self.assertIn("truncated", out["detail"])


class TestSecretFreeEvidence(unittest.TestCase):
    """Evidence and structured errors never carry credentials."""

    def test_secret_keys_are_redacted(self):
        out = redact({
            "api_key": "sk-abcdefghijklmnop",
            "authorization": "Bearer abc",
            "password": "hunter2",
            "nested": {"secret_token": "shhh", "port": 8765},
        })
        self.assertEqual(out["api_key"], "[REDACTED]")
        self.assertEqual(out["authorization"], "[REDACTED]")
        self.assertEqual(out["password"], "[REDACTED]")
        self.assertEqual(out["nested"]["secret_token"], "[REDACTED]")
        self.assertEqual(out["nested"]["port"], 8765)

    def test_bearer_values_in_strings_are_redacted(self):
        out = redact("curl -H 'Authorization: Bearer sk-abcdefghijkl'")
        self.assertNotIn("sk-abcdefghijkl", out)
        self.assertIn("[REDACTED]", out)

    def test_github_style_tokens_are_redacted(self):
        out = redact("token ghp_1234567890abcdef1234")
        self.assertNotIn("ghp_1234567890abcdef1234", out)

    def test_non_secret_values_survive(self):
        out = redact({"url": "http://127.0.0.1:8765/health",
                      "branch": "work/r02", "port": 8765})
        self.assertEqual(out["url"], "http://127.0.0.1:8765/health")
        self.assertEqual(out["branch"], "work/r02")
        self.assertEqual(out["port"], 8765)

    def test_observation_dict_contains_no_env_dump(self):
        reg = _reg()
        with patch("core.infra.probes.run_all_local_probes", return_value=[]):
            scoped = build_local_observation(reg)
        dumped = json.dumps(scoped.to_dict()).lower()
        for banned in ("api_key", "authorization:", "password", "secret"):
            self.assertNotIn(banned, dumped)

    def test_evidence_timestamps_are_utc(self):
        ev = ProbeEvidence(probe="p", observer_node="n", target_node="n",
                           status="ok",
                           observed_at=datetime.now(timezone.utc))
        self.assertTrue(ev.to_dict()["observed_at"].endswith("Z")
                        or "+" in ev.to_dict()["observed_at"])


class TestReadonlyDiagnostics(unittest.TestCase):
    """Diagnostics must not mutate state or execute recovery."""

    def test_status_command_takes_no_recovery_path(self):
        from core.infra.recovery import get_recovery_policy
        policy = get_recovery_policy(observation_only=True)
        payload = json.dumps(policy, default=str).lower()
        # An observation-only policy must not claim it executed anything.
        self.assertNotIn('"executed"', payload)

    def test_scoped_observation_carries_no_command(self):
        reg = _reg()
        with patch("core.infra.probes.run_all_local_probes", return_value=[]):
            scoped = build_local_observation(reg)
        self.assertFalse(hasattr(scoped, "command"))
        self.assertIsNone(scoped.to_dict().get("command"))


if __name__ == "__main__":
    unittest.main()
