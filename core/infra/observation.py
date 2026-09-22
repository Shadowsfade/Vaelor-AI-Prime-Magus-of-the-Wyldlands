"""Scope-aware observation assembly for R0.2.

The core rule: local process/model evidence must never be attributed to a
remote target. Every probe carries an evidence scope, and the assembler
refuses to attach out-of-scope evidence to a target node.

Read-only. This module never starts, stops, or restarts anything.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Optional

from core.infra.condition import (
    NodeCondition,
    condition_to_state,
    resolve_condition,
)
from core.infra.node_config import NodeIdentity, NodeRegistry, NodeConfigError
from core.infra.status import NodeObservation, NodeState, ProbeEvidence


class ScopedObservation:
    """A NodeObservation plus the identity/condition metadata R0.2 requires."""

    def __init__(self, observation: NodeObservation, *,
                 observer: NodeIdentity, target: NodeIdentity,
                 scope: str, condition: NodeCondition,
                 explanation: str, contradictions: list,
                 timeout_ms: Optional[float] = None):
        self.observation = observation
        self.observer = observer
        self.target = target
        self.scope = scope
        self.condition = condition
        self.explanation = explanation
        self.contradictions = contradictions
        self.timeout_ms = timeout_ms

    @property
    def state(self) -> NodeState:
        return self.observation.state

    @property
    def node(self) -> str:
        return self.observation.node

    def to_dict(self) -> dict:
        base = self.observation.to_dict()
        base.update({
            "condition": self.condition.value,
            "explanation": self.explanation,
            "scope": self.scope,
            "configured_hostname": self.target.hostname,
            "target_tailscale_ip": self.target.tailscale_ip,
            "observer": self.observer.to_dict(),
            "target": self.target.to_dict(),
            "contradictions": list(self.contradictions),
            "timeout_ms": self.timeout_ms,
        })
        return base

    def summary(self) -> str:
        return (
            f"{self.target.name} [{self.scope}] "
            f"observer={self.observer.name} "
            f"condition={self.condition.value} "
            f"state={self.state.value} "
            f"| {self.explanation}"
        )


def _tag(evidence: ProbeEvidence, scope: str) -> ProbeEvidence:
    """Stamp a scope onto a piece of evidence without losing its content."""
    raw = dict(evidence.raw or {})
    raw.setdefault("evidence_scope", scope)
    return ProbeEvidence(
        probe=evidence.probe,
        observer_node=evidence.observer_node,
        target_node=evidence.target_node,
        status=evidence.status,
        observed_at=evidence.observed_at,
        latency_ms=evidence.latency_ms,
        detail=evidence.detail,
        raw=raw,
    )


def build_local_observation(registry: NodeRegistry, *,
                            target_name: Optional[str] = None,
                            worktree_path: Optional[str] = None,
                            timeout_ms: Optional[float] = None) -> ScopedObservation:
    """Observe the local machine and attribute it only to the local target.

    If a remote target is requested, local probes are still collected but
    are recorded under the observer's identity and the result is reported
    as UNKNOWN with an explicit 'no remote evidence' explanation. Local
    process/model facts are never written onto a remote target.
    """
    observer = registry.observer
    now = datetime.now(timezone.utc)

    try:
        target = registry.target(target_name)
    except NodeConfigError as exc:
        obs = NodeObservation(
            node=target_name or observer.name,
            observer_node=observer.name,
            state=NodeState.UNKNOWN,
            observed_at=now,
        )
        return ScopedObservation(
            obs, observer=observer, target=observer, scope="local",
            condition=NodeCondition.MISCONFIGURED, explanation=str(exc),
            contradictions=[], timeout_ms=timeout_ms,
        )

    is_local_target = target.name == observer.name
    scope = "local" if is_local_target else "remote"

    if not is_local_target:
        # Fail closed: do not run local probes and pretend they are remote.
        obs = NodeObservation(
            node=target.name,
            observer_node=observer.name,
            state=NodeState.UNKNOWN,
            observed_at=now,
        )
        obs.add_evidence(ProbeEvidence(
            probe="scope_guard",
            observer_node=observer.name,
            target_node=target.name,
            status="unknown",
            observed_at=now,
            detail="remote target requested; local probes withheld",
            raw={"evidence_scope": "withheld",
                 "reason": "local evidence must not be attributed to a remote target"},
        ))
        return ScopedObservation(
            obs, observer=observer, target=target, scope=scope,
            condition=NodeCondition.UNKNOWN,
            explanation=(
                f"target {target.name!r} is not the observer; no remote probe was "
                "performed, so no state can be asserted"
            ),
            contradictions=[], timeout_ms=timeout_ms,
        )

    from core.infra.probes import run_all_local_probes

    evidence_list = run_all_local_probes(observer.name, target.name, worktree_path)

    obs = NodeObservation(
        node=target.name,
        observer_node=observer.name,
        state=NodeState.UNKNOWN,
        observed_at=now,
    )
    for ev in evidence_list:
        scoped = _tag(ev, "local")
        obs.add_evidence(scoped)
        _apply(obs, scoped)

    condition, explanation = resolve_condition(
        scope="local",
        observer=observer.name,
        target=target.name,
        host_reachable=obs.host_reachable,
        vaelor_health=obs.vaelor_health,
        vaelor_process_alive=_process_alive_from(obs),
        model_backend=obs.model_backend,
        contradictions=_contradictions(obs),
    )

    obs.state = condition_to_state(condition)
    return ScopedObservation(
        obs, observer=observer, target=target, scope="local",
        condition=condition, explanation=explanation,
        contradictions=_contradictions(obs), timeout_ms=timeout_ms,
    )


def _process_alive_from(obs: NodeObservation) -> Optional[bool]:
    """Derive local process liveness from verified listener identity only."""
    verified = False
    saw_listener = False
    for _port, info in obs.listener_ownership.items():
        saw_listener = True
        if (str(info.get("product", "")).lower() == "vaelor"
                and info.get("identity_confidence") == "VERIFIED"):
            verified = True
    if verified:
        return True
    if obs.vaelor_health is True:
        return True
    if saw_listener and not verified:
        return None
    if obs.vaelor_health is False:
        return False
    return None


def _contradictions(obs: NodeObservation) -> list:
    """Detect evidence that cannot all be true at once."""
    out = []
    if obs.host_reachable is False and obs.vaelor_health is True:
        out.append("host unreachable but health endpoint answered")
    if obs.host_reachable is False and obs.model_backend is True:
        out.append("host unreachable but model backend answered")
    if obs.tailscale_service is True and obs.tailscale_backend is False:
        out.append("tailscale service active but backend not running")
    if obs.vaelor_health is True and not obs.listener_ownership:
        out.append("health endpoint answered but no listener ownership observed")
    return out


def _apply(obs: NodeObservation, ev: ProbeEvidence) -> None:
    """Fold one evidence record into the observation."""
    probe, status, raw = ev.probe, ev.status, (ev.raw or {})

    if probe == "host_uptime":
        obs.host_reachable = (status == "ok")
        if status == "ok" and "uptime_seconds" in raw:
            obs.uptime_seconds = raw["uptime_seconds"]
    elif probe == "tailscale_service":
        obs.tailscale_service = (status == "ok")
    elif probe == "tailscale_backend":
        obs.tailscale_backend = (status == "ok")
    elif probe == "tailscale_peer_reachable":
        obs.tailscale_peer_reachable = (status == "ok")
    elif probe == "ssh_service":
        obs.ssh_service = (status == "ok")
    elif probe.startswith("vaelor_health_"):
        # First failing health wins over a later success only if none passed.
        if obs.vaelor_health is None or status == "ok":
            obs.vaelor_health = (status == "ok")
    elif probe.startswith("vaelor_readiness_"):
        if obs.vaelor_readiness is None or status == "ok":
            obs.vaelor_readiness = (status == "ok")
    elif probe.startswith("vaelor_runtime_status_"):
        if status == "ok" and isinstance(raw.get("body"), str):
            try:
                import json
                sup = json.loads(raw["body"]).get("supervisor", {})
                obs.supervisor = bool(sup.get("running", False))
            except Exception:
                pass
    elif probe == "listener_ownership":
        obs.listener_ownership = raw.get("ownership", {})
    elif probe == "git_identity":
        if status == "ok":
            obs.git_branch = raw.get("branch")
            obs.git_head = raw.get("head")
    elif probe == "model_backend":
        obs.model_backend = (status == "ok")
