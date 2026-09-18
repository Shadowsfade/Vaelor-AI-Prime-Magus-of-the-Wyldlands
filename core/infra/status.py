"""Infrastructure status data models for Vaelor R0 observability.

These models represent the deterministic observation and classification
layer for infrastructure health. No recovery actions are encoded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class NodeState(Enum):
    """Classified infrastructure state of a node."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProbeEvidence:
    """Single probe result with full attribution.

    Every observation must record who observed what, when, and the raw evidence.
    """
    probe: str                          # e.g., "tailscale_service", "vaelor_health"
    observer_node: str                  # e.g., "skyai", "legiongo", "vaelor-relay"
    target_node: str                    # e.g., "skyai", "vaelor-relay"
    status: str                         # "ok", "degraded", "failed", "unknown"
    observed_at: datetime = field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = None
    detail: Optional[str] = None
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "probe": self.probe,
            "observer_node": self.observer_node,
            "target_node": self.target_node,
            "status": self.status,
            "observed_at": self.observed_at.isoformat() + "Z",
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "raw": self.raw,
        }


@dataclass
class NodeObservation:
    """Complete observation of a target node from a specific observer.

    Separates raw evidence from classified state. Unknown must remain None,
    not silently become False.
    """
    node: str                           # Target node name (e.g., "skyai")
    observer_node: str                  # Who performed the observation
    state: NodeState
    observed_at: datetime = field(default_factory=datetime.utcnow)

    # Host-level
    host_reachable: Optional[bool] = None

    # Tailscale
    tailscale_service: Optional[bool] = None
    tailscale_backend: Optional[bool] = None
    tailscale_peer_reachable: Optional[bool] = None

    # SSH
    ssh_service: Optional[bool] = None
    ssh_remote_reachable: Optional[bool] = None

    # Vaelor API
    vaelor_health: Optional[bool] = None
    vaelor_readiness: Optional[bool] = None
    supervisor: Optional[bool] = None
    model_backend: Optional[bool] = None

    # System
    uptime_seconds: Optional[float] = None

    # Git
    git_branch: Optional[str] = None
    git_head: Optional[str] = None

    # Listener ownership for configured Vaelor ports
    listener_ownership: dict = field(default_factory=dict)

    # Full evidence trail
    evidence: list[ProbeEvidence] = field(default_factory=list)

    def add_evidence(self, evidence: ProbeEvidence) -> None:
        self.evidence.append(evidence)

    def to_dict(self) -> dict:
        return {
            "node": self.node,
            "observer_node": self.observer_node,
            "state": self.state.value,
            "observed_at": self.observed_at.isoformat() + "Z",
            "host_reachable": self.host_reachable,
            "tailscale_service": self.tailscale_service,
            "tailscale_backend": self.tailscale_backend,
            "tailscale_peer_reachable": self.tailscale_peer_reachable,
            "ssh_service": self.ssh_service,
            "ssh_remote_reachable": self.ssh_remote_reachable,
            "vaelor_health": self.vaelor_health,
            "vaelor_readiness": self.vaelor_readiness,
            "supervisor": self.supervisor,
            "model_backend": self.model_backend,
            "uptime_seconds": self.uptime_seconds,
            "git_branch": self.git_branch,
            "git_head": self.git_head,
            "listener_ownership": self.listener_ownership,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    def summary(self) -> str:
        """Human-readable one-line summary."""
        parts = [f"{self.node}: {self.state.value}"]
        if self.host_reachable is not None:
            parts.append(f"host={'UP' if self.host_reachable else 'DOWN'}")
        if self.tailscale_service is not None:
            parts.append(f"tailscale={'OK' if self.tailscale_service else 'FAIL'}")
        if self.vaelor_health is not None:
            parts.append(f"vaelor={'OK' if self.vaelor_health else 'FAIL'}")
        if self.model_backend is not None:
            parts.append(f"model={'OK' if self.model_backend else 'FAIL'}")
        return " | ".join(parts)

