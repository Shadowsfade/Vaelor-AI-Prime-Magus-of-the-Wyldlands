"""Recovery authority matrix for Vaelor R0.2.

Deterministic, trusted-code policy that separates what the guardian may do
on its own from what must be diagnosed or approved by the operator.

This module only *decides*. It never executes anything itself, so a policy
evaluation is always side-effect free and safe to call from tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Authority(Enum):
    """Who is allowed to perform a given action."""

    AUTOMATIC = "AUTOMATIC"          # guardian may do this unattended
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"  # needs explicit operator approval
    DIAGNOSE_ONLY = "DIAGNOSE_ONLY"  # observe/report, never mutate


@dataclass(frozen=True)
class RecoveryDecision:
    """Outcome of consulting the authority matrix."""

    action: str
    authority: Authority
    reason: str
    command: Optional[tuple] = None  # exact argv, never a shell string
    reversible: bool = True

    @property
    def may_auto_execute(self) -> bool:
        return self.authority is Authority.AUTOMATIC

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "authority": self.authority.value,
            "reason": self.reason,
            "command": list(self.command) if self.command else None,
            "reversible": self.reversible,
            "may_auto_execute": self.may_auto_execute,
        }


# ---------------------------------------------------------------------------
# Explicit authority sets. Membership here IS the policy; there is no
# inference from strings at call time.
# ---------------------------------------------------------------------------

# Actions the guardian may perform unattended on the local machine.
AUTOMATIC_ACTIONS = frozenset({
    "restart_local_vaelor",
    "start_local_vaelor",
    "stop_local_vaelor",
    "clear_stale_pid",
    "rotate_guardian_state",
})

# Actions that must never run unattended, no matter how healthy the host is.
APPROVAL_REQUIRED_ACTIONS = frozenset({
    "install_tailscale",
    "configure_tailscale",
    "restart_tailscale",
    "change_firewall",
    "install_system_package",
    "repair_credentials",
    "wake_on_lan",
    "power_on_remote_host",
    "reboot_host",
    "shutdown_host",
    "install_windows_service",
    "install_systemd_service",
    "enable_systemd_service",
    "modify_canonical_git",
    "run_unknown_command",
    "restart_unrelated_service",
    "reboot_after_crash_loop",
})

# Reasons that force a decision to DIAGNOSE_ONLY regardless of the action.
DIAGNOSTIC_BLOCKERS = (
    "ambiguous_node_identity",
    "contradictory_evidence",
    "repeated_crash_loop",
    "host_unreachable",
    "stale_state_uncertain",
    "missing_configuration",
    "unknown_command_source",
)


@dataclass
class RecoveryAuthorityMatrix:
    """Deterministic policy lookup with fail-closed defaults.

    Anything not explicitly enumerated is treated as unknown and therefore
    approval-required. This keeps new or malformed inputs from ever landing
    in the automatic bucket.
    """

    automatic: frozenset = AUTOMATIC_ACTIONS
    approval_required: frozenset = APPROVAL_REQUIRED_ACTIONS
    crash_loop_threshold: int = 3
    decisions: list = field(default_factory=list)

    def consult(self, action: str, *,
                blockers: Optional[list] = None,
                command: Optional[tuple] = None,
                source: str = "guardian",
                reversible: bool = True) -> RecoveryDecision:
        """Resolve authority for one action.

        ``blockers`` are reason codes from DIAGNOSTIC_BLOCKERS (or any
        string); a non-empty list forces DIAGNOSE_ONLY.

        ``source`` records where the action came from. Anything other than
        a trusted local origin is approval-required, which is how commands
        suggested by a model, task, memory record, web response, or
        conversation are rejected.
        """
        blockers = list(blockers or [])

        if source != "guardian":
            blockers.append("unknown_command_source")

        if blockers:
            decision = RecoveryDecision(
                action=action,
                authority=Authority.DIAGNOSE_ONLY,
                reason="; ".join(blockers),
                command=None,
                reversible=reversible,
            )
        elif action in self.approval_required:
            decision = RecoveryDecision(
                action=action,
                authority=Authority.APPROVAL_REQUIRED,
                reason="listed as approval-required by policy",
                command=None,
                reversible=reversible,
            )
        elif action in self.automatic:
            decision = RecoveryDecision(
                action=action,
                authority=Authority.AUTOMATIC,
                reason="listed as automatically recoverable by policy",
                command=command,
                reversible=reversible,
            )
        else:
            # Fail closed: unenumerated actions are never automatic.
            decision = RecoveryDecision(
                action=action,
                authority=Authority.APPROVAL_REQUIRED,
                reason="action not enumerated as automatically recoverable",
                command=None,
                reversible=reversible,
            )

        self.decisions.append(decision)
        return decision

    def is_automatic(self, action: str) -> bool:
        return action in self.automatic

    def history(self) -> list:
        return [d.to_dict() for d in self.decisions]


# Convenience singletons used by the guardian and CLI.
DEFAULT_MATRIX = RecoveryAuthorityMatrix()


def automatic_restart(command: tuple) -> RecoveryDecision:
    """Canonical decision for restarting the configured local service."""
    return DEFAULT_MATRIX.consult(
        "restart_local_vaelor",
        command=command,
        source="guardian",
    )


def requires_approval(action: str, reason: str) -> RecoveryDecision:
    """Build an explicit approval-required decision with a stated reason."""
    return RecoveryDecision(
        action=action,
        authority=Authority.APPROVAL_REQUIRED,
        reason=reason,
        command=None,
    )
