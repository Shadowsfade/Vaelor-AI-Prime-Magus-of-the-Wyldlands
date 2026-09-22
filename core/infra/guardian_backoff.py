"""Restart backoff, budget, and circuit-breaker policy for the guardian.

Pure logic with an injectable clock so tests can drive time deterministically.
No sleeping, no process control, no I/O lives here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class CircuitState(Enum):
    CLOSED = "CLOSED"            # normal operation, restarts allowed
    OPEN = "OPEN"                # tripped: restarts suppressed
    HALF_OPEN = "HALF_OPEN"      # probing after cooldown


@dataclass
class BackoffPolicy:
    """Exponential backoff with jitter and a hard ceiling."""

    base_seconds: float = 1.0
    factor: float = 2.0
    max_seconds: float = 60.0
    jitter_ratio: float = 0.25   # +/- 25%

    def delay_for(self, attempt: int, rng: Optional[random.Random] = None) -> float:
        """Delay before attempt N (1-based), with bounded jitter.

        Jitter prevents a thundering herd when several guardians or
        children recover at the same instant.
        """
        if attempt < 1:
            attempt = 1
        raw = self.base_seconds * (self.factor ** (attempt - 1))
        capped = min(raw, self.max_seconds)
        if self.jitter_ratio <= 0:
            return capped
        r = rng or random
        spread = capped * self.jitter_ratio
        jittered = capped + r.uniform(-spread, spread)
        return max(0.0, min(jittered, self.max_seconds))


@dataclass
class RestartBudget:
    """Bounded restart allowance that only resets after sustained health."""

    max_restarts: int = 5
    healthy_interval_seconds: float = 60.0
    used: int = 0
    exhausted: bool = False

    def consume(self) -> bool:
        """Take one restart slot. Returns False when the budget is spent."""
        if self.exhausted or self.used >= self.max_restarts:
            self.exhausted = True
            return False
        self.used += 1
        if self.used >= self.max_restarts:
            self.exhausted = True
        return True

    def reset(self) -> None:
        self.used = 0
        self.exhausted = False

    @property
    def remaining(self) -> int:
        return max(0, self.max_restarts - self.used)

    def to_dict(self) -> dict:
        return {
            "max_restarts": self.max_restarts,
            "used": self.used,
            "remaining": self.remaining,
            "exhausted": self.exhausted,
            "healthy_interval_seconds": self.healthy_interval_seconds,
        }


@dataclass
class CircuitBreaker:
    """Opens after repeated failures; half-opens after a cooldown."""

    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: Optional[float] = None

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if self.state is CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.opened_at = None
        elif self.state is CircuitState.OPEN:
            self.state = CircuitState.CLOSED
            self.opened_at = None

    def record_failure(self, now: float) -> None:
        self.consecutive_failures += 1
        if self.state is CircuitState.HALF_OPEN:
            # A failed probe re-opens immediately.
            self.state = CircuitState.OPEN
            self.opened_at = now
        elif self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now

    def allow(self, now: float) -> bool:
        """Whether an action may proceed at ``now``."""
        if self.state is CircuitState.CLOSED:
            return True
        if self.state is CircuitState.OPEN:
            if self.opened_at is None:
                return False
            if now - self.opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN: allow exactly one probe; callers gate with in_flight.
        return True

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "opened_at": self.opened_at,
        }


@dataclass
class RecoveryController:
    """Combines budget + backoff + breaker behind one deterministic API.

    ``clock`` is injectable; tests pass a fake to avoid real waiting.
    ``rng`` is injectable so jitter is reproducible under test.
    """

    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    budget: RestartBudget = field(default_factory=RestartBudget)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    clock: Callable[[], float] = field(default=lambda: __import__("time").monotonic)
    rng: Optional[random.Random] = None

    _healthy_since: Optional[float] = field(default=None, init=False, repr=False)

    @property
    def blocked_reason(self) -> Optional[str]:
        """Why a restart is currently refused, or None if allowed."""
        now = self.clock()
        if not self.breaker.allow(now):
            return f"circuit breaker {self.breaker.state.value}"
        if self.budget.exhausted:
            return "restart budget exhausted"
        return None

    def can_restart(self) -> bool:
        return self.blocked_reason is None

    def next_delay(self) -> float:
        return self.backoff.delay_for(self.budget.used + 1, rng=self.rng)

    def on_restart_attempt(self) -> bool:
        """Reserve a budget slot for an attempted restart."""
        return self.budget.consume()

    def on_child_success(self) -> None:
        """Child started and stayed up long enough to count as healthy."""
        self.breaker.record_success()
        self._healthy_since = self.clock()

    def on_child_failure(self) -> None:
        now = self.clock()
        self.breaker.record_failure(now)
        self._healthy_since = None

    def tick_healthy(self, now: Optional[float] = None) -> bool:
        """Advance sustained-health tracking.

        Returns True when the healthy interval elapsed and the budget was
        consequently reset. Repeated crash loops therefore cannot be
        laundered into an infinite restart loop by briefly surviving.
        """
        now = self.clock() if now is None else now
        if self._healthy_since is None:
            return False
        if now - self._healthy_since >= self.budget.healthy_interval_seconds:
            if self.budget.used or self.budget.exhausted:
                self.budget.reset()
            self._healthy_since = now
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "backoff": {
                "base_seconds": self.backoff.base_seconds,
                "factor": self.backoff.factor,
                "max_seconds": self.backoff.max_seconds,
                "jitter_ratio": self.backoff.jitter_ratio,
                "next_delay_seconds": round(self.next_delay(), 3),
            },
            "budget": self.budget.to_dict(),
            "circuit_breaker": self.breaker.to_dict(),
            "blocked_reason": self.blocked_reason,
        }
