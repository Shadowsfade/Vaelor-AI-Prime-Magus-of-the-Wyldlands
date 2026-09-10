"""Small provider-independent governance primitives for Vaelor actions.

These values are deliberately declarative.  They do not grant permission by
themselves; the task/approval boundary remains the authority for execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from typing import Any, Mapping


class EvidenceSource(str, Enum):
    CURRENT_TOOL = "current_tool"
    CURRENT_STATE = "current_state"
    USER_SUPPLIED = "user_supplied"
    HISTORICAL_TASK = "historical_task"
    HISTORICAL_CONVERSATION = "historical_conversation"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"
    VERIFIED_RESULT = "verified_result"


@dataclass(frozen=True)
class EvidenceProvenance:
    evidence_id: str
    source: EvidenceSource
    origin: str
    observed_at: str
    trust: str = "unverified"
    quarantined: bool = False
    integrity_ref: str | None = None
    may_influence_mutation: bool = False

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.origin.strip():
            raise ValueError("evidence identity is required")
        if self.quarantined and self.may_influence_mutation:
            raise ValueError("quarantined evidence cannot influence mutation")


@dataclass(frozen=True)
class ActionAuthorization:
    fingerprint: str
    actor: str
    issued_at: str
    expires_at: str | None = None


def bound_action_fingerprint(tool: str, arguments: Mapping[str, Any], *, target: str = "",
                             scope: str = "", effects: str = "", state: str = "",
                             provenance: tuple[str, ...] = ()) -> str:
    payload = {"tool": tool, "arguments": dict(arguments), "target": target,
               "scope": scope, "effects": effects, "state": state,
               "provenance": tuple(provenance)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def current_state_binding(tool: str, arguments: Mapping[str, Any]) -> str:
    """Derive a trusted, bounded binding for common local mutation targets."""
    path = arguments.get("path") or arguments.get("target")
    payload: dict[str, Any] = {"tool": str(tool), "cwd": os.getcwd()}
    if path:
        try:
            full = os.path.abspath(os.path.expanduser(str(path)))
            payload["path"] = full
            if os.path.exists(full):
                stat = os.stat(full)
                payload.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                if os.path.isfile(full) and stat.st_size <= 2_000_000:
                    with open(full, "rb") as handle:
                        payload["sha256"] = hashlib.sha256(handle.read()).hexdigest()
            else:
                payload["exists"] = False
        except (OSError, ValueError):
            payload["unavailable"] = True
    elif "command" in arguments:
        payload["command"] = str(arguments["command"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mutation_supported(evidence: tuple[EvidenceProvenance, ...]) -> bool:
    return bool(evidence) and all(
        item.source in {EvidenceSource.CURRENT_TOOL, EvidenceSource.CURRENT_STATE,
                        EvidenceSource.VERIFIED_RESULT}
        and item.trust == "validated" and not item.quarantined
        and item.may_influence_mutation for item in evidence
    )
