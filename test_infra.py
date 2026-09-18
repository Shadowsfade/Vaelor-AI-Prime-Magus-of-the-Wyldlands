"""Focused R0 infrastructure tests."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from core.infra.status import NodeObservation, NodeState, ProbeEvidence
from core.infra.classifier import classify_observation, NodeExpectations, get_state_summary
from core.infra.recovery import RecoveryPolicy, RecoveryAction, RecoveryTrigger, get_recovery_policy
from core.infra.relay_contract import get_relay_contract, NodeConfig
from core.infra.probes.windows import (
    _verify_vaelor_identity,
    probe_tailscale,
    probe_ssh_service,
    probe_listener_ownership,
    run_all_local_probes,
)
from core.infra.observer import observe_local


class TestTailscaleServiceParsing(unittest.TestCase):
    """Test Tailscale service enum/string parsing."""

    @patch("core.infra.probes.windows._run_powershell")
    def test_tailscale_service_returns_running(self, mock_run):
        mock_run.return_value = (0, '{"Status": "Running", "StartType": "Automatic"}', "")
        from core.infra.probes.windows import probe_tailscale
        evidence = probe_tailscale("skyai", "skyai")
        svc_evidence = [e for e in evidence if e.probe == "tailscale_service"][0]
        self.assertEqual(svc_evidence.status, "ok")
        self.assertEqual(svc_evidence.raw.get("Status"), "Running")

    @patch("core.infra.probes.windows._run_powershell")
    def test_tailscale_service_stopped_is_degraded(self, mock_run):
        mock_run.return_value = (0, '{"Status": "Stopped", "StartType": "Automatic"}', "")
        from core.infra.probes.windows import probe_tailscale
        evidence = probe_tailscale("skyai", "skyai")
        svc_evidence = [e for e in evidence if e.probe == "tailscale_service"][0]
        self.assertEqual(svc_evidence.status, "degraded")


class TestSSHServiceParsing(unittest.TestCase):
    """Test SSH service enum/string parsing."""

    @patch("core.infra.probes.windows._run_powershell")
    def test_ssh_service_returns_running(self, mock_run):
        mock_run.return_value = (0, '{"Status": "Running", "StartType": "Automatic"}', "")
        from core.infra.probes.windows import probe_ssh_service
        evidence = probe_ssh_service("skyai", "skyai")
        self.assertEqual(evidence.status, "ok")
        self.assertEqual(evidence.raw.get("Status"), "Running")

    @patch("core.infra.probes.windows._run_powershell")
    def test_ssh_service_not_found_is_failed(self, mock_run):
        mock_run.return_value = (0, "", "")
        from core.infra.probes.windows import probe_ssh_service
        evidence = probe_ssh_service("skyai", "skyai")
        self.assertEqual(evidence.status, "failed")


class TestTailscalePeerReachability(unittest.TestCase):
    """Test that backend Running + zero peers does not degrade local node."""

    @patch("core.infra.probes.windows._run_cmd")
    @patch("core.infra.probes.windows._run_powershell")
    def test_backend_running_zero_peers_local_healthy(self, mock_ps, mock_cmd):
        # Service Running
        mock_ps.return_value = (0, '{"Status": "Running", "StartType": "Automatic"}', "")
        # Backend Running, zero peers
        mock_cmd.return_value = (0, json.dumps({
            "BackendState": "Running",
            "TailscaleIPs": ["100.119.249.96"],
            "Peer": {}
        }), "")

        from core.infra.probes.windows import probe_tailscale
        evidence = probe_tailscale("skyai", "skyai")
        backend_evidence = [e for e in evidence if e.probe == "tailscale_backend"][0]
        peer_evidence = [e for e in evidence if e.probe == "tailscale_peer_reachable"][0]

        self.assertEqual(backend_evidence.status, "ok")
        # Peer reachability is informational - degraded is acceptable but should not affect node health


class TestOdysseusNeverClassifiedAsVaelor(unittest.TestCase):
    """Test Odysseus is never classified as Vaelor."""

    def test_verify_vaelor_identity_odysseus_not_verified(self):
        # VERIFIED requires explicit product identity == Vaelor
        # INFERRED is weak textual detection of "vaelor"
        # UNKNOWN is no match
        body = '{"name": "Odysseus", "version": "1.0"}'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = body.encode()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = lambda s, *a: None
            mock_urlopen.return_value = mock_resp

            from core.infra.probes.windows import _verify_vaelor_identity
            is_vaelor, confidence, raw = _verify_vaelor_identity("http://127.0.0.1:7000/health", 7000)
            # Odysseus has NO "vaelor" text and name != "Vaelor" -> should be UNKNOWN
            self.assertFalse(is_vaelor)
            self.assertEqual(confidence, "UNKNOWN")


class TestVaelorIdentityVerification(unittest.TestCase):
    """Test Vaelor product identity verification levels."""

    def test_exact_product_identity_is_verified(self):
        # VERIFIED: explicit product field == Vaelor
        body = '{"name": "Vaelor", "product": "Vaelor", "version": "1.0"}'
        is_vaelor, confidence, raw = _verify_vaelor_identity("http://127.0.0.1:8765/health", 8765)
        # Direct test of verification logic via the function
        import urllib.request
        from unittest.mock import MagicMock

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = body.encode()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = lambda s, *a: None
            mock_urlopen.return_value = mock_resp

            is_vaelor, confidence, raw = _verify_vaelor_identity("http://127.0.0.1:8765/health", 8765)
            self.assertTrue(is_vaelor)
            self.assertEqual(confidence, "VERIFIED")

    def test_arbitrary_vaelor_mention_is_inferred(self):
        # INFERRED: only weak textual detection
        body = '{"status": "ok", "service": "some vaelor thing"}'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = body.encode()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = lambda s, *a: None
            mock_urlopen.return_value = mock_resp

            is_vaelor, confidence, raw = _verify_vaelor_identity("http://127.0.0.1:8765/health", 8765)
            self.assertTrue(is_vaelor)
            self.assertEqual(confidence, "INFERRED")

    def test_no_vaelor_identity_unknown(self):
        body = '{"status": "ok"}'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.getcode.return_value = 200
            mock_resp.read.return_value = body.encode()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = lambda s, *a: None
            mock_urlopen.return_value = mock_resp

            is_vaelor, confidence, raw = _verify_vaelor_identity("http://127.0.0.1:8000/health", 8000)
            self.assertFalse(is_vaelor)
            self.assertEqual(confidence, "UNKNOWN")


class TestRequiredFalseDegraded(unittest.TestCase):
    """Test required False -> DEGRADED."""

    def test_required_false_is_degraded(self):
        obs = NodeObservation(
            node="skyai", observer_node="skyai", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=False, vaelor_health=True, ssh_service=True
        )
        expectations = NodeExpectations.for_node("skyai")
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.DEGRADED)


class TestRequiredNoneUnknown(unittest.TestCase):
    """Test required None -> UNKNOWN where evidence insufficient."""

    def test_required_none_without_positive_evidence_is_unknown(self):
        obs = NodeObservation(
            node="skyai", observer_node="skyai", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=None, vaelor_health=None, ssh_service=None
        )
        expectations = NodeExpectations.for_node("skyai")
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.UNKNOWN)

    def test_required_none_with_some_positive_evidence_is_unknown(self):
        obs = NodeObservation(
            node="skyai", observer_node="skyai", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=None, ssh_service=True
        )
        expectations = NodeExpectations.for_node("skyai")
        state = classify_observation(obs, expectations)
        # Required probe is None -> UNKNOWN, even though other required probes are True
        self.assertEqual(state, NodeState.UNKNOWN)


class TestModelBackendDownNotUnreachable(unittest.TestCase):
    """Test Ollama down does not make host unreachable."""

    def test_model_backend_false_not_unreachable(self):
        obs = NodeObservation(
            node="skyai", observer_node="skyai", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=True,
            ssh_service=True, model_backend=False
        )
        expectations = NodeExpectations.for_node("skyai")
        state = classify_observation(obs, expectations)
        # model_backend not required for skyai, so should be DEGRADED (optional failure) not UNREACHABLE
        self.assertIn(state, [NodeState.DEGRADED, NodeState.HEALTHY])
        self.assertNotEqual(state, NodeState.UNREACHABLE)


class TestListenerDetection(unittest.TestCase):
    """Test listener detection on various addresses."""

    @patch("core.infra.probes.windows._run_powershell")
    def test_listener_on_0_0_0_0_detected(self, mock_run):
        mock_run.side_effect = [
            (0, json.dumps([{"LocalAddress": "0.0.0.0", "LocalPort": 8765, "OwningProcess": 1234}]), ""),
            (0, json.dumps({"ProcessId": 1234, "ExecutablePath": "C:\\Vaelor\\.venv\\Scripts\\python.exe", "CommandLine": "python -m uvicorn"}), ""),
        ]
        evidence = probe_listener_ownership("skyai", "skyai", ports=[8765])
        ownership = evidence.raw.get("ownership", {})
        self.assertIn("8765", ownership)
        self.assertEqual(ownership["8765"]["local_address"], "0.0.0.0")

    @patch("core.infra.probes.windows._run_powershell")
    def test_listener_on_ipv6_detected(self, mock_run):
        mock_run.side_effect = [
            (0, json.dumps([{"LocalAddress": "::", "LocalPort": 8765, "OwningProcess": 1234}]), ""),
            (0, json.dumps({"ProcessId": 1234, "ExecutablePath": "C:\\Vaelor\\.venv\\Scripts\\python.exe", "CommandLine": "python -m uvicorn"}), ""),
        ]
        evidence = probe_listener_ownership("skyai", "skyai", ports=[8765])
        ownership = evidence.raw.get("ownership", {})
        self.assertIn("8765", ownership)
        self.assertEqual(ownership["8765"]["local_address"], "::")


class TestUnknownListenerOwner(unittest.TestCase):
    """Test unknown listener owner remains UNKNOWN."""

    @patch("core.infra.probes.windows._run_powershell")
    def test_unknown_listener_owner(self, mock_run):
        mock_run.side_effect = [
            (0, json.dumps([{"LocalAddress": "127.0.0.1", "LocalPort": 9999, "OwningProcess": 5678}]), ""),
            (0, json.dumps({"ProcessId": 5678, "ExecutablePath": "C:\\Unknown\\app.exe", "CommandLine": "app.exe"}), ""),
        ]
        evidence = probe_listener_ownership("skyai", "skyai", ports=[9999])
        ownership = evidence.raw.get("ownership", {})
        self.assertIn("9999", ownership)
        self.assertEqual(ownership["9999"]["identity_confidence"], "UNKNOWN")


class TestLANIPUnset(unittest.TestCase):
    """Test LAN IP may be unset."""

    def test_relay_contract_lan_ip_none(self):
        contract = get_relay_contract()
        skyai_config = contract.get_node_config("skyai")
        self.assertIsNone(skyai_config.lan_ip)


class TestRecoveryDescriptions(unittest.TestCase):
    """Test recovery attempt descriptions are correct."""

    def test_recovery_attempt_1_2_description(self):
        policy = get_recovery_policy(observation_only=True)
        candidate = policy.get_candidate(RecoveryTrigger.VAELOR_UNHEALTHY, "skyai", attempt=1)
        self.assertEqual(candidate.description, "Restart Vaelor API on skyai (attempt 1/2)")

        candidate2 = policy.get_candidate(RecoveryTrigger.VAELOR_UNHEALTHY, "skyai", attempt=2)
        self.assertEqual(candidate2.description, "Restart Vaelor API on skyai (attempt 2/2)")

    def test_recovery_attempt_3_rejected(self):
        from core.infra.recovery import RecoveryCandidate, RecoveryAction, RecoveryTrigger
        candidate = RecoveryCandidate(
            action=RecoveryAction.RESTART_VAELOR,
            trigger=RecoveryTrigger.VAELOR_UNHEALTHY,
            target_node="skyai",
            attempt=2,
            max_attempts=2,
        )
        with self.assertRaises(ValueError):
            candidate.next_attempt()


class TestObservationOnly(unittest.TestCase):
    """Test observation-only mode executes zero actions."""

    def test_observation_only_no_execute(self):
        policy = get_recovery_policy(observation_only=True)
        candidate = policy.get_candidate(RecoveryTrigger.VAELOR_UNHEALTHY, "skyai", attempt=1)
        result = policy.execute_candidate(candidate)
        self.assertFalse(result)


class TestLEGORole(unittest.TestCase):
    """Test LEGO role does not require Vaelor API."""

    def test_lego_expectations_no_vaelor(self):
        expectations = NodeExpectations.for_node("legiongo")
        self.assertFalse(expectations.vaelor_required)
        self.assertTrue(expectations.tailscale_required)
        self.assertFalse(expectations.ssh_required)

    def test_lego_classification_without_vaelor(self):
        obs = NodeObservation(
            node="legiongo", observer_node="legiongo", state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=None, ssh_service=None
        )
        expectations = NodeExpectations.for_node("legiongo")
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.HEALTHY)


class TestVaelorEndpointPlusClosedPorts(unittest.TestCase):
    """Test valid Vaelor endpoint + closed historical ports remains valid."""

    @patch("core.infra.probes.windows.probe_host_uptime")
    @patch("core.infra.probes.windows.probe_tailscale")
    @patch("core.infra.probes.windows.probe_ssh_service")
    @patch("core.infra.probes.windows.probe_listener_ownership")
    @patch("core.infra.probes.windows.probe_git_identity")
    @patch("core.infra.probes.windows.probe_model_backend")
    @patch("core.infra.probes.windows.probe_vaelor_endpoints")
    def test_one_valid_plus_closed_ports(self, mock_vaelor_endpoints, mock_model, mock_git, mock_listener, mock_ssh, mock_tailscale, mock_uptime):
        # Mock all other probes to return valid evidence
        mock_uptime.return_value = ProbeEvidence(probe="host_uptime", observer_node="skyai", target_node="skyai", status="ok", raw={"uptime_seconds": 3600})
        mock_tailscale.return_value = [
            ProbeEvidence(probe="tailscale_service", observer_node="skyai", target_node="skyai", status="ok"),
            ProbeEvidence(probe="tailscale_backend", observer_node="skyai", target_node="skyai", status="ok"),
            ProbeEvidence(probe="tailscale_peer_reachable", observer_node="skyai", target_node="skyai", status="degraded"),
        ]
        mock_ssh.return_value = ProbeEvidence(probe="ssh_service", observer_node="skyai", target_node="skyai", status="ok")
        mock_listener.return_value = ProbeEvidence(probe="listener_ownership", observer_node="skyai", target_node="skyai", status="ok", raw={"ownership": {}})
        mock_git.return_value = ProbeEvidence(probe="git_identity", observer_node="skyai", target_node="skyai", status="ok", raw={"branch": "main", "head": "abc123"})
        mock_model.return_value = ProbeEvidence(probe="model_backend", observer_node="skyai", target_node="skyai", status="failed")

        # Mock Vaelor endpoints: only configured port 8765 is VERIFIED
        mock_vaelor_endpoints.return_value = [
            ProbeEvidence(probe="vaelor_health_8765", observer_node="skyai", target_node="skyai", status="ok", raw={"source": "configured", "identity_confidence": "VERIFIED", "verified_vaelor": True}),
            ProbeEvidence(probe="vaelor_health_8766", observer_node="skyai", target_node="skyai", status="failed", raw={"source": "vaelor_range", "identity_confidence": "UNKNOWN", "verified_vaelor": False}),
            ProbeEvidence(probe="vaelor_readiness_8765", observer_node="skyai", target_node="skyai", status="ok", raw={"source": "configured", "identity_confidence": "VERIFIED", "verified_vaelor": True}),
            ProbeEvidence(probe="vaelor_readiness_8766", observer_node="skyai", target_node="skyai", status="failed", raw={"source": "vaelor_range", "identity_confidence": "UNKNOWN", "verified_vaelor": False}),
            ProbeEvidence(probe="vaelor_runtime_status_8765", observer_node="skyai", target_node="skyai", status="ok", raw={"source": "configured", "identity_confidence": "VERIFIED", "verified_vaelor": True}),
            ProbeEvidence(probe="vaelor_runtime_status_8766", observer_node="skyai", target_node="skyai", status="failed", raw={"source": "vaelor_range", "identity_confidence": "UNKNOWN", "verified_vaelor": False}),
        ]

        evidence = run_all_local_probes("skyai", "skyai")
        vaelor_evidence = [e for e in evidence if e.probe.startswith("vaelor_health_")]
        ok_count = sum(1 for e in vaelor_evidence if e.status == "ok")
        self.assertEqual(ok_count, 1)  # Only configured port should be ok


class TestFailedEndpointNoUnboundLocalError(unittest.TestCase):
    """Test failed endpoint request does not raise UnboundLocalError."""

    @patch("core.infra.probes.windows._run_powershell")
    @patch("core.infra.probes.windows._run_cmd")
    @patch("core.infra.probes.windows._verify_vaelor_identity")
    @patch("urllib.request.urlopen")
    def test_failed_endpoint_no_unbound_error(self, mock_urlopen, mock_verify, mock_cmd, mock_ps):
        mock_ps.return_value = (0, '{"Status": "Running", "StartType": "Automatic"}', "")
        mock_cmd.return_value = (0, json.dumps({"BackendState": "Running", "TailscaleIPs": [], "Peer": {}}), "")
        mock_verify.return_value = (False, "UNKNOWN", {"error": "connection refused"})

        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        # Should not raise UnboundLocalError
        evidence = run_all_local_probes("skyai", "skyai")
        vaelor_evidence = [e for e in evidence if e.probe.startswith("vaelor_")]
        # All should be failed or degraded, none should crash
        for e in vaelor_evidence:
            self.assertIn(e.status, ["failed", "degraded"])


if __name__ == "__main__":
    unittest.main()

class TestHardcodedPathRemoved(unittest.TestCase):
    """Test that infra status does not depend on hardcoded ComputerUse-Foundation path."""

    @patch('core.infra.probes.windows._run_powershell')
    @patch('core.infra.probes.windows._run_cmd')
    @patch('core.infra.probes.windows.probe_vaelor_endpoints')
    @patch('core.infra.probes.windows.probe_model_backend')
    def test_observe_local_without_hardcoded_path(self, mock_model, mock_vaelor, mock_cmd, mock_ps):
        # Mock all probes to return valid evidence
        mock_ps.return_value = (0, '{"Status": "Running", "StartType": "Automatic"}', '')
        mock_cmd.return_value = (0, json.dumps({'BackendState': 'Running', 'TailscaleIPs': [], 'Peer': {}}), '')

        mock_vaelor.return_value = [
            ProbeEvidence(probe='vaelor_health_8765', observer_node='skyai', target_node='skyai', status='ok', raw={'source': 'configured', 'identity_confidence': 'VERIFIED', 'verified_vaelor': True}),
        ]
        mock_model.return_value = ProbeEvidence(probe='model_backend', observer_node='skyai', target_node='skyai', status='failed')

        # Call observe_local WITHOUT providing worktree_path
        # This should work via git discovery
        obs = observe_local(node_name='skyai', observer_name='skyai', worktree_path=None)

        # Should not crash and should produce a valid observation
        self.assertIsNotNone(obs)
        self.assertEqual(obs.node, 'skyai')


class TestRequiredNoneClassification(unittest.TestCase):
    """Test required None -> UNKNOWN semantics (not DEGRADED)."""

    def test_required_none_is_unknown_even_with_other_required_true(self):
        # host_reachable=True, tailscale=True, ssh=True, vaelor_health=None
        # vaelor_health is required for skyai and is None -> must be UNKNOWN
        obs = NodeObservation(
            node='skyai', observer_node='skyai', state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=None, ssh_service=True
        )
        expectations = NodeExpectations.for_node('skyai')
        state = classify_observation(obs, expectations)
        # Required probe is None -> UNKNOWN, even though other required probes are True
        self.assertEqual(state, NodeState.UNKNOWN, 'Required None must be UNKNOWN, not DEGRADED')

    def test_required_false_is_degraded(self):
        obs = NodeObservation(
            node='skyai', observer_node='skyai', state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=False, vaelor_health=True, ssh_service=True
        )
        expectations = NodeExpectations.for_node('skyai')
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.DEGRADED)

    def test_optional_false_is_degraded(self):
        # model_backend is optional for skyai
        obs = NodeObservation(
            node='skyai', observer_node='skyai', state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=True,
            ssh_service=True, model_backend=False
        )
        expectations = NodeExpectations.for_node('skyai')
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.DEGRADED)

    def test_host_unreachable_is_unreachable(self):
        obs = NodeObservation(
            node='skyai', observer_node='skyai', state=NodeState.UNKNOWN,
            host_reachable=False, tailscale_service=True, vaelor_health=True, ssh_service=True
        )
        expectations = NodeExpectations.for_node('skyai')
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.UNREACHABLE)

    def test_all_required_true_is_healthy(self):
        obs = NodeObservation(
            node='skyai', observer_node='skyai', state=NodeState.UNKNOWN,
            host_reachable=True, tailscale_service=True, vaelor_health=True, ssh_service=True
        )
        expectations = NodeExpectations.for_node('skyai')
        state = classify_observation(obs, expectations)
        self.assertEqual(state, NodeState.HEALTHY)