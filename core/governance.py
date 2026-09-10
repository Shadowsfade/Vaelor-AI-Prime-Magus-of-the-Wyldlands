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
from datetime import datetime, timezone
from typing import Any, Mapping
import secrets
import subprocess
import threading


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
    _nonce: str = ""


_ISSUED: dict[str, ActionAuthorization] = {}
_ISSUED_LOCK = threading.Lock()
_MAX_ISSUED = 4096


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("malformed authorization expiry")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed authorization expiry") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("authorization timestamps must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _authorization_now() -> datetime:
    return datetime.now(timezone.utc)


def _prune_expired_locked(now: datetime) -> int:
    removed = 0
    for nonce, authorization in list(_ISSUED.items()):
        expires = _parse_utc_timestamp(authorization.expires_at)
        if expires is not None and expires <= now:
            _ISSUED.pop(nonce, None)
            removed += 1
    return removed


def issue_authorization(fingerprint: str, actor: str, issued_at: str,
                        expires_at: str | None = None) -> ActionAuthorization:
    try:
        issued = _parse_utc_timestamp(issued_at)
    except ValueError:
        # Legacy callers supplied opaque issuance labels; expiry remains strict.
        issued = None
    expires = _parse_utc_timestamp(expires_at)
    if expires is not None and issued is not None and expires <= issued:
        raise ValueError("authorization expiry must be after issuance")
    nonce = secrets.token_urlsafe(24)
    with _ISSUED_LOCK:
        _prune_expired_locked(_authorization_now())
        if len(_ISSUED) >= _MAX_ISSUED:
            raise RuntimeError("runtime authorization capacity exhausted")
        value = ActionAuthorization(fingerprint, actor, issued_at, expires_at, nonce)
        _ISSUED[nonce] = value
        return value


def is_runtime_authorization(value: ActionAuthorization | None) -> bool:
    with _ISSUED_LOCK:
        if not isinstance(value, ActionAuthorization) or not value._nonce:
            return False
        stored = _ISSUED.get(value._nonce)
        if stored is None:
            return False
        expires = _parse_utc_timestamp(stored.expires_at)
        if expires is not None and expires <= _authorization_now():
            _ISSUED.pop(value._nonce, None)
            return False
        return True


def consume_runtime_authorization(value: ActionAuthorization) -> None:
    with _ISSUED_LOCK:
        _ISSUED.pop(value._nonce, None)


def claim_runtime_authorization(value: ActionAuthorization, fingerprint: str) -> bool:
    """Atomically validate and consume a capability before dispatch."""
    with _ISSUED_LOCK:
        stored = _ISSUED.get(getattr(value, "_nonce", ""))
        if stored is None or stored.fingerprint != fingerprint or value.fingerprint != fingerprint:
            return False
        expires = _parse_utc_timestamp(stored.expires_at)
        if expires is not None and expires <= _authorization_now():
            _ISSUED.pop(value._nonce, None)
            return False
        _ISSUED.pop(value._nonce, None)
        return True


def _reset_runtime_authorizations_for_tests() -> None:
    """Private test reset; never reachable from model/tool input."""
    with _ISSUED_LOCK:
        _ISSUED.clear()


@dataclass(frozen=True)
class GovernedInvocation:
    tool: str
    arguments: Mapping[str, Any]
    target: str = ""
    scope: str = ""
    effects: str = ""
    state: str = ""
    task_id: str = ""
    step_id: str = ""
    provenance: tuple[str, ...] = ()


def bound_action_fingerprint(tool: str, arguments: Mapping[str, Any], *, target: str = "",
                             scope: str = "", effects: str = "", state: str = "",
                             task_id: str = "", step_id: str = "",
                             provenance: tuple[str, ...] = ()) -> str:
    payload = {"tool": tool, "arguments": dict(arguments), "target": target,
               "scope": scope, "effects": effects, "state": state,
               "task_id": task_id, "step_id": step_id,
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
                payload.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                               type="file" if os.path.isfile(full) else "directory" if os.path.isdir(full) else "other")
                if os.path.isfile(full) and stat.st_size <= 2_000_000:
                    with open(full, "rb") as handle:
                        payload["sha256"] = hashlib.sha256(handle.read()).hexdigest()
            else:
                payload["exists"] = False
        except (OSError, ValueError):
            payload["unavailable"] = True
    elif "command" in arguments:
        payload["command"] = str(arguments["command"])
        cwd = str(arguments.get("cwd") or os.getcwd())
        if any(token in payload["command"] for token in ("git ", "git\t")):
            try:
                root = subprocess.check_output(["git", "-C", cwd, "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL).strip()
                head = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
                branch = subprocess.check_output(["git", "-C", root, "symbolic-ref", "--short", "-q", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip() or "DETACHED"
                status = subprocess.check_output(["git", "-C", root, "status", "--porcelain=v1"], text=True, stderr=subprocess.DEVNULL)
                payload.update(repository=os.path.realpath(root), head=head, branch=branch,
                               status_sha256=hashlib.sha256(status.encode()).hexdigest())
            except (OSError, subprocess.SubprocessError):
                payload["state_adapter"] = "unavailable"
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mutation_supported(evidence: tuple[EvidenceProvenance, ...]) -> bool:
    return bool(evidence) and all(
        item.source in {EvidenceSource.CURRENT_TOOL, EvidenceSource.CURRENT_STATE,
                        EvidenceSource.VERIFIED_RESULT}
        and item.trust == "validated" and not item.quarantined
        and item.may_influence_mutation for item in evidence
    )
