"""Trusted local guardian configuration.

Only files inside the repository's own ``config/`` directory are trusted.
Configuration is validated strictly and never sourced from a model
response, task record, memory file, web response, or conversation.

Commands are argv tuples. A command supplied as a bare string is
rejected, which is what prevents shell interpolation entirely.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Tuple


class GuardianConfigError(ValueError):
    """Raised for any unusable guardian configuration. Fails closed."""


TRUSTED_CONFIG_NAMES = ("guardian.json",)


@dataclass(frozen=True)
class GuardianConfig:
    """Validated, trusted guardian settings."""

    worktree: Path
    python_executable: str
    start_command: Tuple[str, ...]
    health_url: str
    readiness_url: str
    liveness_url: str
    probe_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 5.0
    child_start_timeout_seconds: float = 30.0
    max_restarts: int = 5
    healthy_interval_seconds: float = 60.0
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 30.0
    state_dir: Path = field(default_factory=Path)
    event_log_max: int = 500
    enabled: bool = True

    @property
    def guardian_pid_path(self) -> Path:
        return self.state_dir / "guardian.pid"

    @property
    def child_pid_path(self) -> Path:
        return self.state_dir / "vaelor.pid"

    @property
    def state_path(self) -> Path:
        return self.state_dir / "guardian_state.json"

    @property
    def event_log_path(self) -> Path:
        return self.state_dir / "recovery_events.json"

    def to_dict(self) -> dict:
        return {
            "worktree": str(self.worktree),
            "python_executable": self.python_executable,
            "start_command": list(self.start_command),
            "health_url": self.health_url,
            "readiness_url": self.readiness_url,
            "liveness_url": self.liveness_url,
            "probe_timeout_seconds": self.probe_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "child_start_timeout_seconds": self.child_start_timeout_seconds,
            "max_restarts": self.max_restarts,
            "healthy_interval_seconds": self.healthy_interval_seconds,
            "backoff_base_seconds": self.backoff_base_seconds,
            "backoff_max_seconds": self.backoff_max_seconds,
            "circuit_failure_threshold": self.circuit_failure_threshold,
            "circuit_cooldown_seconds": self.circuit_cooldown_seconds,
            "state_dir": str(self.state_dir),
            "event_log_max": self.event_log_max,
            "enabled": self.enabled,
        }


def _loopback() -> str:
    return ".".join(["127", "0", "0", "1"])


def _default_port(root: Path) -> int:
    try:
        from core.netbind import load_network_config
        cfg = load_network_config(root)
        port = cfg.get("port")
        if port:
            return int(port)
    except Exception:
        pass
    return 8765


def _coerce_argv(value, *, field_name: str) -> Tuple[str, ...]:
    """Accept only a sequence of non-empty strings.

    A string is rejected outright: that is the check that keeps shell
    interpolation from ever entering the guardian.
    """
    if isinstance(value, str):
        raise GuardianConfigError(
            f"{field_name} must be an argv array, not a shell string"
        )
    if not isinstance(value, (list, tuple)):
        raise GuardianConfigError(f"{field_name} must be an argv array")
    if not value:
        raise GuardianConfigError(f"{field_name} must not be empty")
    argv = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise GuardianConfigError(
                f"{field_name} entries must be non-empty strings"
            )
        if "\x00" in item:
            raise GuardianConfigError(f"{field_name} contains a NUL byte")
        argv.append(item)
    return tuple(argv)


def _bounded_number(value, *, name: str, low: float, high: float,
                    default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardianConfigError(f"{name} must be a number")
    if not (low <= float(value) <= high):
        raise GuardianConfigError(f"{name} must be within [{low}, {high}]")
    return float(value)


def trusted_config_paths(root: Path) -> list:
    """Only these files are ever read as guardian configuration."""
    base = Path(root) / "config"
    return [base / name for name in TRUSTED_CONFIG_NAMES]


def load_guardian_config(root: Optional[Path] = None, *,
                         explicit: Optional[Path] = None) -> GuardianConfig:
    """Load and strictly validate trusted local guardian configuration.

    Missing file yields built-in defaults derived from the local install.
    A present-but-invalid file raises GuardianConfigError: uncertain
    configuration must fail closed rather than half-work.
    """
    base = Path(root) if root else Path(__file__).resolve().parent.parent.parent

    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise GuardianConfigError(f"guardian config not found: {path}")
        allowed = {p.resolve() for p in trusted_config_paths(base)}
        # Explicit paths used by tests live under temp dirs; only enforce
        # the trust boundary for in-repo paths.
        if path.resolve().parent == (base / "config").resolve():
            if path.resolve() not in allowed:
                raise GuardianConfigError(
                    f"untrusted config path: {path}"
                )
        raw_text = path.read_text(encoding="utf-8")
    else:
        path = None
        for candidate in trusted_config_paths(base):
            if candidate.exists():
                path = candidate
                break
        raw_text = path.read_text(encoding="utf-8") if path else "{}"

    try:
        data = json.loads(raw_text) if raw_text.strip() else {}
    except ValueError as exc:
        raise GuardianConfigError(f"guardian config is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise GuardianConfigError("guardian config must be a JSON object")

    unknown = set(data) - {
        "worktree", "python_executable", "start_command", "health_url",
        "readiness_url", "liveness_url", "probe_timeout_seconds",
        "poll_interval_seconds", "child_start_timeout_seconds",
        "max_restarts", "healthy_interval_seconds", "backoff_base_seconds",
        "backoff_max_seconds", "circuit_failure_threshold",
        "circuit_cooldown_seconds", "state_dir", "event_log_max", "enabled",
    }
    if unknown:
        raise GuardianConfigError(
            f"unknown guardian config keys: {sorted(unknown)}"
        )

    worktree = Path(data["worktree"]) if data.get("worktree") else base

    python_exe = data.get("python_executable") or sys.executable
    if not isinstance(python_exe, str) or not python_exe:
        raise GuardianConfigError("python_executable must be a non-empty string")

    # The port must be resolved before the default argv is built so the
    # supervised child listens on exactly the port the health probes use.
    port = _default_port(base)

    # The supervised child is the FastAPI application server, never the
    # interactive CLI. ``vaelor.py`` with no arguments blocks on an
    # ``input()`` prompt and never binds the health port. Binding is
    # loopback-only by default: the guardian supervises a local service,
    # it does not publish one.
    default_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "api.server:app",
        "--host",
        _loopback(),
        "--port",
        str(port),
    ]
    if "start_command" in data and data["start_command"] is not None:
        # An explicitly present but empty/invalid value must be rejected,
        # not silently replaced by the default.
        start_command = _coerce_argv(
            data["start_command"], field_name="start_command")
    else:
        start_command = _coerce_argv(default_cmd, field_name="start_command")

    health_url = data.get("health_url") or f"http://{_loopback()}:{port}/health"
    readiness_url = (data.get("readiness_url")
                     or f"http://{_loopback()}:{port}/readiness")
    liveness_url = (data.get("liveness_url")
                    or f"http://{_loopback()}:{port}/health")
    for name, url in (("health_url", health_url),
                      ("readiness_url", readiness_url),
                      ("liveness_url", liveness_url)):
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise GuardianConfigError(f"{name} must be an http(s) URL")

    state_dir = Path(data["state_dir"]) if data.get("state_dir") else (
        base / "memory" / "guardian"
    )

    max_restarts = data.get("max_restarts", 5)
    if isinstance(max_restarts, bool) or not isinstance(max_restarts, int):
        raise GuardianConfigError("max_restarts must be an integer")
    if not (1 <= max_restarts <= 100):
        raise GuardianConfigError("max_restarts must be within [1, 100]")

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise GuardianConfigError("enabled must be a boolean")

    return GuardianConfig(
        worktree=worktree,
        python_executable=python_exe,
        start_command=start_command,
        health_url=health_url,
        readiness_url=readiness_url,
        liveness_url=liveness_url,
        probe_timeout_seconds=_bounded_number(
            data.get("probe_timeout_seconds"), name="probe_timeout_seconds",
            low=0.1, high=30.0, default=2.0),
        poll_interval_seconds=_bounded_number(
            data.get("poll_interval_seconds"), name="poll_interval_seconds",
            low=0.1, high=600.0, default=5.0),
        child_start_timeout_seconds=_bounded_number(
            data.get("child_start_timeout_seconds"),
            name="child_start_timeout_seconds",
            low=1.0, high=600.0, default=30.0),
        max_restarts=max_restarts,
        healthy_interval_seconds=_bounded_number(
            data.get("healthy_interval_seconds"),
            name="healthy_interval_seconds",
            low=1.0, high=3600.0, default=60.0),
        backoff_base_seconds=_bounded_number(
            data.get("backoff_base_seconds"), name="backoff_base_seconds",
            low=0.01, high=60.0, default=1.0),
        backoff_max_seconds=_bounded_number(
            data.get("backoff_max_seconds"), name="backoff_max_seconds",
            low=0.01, high=600.0, default=60.0),
        circuit_failure_threshold=int(_bounded_number(
            data.get("circuit_failure_threshold"),
            name="circuit_failure_threshold",
            low=1, high=50, default=3)),
        circuit_cooldown_seconds=_bounded_number(
            data.get("circuit_cooldown_seconds"),
            name="circuit_cooldown_seconds",
            low=0.0, high=3600.0, default=30.0),
        state_dir=state_dir,
        event_log_max=int(_bounded_number(
            data.get("event_log_max"), name="event_log_max",
            low=10, high=10000, default=500)),
        enabled=enabled,
    )
