"""Observer orchestrates probes and produces classified NodeObservations."""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Optional

from core.infra.status import NodeObservation, NodeState, ProbeEvidence
from core.infra.classifier import classify_observation, is_vaelor_expected, NodeExpectations
from core.infra.probes import run_all_local_probes


def observe_local(node_name: str = "legiongo",
                  observer_name: Optional[str] = None,
                  worktree_path: Optional[str] = None) -> NodeObservation:
    """Run all local probes and produce a classified NodeObservation.

    This is the primary entry point for R0.1 local observation.
    The target node defaults to the current hostname.
    """
    observer = observer_name or platform.node()
    target = node_name or platform.node()

    obs = NodeObservation(
        node=target,
        observer_node=observer,
        state=NodeState.UNKNOWN,
        observed_at=datetime.now(timezone.utc),
    )

    # Run all local probes
    evidence_list = run_all_local_probes(observer, target, worktree_path)

    # Populate observation from evidence
    for ev in evidence_list:
        obs.add_evidence(ev)
        _apply_evidence(obs, ev)

    # Determine if Vaelor is expected here (from verified listener identity)
    vaelor_expected = is_vaelor_expected(obs)

    # Classify with role-aware expectations
    expectations = NodeExpectations.for_node(target)
    obs.state = classify_observation(obs, expectations)

    return obs


def _apply_evidence(obs: NodeObservation, ev: ProbeEvidence) -> None:
    """Apply a single piece of evidence to the observation."""
    probe = ev.probe
    status = ev.status
    raw = ev.raw or {}

    # Host
    if probe == "host_uptime":
        obs.host_reachable = (status == "ok")
        if status == "ok" and "uptime_seconds" in raw:
            obs.uptime_seconds = raw["uptime_seconds"]

    # Tailscale
    elif probe == "tailscale_service":
        obs.tailscale_service = (status == "ok")
    elif probe == "tailscale_backend":
        obs.tailscale_backend = (status == "ok")
    elif probe == "tailscale_peer_reachable":
        obs.tailscale_peer_reachable = (status == "ok")

    # SSH
    elif probe == "ssh_service":
        obs.ssh_service = (status == "ok")

    # Vaelor
    elif probe.startswith("vaelor_health_"):
        obs.vaelor_health = (status == "ok")
    elif probe.startswith("vaelor_readiness_"):
        obs.vaelor_readiness = (status == "ok")

    # Supervisor - from runtime/status
    elif probe.startswith("vaelor_runtime_status_"):
        if status == "ok" and "body" in raw:
            try:
                import json
                data = json.loads(raw["body"])
                sup = data.get("supervisor", {})
                obs.supervisor = sup.get("running", False)
            except Exception:
                pass

    # Listener ownership
    elif probe == "listener_ownership":
        obs.listener_ownership = raw.get("ownership", {})

    # Git
    elif probe == "git_identity":
        if status == "ok" and "branch" in raw:
            obs.git_branch = raw["branch"]
            obs.git_head = raw["head"]
        # dirty status not directly stored, but in raw

    # Model backend
    elif probe == "model_backend":
        obs.model_backend = (status == "ok")


def observe_remote(node_name: str, observer_name: str,
                   ssh_host: str, ssh_user: str) -> NodeObservation:
    """Observe a remote node via SSH.

    This is a placeholder for Phase 2 when vaelor-relay is online.
    """
    obs = NodeObservation(
        node=node_name,
        observer_node=observer_name,
        state=NodeState.UNKNOWN,
        observed_at=datetime.now(timezone.utc),
    )
    obs.host_reachable = None  # Not probed locally
    obs.tailscale_service = None
    obs.tailscale_backend = None
    obs.tailscale_peer_reachable = None
    obs.ssh_remote_reachable = None  # Would need SSH probe
    obs.vaelor_health = None
    obs.vaelor_readiness = None
    obs.supervisor = None
    obs.model_backend = None
    return obs
