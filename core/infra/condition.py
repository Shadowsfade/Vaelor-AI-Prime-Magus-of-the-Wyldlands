"""Fine-grained node conditions and evidence redaction.

``NodeState`` stays the coarse R0.1 rollup so existing consumers keep
working. ``NodeCondition`` is the precise diagnosis that R0.2 requires:
it separates "this machine is down" from "I cannot reach it", and
separates a dead process from an unhealthy one.

Contradictory evidence resolves to UNKNOWN or DEGRADED with an
explanation, never to a confident DOWN diagnosis.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterable, Optional


class NodeCondition(Enum):
    """Precise diagnosis derived from evidence."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HOST_UNREACHABLE = "HOST_UNREACHABLE"
    NETWORK_PATH_UNAVAILABLE = "NETWORK_PATH_UNAVAILABLE"
    VAELOR_PROCESS_DOWN = "VAELOR_PROCESS_DOWN"
    VAELOR_UNHEALTHY = "VAELOR_UNHEALTHY"
    MODEL_BACKEND_DOWN = "MODEL_BACKEND_DOWN"
    MISCONFIGURED = "MISCONFIGURED"
    UNKNOWN = "UNKNOWN"
    RECOVERING = "RECOVERING"


# Conditions that assert the target host is definitively not there.
DOWN_ASSERTING = {
    NodeCondition.HOST_UNREACHABLE,
    NodeCondition.NETWORK_PATH_UNAVAILABLE,
    NodeCondition.VAELOR_PROCESS_DOWN,
}

# Conditions that mean "we do not know", and must never be rendered as DOWN.
UNCERTAIN = {
    NodeCondition.UNKNOWN,
    NodeCondition.MISCONFIGURED,
}

_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|"
    r"cookie|credential|private[_-]?key|bearer)",
    re.IGNORECASE,
)

_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(bearer\s+[A-Za-z0-9._~+/-]+=*|"
    r"(?:sk|pk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{8,})",
)


def redact(value):
    """Recursively strip anything credential-shaped from evidence.

    Applied to every structured error and recovery event before it is
    persisted, so logs never carry credentials or environment dumps.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        if _SECRET_VALUE_RE.search(value):
            return _SECRET_VALUE_RE.sub("[REDACTED]", value)
        if len(value) > 500:
            return value[:250] + "...[truncated]" + value[-100:]
    return value


def bounded_error(exc: BaseException, limit: int = 300) -> str:
    """Bound an exception message so health errors stay structured and small."""
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:limit]


def explain(observations: Iterable[tuple]) -> str:
    """Build a short explanation from (label, value) pairs."""
    parts = []
    for label, value in observations:
        if value is None:
            parts.append(f"{label}=unknown")
        elif value is True:
            parts.append(f"{label}=ok")
        elif value is False:
            parts.append(f"{label}=fail")
        else:
            parts.append(f"{label}={value}")
    return "; ".join(parts)


def resolve_condition(*,
                      scope: str,
                      observer: str,
                      target: str,
                      host_reachable: Optional[bool],
                      vaelor_health: Optional[bool],
                      vaelor_process_alive: Optional[bool],
                      model_backend: Optional[bool],
                      contradictions: Optional[list] = None,
                      misconfigured: Optional[str] = None) -> tuple:
    """Deterministically resolve a NodeCondition from separated evidence.

    Returns (condition, explanation).

    Rules:
    - Configuration problems fail closed to MISCONFIGURED.
    - Contradictory evidence fails closed to UNKNOWN with the reason.
    - Local scope lets us assert host down; remote scope never does.
    """
    if misconfigured:
        return NodeCondition.MISCONFIGURED, f"misconfigured: {misconfigured}"

    if contradictions:
        joined = "; ".join(contradictions)
        return NodeCondition.UNKNOWN, f"contradictory evidence: {joined}"

    if host_reachable is False:
        if scope == "local" and observer == target:
            return NodeCondition.HOST_UNREACHABLE, "local observer reports host down"
        return (
            NodeCondition.NETWORK_PATH_UNAVAILABLE,
            "target unreachable from observer; host state cannot be distinguished "
            "from a broken network path",
        )

    if host_reachable is None:
        return NodeCondition.UNKNOWN, "no host reachability evidence"

    # Host is up from here.
    if vaelor_process_alive is False:
        return NodeCondition.VAELOR_PROCESS_DOWN, "configured local process is absent"

    if vaelor_health is False and vaelor_process_alive:
        return NodeCondition.VAELOR_UNHEALTHY, "process alive but health endpoint failing"

    if vaelor_health is False and vaelor_process_alive is None:
        return NodeCondition.VAELOR_UNHEALTHY, "health endpoint failing; process state unknown"

    if model_backend is False:
        return (
            NodeCondition.MODEL_BACKEND_DOWN,
            "model backend unavailable; status, approval, and diagnosis remain usable",
        )

    if vaelor_health is True and vaelor_process_alive is not False:
        return NodeCondition.HEALTHY, "host, process, and health endpoint all observed ok"

    if vaelor_process_alive is True and vaelor_health is None:
        return NodeCondition.DEGRADED, "process alive; health endpoint not yet observed"

    if host_reachable is True and vaelor_health is None and vaelor_process_alive is None:
        return NodeCondition.UNKNOWN, "host observed; no service evidence collected"

    return NodeCondition.UNKNOWN, "insufficient evidence to classify"


def condition_to_state(condition: NodeCondition):
    """Map a precise condition onto the coarse R0.1 NodeState rollup."""
    from core.infra.status import NodeState

    mapping = {
        NodeCondition.HEALTHY: NodeState.HEALTHY,
        NodeCondition.DEGRADED: NodeState.DEGRADED,
        NodeCondition.RECOVERING: NodeState.RECOVERING,
        NodeCondition.HOST_UNREACHABLE: NodeState.UNREACHABLE,
        NodeCondition.NETWORK_PATH_UNAVAILABLE: NodeState.UNREACHABLE,
        NodeCondition.VAELOR_PROCESS_DOWN: NodeState.DEGRADED,
        NodeCondition.VAELOR_UNHEALTHY: NodeState.DEGRADED,
        NodeCondition.MODEL_BACKEND_DOWN: NodeState.DEGRADED,
        NodeCondition.MISCONFIGURED: NodeState.UNKNOWN,
        NodeCondition.UNKNOWN: NodeState.UNKNOWN,
    }
    return mapping[condition]
