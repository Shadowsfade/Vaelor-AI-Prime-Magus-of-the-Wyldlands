"""Narrow service-manager adapter interface for Vaelor R0.2.

One small contract, two implementations:

- ``SystemdUserAdapter`` renders/validates a user unit and plans exact
  argv for start/stop/restart/status. It never installs or enables the
  real service; installation requires explicit operator approval.
- ``WindowsServiceAdapter`` represents the existing persistent
  launcher/service arrangement and plans deterministic commands. It does
  NOT claim to validate Windows behavior when running on Linux, and it
  never touches a remote Windows host.

Every plan is an argv tuple, never an interpolated shell string.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence


class AdapterError(RuntimeError):
    """Raised when an adapter cannot produce a valid plan."""


@dataclass(frozen=True)
class ServicePlan:
    """A deterministic, inspectable plan for one service operation."""

    operation: str            # start | stop | restart | status | render | install
    argv: tuple
    adapter: str
    dry_run_only: bool = False
    notes: str = ""

    @property
    def command(self) -> str:
        return " ".join(self.argv)

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "argv": list(self.argv),
            "adapter": self.adapter,
            "dry_run_only": self.dry_run_only,
            "notes": self.notes,
            "command": self.command,
        }


class ServiceManagerAdapter:
    """The narrow contract every service manager implements."""

    name = "base"

    def plan(self, operation: str, *, unit: str) -> ServicePlan:
        raise NotImplementedError

    def render(self) -> str:
        raise NotImplementedError

    def validate(self) -> list:
        """Return a list of problems; empty means valid."""
        raise NotImplementedError

    def status(self) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# systemd --user
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=Vaelor local service (guarded)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={worktree}
ExecStart={exec_start}
Restart=no
# The out-of-process guardian owns restart policy; systemd must not race it.
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=default.target
"""


@dataclass
class SystemdUserAdapter(ServiceManagerAdapter):
    """Plans systemd --user operations without ever installing them."""

    name = "systemd-user"
    unit_name: str = "vaelor.service"
    worktree: Path = field(default_factory=Path)
    python_executable: Optional[str] = None   # None -> resolve the venv
    entry_script: str = "vaelor.py"
    # The unit brings the *guardian* up at login — not the interactive
    # CLI and not the API directly. The guardian owns restart policy for
    # the API child. Running ``vaelor.py`` with no arguments blocks on
    # the interactive ``input()`` prompt and supervises nothing.
    entry_args: tuple = ("infra", "guardian", "run")
    systemctl: str = "systemctl"
    dry_run: bool = True          # installation requires explicit approval

    def __post_init__(self):
        self.worktree = Path(self.worktree)
        if self.python_executable is None:
            self.python_executable = self._resolve_python()

    def _resolve_python(self) -> str:
        """Prefer the worktree venv interpreter.

        Bare ``python`` is the *system* interpreter, which does not have
        the application's dependencies — the supervised child imports
        ``uvicorn`` — so a unit started with it would bring up a
        guardian that can never bring up the API. An explicit value is
        always honoured; ``None`` means auto-resolve.
        """
        for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
            candidate = self.worktree / rel
            if candidate.exists():
                return str(candidate)
        return "python"

    # -- rendering -------------------------------------------------------
    def exec_start(self) -> str:
        # systemd requires a single string; each element is a fixed,
        # repository-owned token. Nothing model-supplied is interpolated.
        return " ".join(
            [self.python_executable, self.entry_script, *self.entry_args]
        )

    def render(self) -> str:
        return SYSTEMD_UNIT_TEMPLATE.format(
            worktree=str(self.worktree),
            exec_start=self.exec_start(),
        )

    def validate(self) -> list:
        problems = []
        if not str(self.worktree):
            problems.append("worktree path is empty")
        if not self.unit_name.endswith(".service"):
            problems.append("unit_name must end with .service")
        if ".." in self.unit_name or "/" in self.unit_name:
            problems.append("unit_name must be a bare unit name")
        if not self.python_executable:
            problems.append("python_executable is empty")
        if not self.entry_script.endswith(".py"):
            problems.append("entry_script must be a .py file")
        if not self.worktree.exists():
            problems.append(f"worktree does not exist: {self.worktree}")
        return problems

    # -- planning --------------------------------------------------------
    def plan(self, operation: str, *, unit: Optional[str] = None) -> ServicePlan:
        unit = unit or self.unit_name
        problems = self.validate()
        if problems:
            raise AdapterError("; ".join(problems))

        if operation == "render":
            return ServicePlan(
                operation="render",
                argv=("<rendered-unit>",),
                adapter=self.name,
                dry_run_only=True,
                notes="prints the unit definition; writes nothing",
            )

        if operation in ("start", "stop", "restart", "status"):
            argv = (self.systemctl, "--user", operation, unit)
            return ServicePlan(
                operation=operation,
                argv=argv,
                adapter=self.name,
                dry_run_only=False,
                notes="plans the exact argv; execution is a separate, "
                      "explicitly-approved step",
            )

        if operation == "install":
            # Deliberately refused: installing or enabling a real service
            # requires explicit user approval in this milestone.
            return ServicePlan(
                operation="install",
                argv=("<refused>",),
                adapter=self.name,
                dry_run_only=True,
                notes="service installation requires explicit operator approval; "
                      "plan only, never executed automatically",
            )

        if operation == "daemon-reload":
            return ServicePlan(
                operation="daemon-reload",
                argv=(self.systemctl, "--user", "daemon-reload"),
                adapter=self.name,
                dry_run_only=False,
                notes="reload user unit cache after writing a unit file",
            )

        raise AdapterError(f"unsupported operation: {operation}")

    def status(self) -> dict:
        return {
            "adapter": self.name,
            "unit": self.unit_name,
            "dry_run": self.dry_run,
            "validated": not self.validate(),
            "problems": self.validate(),
            "installed": False,
            "note": "no real service is installed or enabled by this adapter",
        }


# ---------------------------------------------------------------------------
# Windows (contract + planning only)
# ---------------------------------------------------------------------------

@dataclass
class WindowsServiceAdapter(ServiceManagerAdapter):
    """Represents the existing Windows persistent launcher arrangement.

    This adapter only *plans*. Running on Linux it will report
    ``platform_supported=False`` rather than pretending to validate
    Windows service behavior. It never modifies a remote Windows host.
    """

    name = "windows-service"
    unit_name: str = "Vaelor"
    launcher: str = "vaelor_launcher.exe"
    sc_executable: str = "sc.exe"
    platform_supported: bool = False

    def render(self) -> str:
        # Declarative description of the existing arrangement, not a
        # payload that is ever written anywhere automatically.
        return (
            "# Windows persistent launcher arrangement (described, not installed)\n"
            f"# Service name: {self.unit_name}\n"
            f"# Launcher: {self.launcher}\n"
            "# Existing arrangement is managed outside this repository.\n"
        )

    def validate(self) -> list:
        problems = []
        if not self.unit_name:
            problems.append("service name is empty")
        if any(c in self.unit_name for c in " \t/\\"):
            problems.append("service name must not contain spaces or slashes")
        if not self.launcher:
            problems.append("launcher path is empty")
        return problems

    def plan(self, operation: str, *, unit: Optional[str] = None) -> ServicePlan:
        unit = unit or self.unit_name
        problems = self.validate()
        if problems:
            raise AdapterError("; ".join(problems))

        supported = {"start", "stop", "restart", "status"}
        if operation not in supported:
            raise AdapterError(f"unsupported operation: {operation}")

        argv = (self.sc_executable, operation if operation != "restart" else "control",
                unit) if operation != "restart" else (
            self.sc_executable, "control", unit, "restart")

        return ServicePlan(
            operation=operation,
            argv=argv,
            adapter=self.name,
            dry_run_only=True,
            notes=(
                "plan only; Windows service behavior cannot be validated from "
                f"this platform (platform_supported={self.platform_supported})"
            ),
        )

    def status(self) -> dict:
        return {
            "adapter": self.name,
            "unit": self.unit_name,
            "platform_supported": self.platform_supported,
            "validated": False,
            "problems": self.validate(),
            "note": "contract only; no Windows host is contacted or modified",
        }


def select_adapter(system: str) -> ServiceManagerAdapter:
    """Pick an adapter for the current OS. Unknown systems fail closed."""
    lowered = (system or "").lower()
    if lowered.startswith("linux"):
        return SystemdUserAdapter()
    if lowered.startswith("win"):
        return WindowsServiceAdapter(platform_supported=True)
    raise AdapterError(f"no service manager adapter for platform: {system!r}")


def find_executable(name: str) -> Optional[str]:
    """Locate an executable on PATH without invoking a shell."""
    return shutil.which(name)
