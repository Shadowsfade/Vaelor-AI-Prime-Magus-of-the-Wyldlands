"""Recovery policy model for Vaelor R0 infrastructure.

Defines bounded recovery policies without executing them.
Observation-only mode must never execute recovery actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RecoveryAction(Enum):
    """Possible recovery actions."""
    RESTART_VAELOR = "restart_vaelor"
    RESTART_TAILSCALE = "restart_tailscale"
    WAKE_ON_LAN = "wake_on_lan"
    NONE = "none"


class RecoveryTrigger(Enum):
    """Conditions that may trigger recovery."""
    VAELOR_UNHEALTHY = "vaelor_unhealthy"
    TAILSCALE_DOWN_HOST_UP = "tailscale_down_host_up"
    HOST_UNREACHABLE = "host_unreachable"


@dataclass(frozen=True)
class RecoveryCandidate:
    """A potential recovery action with its trigger and bounds."""
    action: RecoveryAction
    trigger: RecoveryTrigger
    target_node: str
    attempt: int = 1
    max_attempts: int = 2
    cooldown_seconds: int = 30
    description: str = ""

    def can_retry(self) -> bool:
        return self.attempt < self.max_attempts

    def next_attempt(self) -> "RecoveryCandidate":
        if not self.can_retry():
            raise ValueError(f"Cannot retry: attempt {self.attempt} >= max_attempts {self.max_attempts}")
        return RecoveryCandidate(
            action=self.action,
            trigger=self.trigger,
            target_node=self.target_node,
            attempt=self.attempt + 1,
            max_attempts=self.max_attempts,
            cooldown_seconds=self.cooldown_seconds,
            description=self.description,
        )

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "trigger": self.trigger.value,
            "target_node": self.target_node,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "cooldown_seconds": self.cooldown_seconds,
            "description": self.description,
        }


@dataclass
class RecoveryPolicy:
    """Bounded recovery policy configuration.

    - Maximum 2 automatic attempts per trigger
    - 30 second cooldown between attempts
    - After max attempts: mark UNREACHABLE, preserve evidence, stop
    - Observation-only mode never executes candidates
    """
    max_auto_attempts: int = 2
    default_cooldown_seconds: int = 30
    observation_only: bool = True  # R0.1 is observation-only

    # Trigger -> default action mapping
    trigger_actions: dict = field(default_factory=lambda: {
        RecoveryTrigger.VAELOR_UNHEALTHY: RecoveryAction.RESTART_VAELOR,
        RecoveryTrigger.TAILSCALE_DOWN_HOST_UP: RecoveryAction.RESTART_TAILSCALE,
        RecoveryTrigger.HOST_UNREACHABLE: RecoveryAction.WAKE_ON_LAN,
    })

    def get_candidate(self, trigger: RecoveryTrigger, target_node: str,
                       attempt: int = 1) -> RecoveryCandidate:
        """Get a recovery candidate for a trigger."""
        action = self.trigger_actions.get(trigger, RecoveryAction.NONE)
        return RecoveryCandidate(
            action=action,
            trigger=trigger,
            target_node=target_node,
            attempt=attempt,
            max_attempts=self.max_auto_attempts,
            cooldown_seconds=self.default_cooldown_seconds,
            description=self._describe(trigger, action, target_node, attempt),
        )

    def _describe(self, trigger: RecoveryTrigger, action: RecoveryAction, node: str, attempt: int) -> str:
        if trigger == RecoveryTrigger.VAELOR_UNHEALTHY and action == RecoveryAction.RESTART_VAELOR:
            return f"Restart Vaelor API on {node} (attempt {attempt}/{self.max_auto_attempts})"
        elif trigger == RecoveryTrigger.TAILSCALE_DOWN_HOST_UP and action == RecoveryAction.RESTART_TAILSCALE:
            return f"Restart Tailscale service on {node} (attempt {attempt}/{self.max_auto_attempts})"
        elif trigger == RecoveryTrigger.HOST_UNREACHABLE and action == RecoveryAction.WAKE_ON_LAN:
            return f"Send Wake-on-LAN to {node} (attempt {attempt}/{self.max_auto_attempts})"
        return f"No action defined for {trigger.value}"

    def evaluate(self, observation, vaelor_expected: bool = True) -> list[RecoveryCandidate]:
        """Evaluate an observation and return applicable recovery candidates.

        Does NOT execute them. Only returns candidates for recording.
        """
        candidates = []

        # Vaelor unhealthy but host reachable
        if vaelor_expected and observation.vaelor_health is False and observation.host_reachable is True:
            candidates.append(self.get_candidate(RecoveryTrigger.VAELOR_UNHEALTHY, observation.node))

        # Tailscale down but host locally reachable (via LAN or direct)
        if observation.tailscale_service is False and observation.host_reachable is True:
            candidates.append(self.get_candidate(RecoveryTrigger.TAILSCALE_DOWN_HOST_UP, observation.node))

        # Host unreachable from guardian
        if observation.host_reachable is False:
            candidates.append(self.get_candidate(RecoveryTrigger.HOST_UNREACHABLE, observation.node))

        return candidates

    def execute_candidate(self, candidate: RecoveryCandidate) -> bool:
        """Execute a recovery candidate.

        In observation-only mode (R0.1), this always returns False and does nothing.
        """
        if self.observation_only:
            return False
        # Actual implementation would go here in later R0 slices
        return False


def get_recovery_policy(observation_only: bool = True) -> RecoveryPolicy:
    """Get the current recovery policy."""
    return RecoveryPolicy(observation_only=observation_only)

