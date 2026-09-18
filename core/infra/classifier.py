"""Deterministic classification rules for infrastructure state.

Classification is evidence-based and never infers False from None.
Role-aware: different nodes have different required services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.infra.status import NodeState, NodeObservation


@dataclass(frozen=True)
class NodeExpectations:
    """Expected services for a given node role."""
    node: str
    vaelor_required: bool = True
    tailscale_required: bool = True
    ssh_required: bool = True
    model_backend_required: bool = False
    supervisor_required: bool = False

    # Default expectations per node
    @classmethod
    def for_node(cls, node: str) -> "NodeExpectations":
        defaults = {
            "skyai": cls(
                node="skyai",
                vaelor_required=True,
                tailscale_required=True,
                ssh_required=True,
                model_backend_required=False,
                supervisor_required=False,
            ),
            "vaelor-relay": cls(
                node="vaelor-relay",
                vaelor_required=False,  # Guardian only, not full API
                tailscale_required=True,
                ssh_required=True,
                model_backend_required=False,
                supervisor_required=False,
            ),
            "legiongo": cls(
                node="legiongo",
                vaelor_required=False,  # Operator node, not a Vaelor host
                tailscale_required=True,
                ssh_required=False,
                model_backend_required=False,
                supervisor_required=False,
            ),
        }
        return defaults.get(node, cls(node=node, vaelor_required=False))


def classify_observation(obs: NodeObservation, expectations: Optional[NodeExpectations] = None) -> NodeState:
    """Classify a node observation into a deterministic state.

    Rules:
    - HEALTHY: host reachable + all REQUIRED probes ok (per node role)
    - DEGRADED: host reachable + at least one REQUIRED probe failed (False)
    - RECOVERING: explicit recovery in progress (set externally)
    - UNREACHABLE: host not reachable from observer
    - UNKNOWN: insufficient evidence (required probe is None and no other evidence proves degradation)
    """
    if expectations is None:
        expectations = NodeExpectations.for_node(obs.node)

    # If explicitly marked as recovering, keep it
    if obs.state == NodeState.RECOVERING:
        return NodeState.RECOVERING

    # Host reachability is the foundation
    if obs.host_reachable is False:
        return NodeState.UNREACHABLE

    if obs.host_reachable is None:
        # No host reachability evidence
        return NodeState.UNKNOWN

    # Host is reachable - check REQUIRED probes per node role
    required_failures = []
    required_unknown = []
    optional_failures = []

    # Check required services
    if expectations.tailscale_required:
        if obs.tailscale_service is False:
            required_failures.append("tailscale_service")
        elif obs.tailscale_service is None:
            required_unknown.append("tailscale_service")
    else:
        if obs.tailscale_service is False:
            optional_failures.append("tailscale_service")

    if expectations.vaelor_required:
        if obs.vaelor_health is False:
            required_failures.append("vaelor_health")
        elif obs.vaelor_health is None:
            required_unknown.append("vaelor_health")
    else:
        if obs.vaelor_health is False:
            optional_failures.append("vaelor_health")

    if expectations.ssh_required:
        if obs.ssh_service is False:
            required_failures.append("ssh_service")
        elif obs.ssh_service is None:
            required_unknown.append("ssh_service")
    else:
        if obs.ssh_service is False:
            optional_failures.append("ssh_service")

    # Non-required (optional) services
    if obs.model_backend is False:
        if expectations.model_backend_required:
            required_failures.append("model_backend")
        else:
            optional_failures.append("model_backend")
    elif obs.model_backend is None and expectations.model_backend_required:
        required_unknown.append("model_backend")

    if obs.vaelor_readiness is False:
        optional_failures.append("vaelor_readiness")
    if obs.supervisor is False:
        optional_failures.append("supervisor")
    # Peer reachability is INFORMATIONAL - never required, never optional failure
    # It does not affect node health classification

    # Any REQUIRED failure (False) -> DEGRADED
    if required_failures:
        return NodeState.DEGRADED

    # If any REQUIRED unknown and no other evidence proves degradation -> UNKNOWN
    # This prevents treating missing evidence as failure
    if required_unknown:
        # But if we have some positive evidence, the unknown required might be degraded
        # Check if we have ANY positive evidence from required probes
        required_positive = []
        if expectations.tailscale_required and obs.tailscale_service is True:
            required_positive.append("tailscale_service")
        if expectations.vaelor_required and obs.vaelor_health is True:
            required_positive.append("vaelor_health")
        if expectations.ssh_required and obs.ssh_service is True:
            required_positive.append("ssh_service")
        if expectations.model_backend_required and obs.model_backend is True:
            required_positive.append("model_backend")
        
        if not required_positive:
            # No positive required evidence, unknown dominates
            return NodeState.UNKNOWN
        
        # Some required probes are ok but others are unknown -> DEGRADED
        # We cannot classify as HEALTHY when required evidence is missing
        return NodeState.DEGRADED

    # If no required failures but optional failures -> DEGRADED
    if optional_failures:
        return NodeState.DEGRADED

    # All checked probes ok -> HEALTHY
    # But only if we have at least some evidence
    has_any_evidence = any([
        obs.tailscale_service is not None,
        obs.vaelor_health is not None,
        obs.model_backend is not None,
        obs.vaelor_readiness is not None,
        obs.supervisor is not None,
        obs.ssh_service is not None,
    ])

    if has_any_evidence:
        return NodeState.HEALTHY

    return NodeState.UNKNOWN


def is_vaelor_expected(obs: NodeObservation) -> bool:
    """Determine if Vaelor is expected to be running on this node.

    Based on verified listener identity (not just path strings).
    """
    for port, info in obs.listener_ownership.items():
        product = info.get("product", "").lower()
        identity_confidence = info.get("identity_confidence", "")
        if product == "vaelor" and identity_confidence == "VERIFIED":
            return True
    return False


def get_state_summary(obs: NodeObservation) -> dict:
    """Get a structured summary for CLI output."""
    return {
        "node": obs.node,
        "observer": obs.observer_node,
        "state": obs.state.value,
        "observed_at": obs.observed_at.isoformat() + "Z",
        "host": "HEALTHY" if obs.host_reachable else ("UNHEALTHY" if obs.host_reachable is False else "UNKNOWN"),
        "tailscale": _probe_to_str(obs.tailscale_service, "service"),
        "tailscale_backend": _probe_to_str(obs.tailscale_backend, "backend"),
        "tailscale_peers": _probe_to_str(obs.tailscale_peer_reachable, "peers"),
        "ssh_service": _probe_to_str(obs.ssh_service, "service"),
        "vaelor_health": _probe_to_str(obs.vaelor_health, "health"),
        "vaelor_readiness": _probe_to_str(obs.vaelor_readiness, "readiness"),
        "supervisor": _probe_to_str(obs.supervisor, "supervisor"),
        "model_backend": _probe_to_str(obs.model_backend, "model"),
        "uptime_seconds": obs.uptime_seconds,
        "git_branch": obs.git_branch,
        "git_head": obs.git_head[:8] if obs.git_head else None,
        "listeners": obs.listener_ownership,
    }


def _probe_to_str(val: Optional[bool], probe_type: str) -> str:
    if val is None:
        return "UNKNOWN"
    if val:
        return "HEALTHY"
    return "DEGRADED"