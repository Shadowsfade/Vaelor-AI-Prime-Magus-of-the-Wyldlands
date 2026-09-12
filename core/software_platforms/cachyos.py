"""CachyOS/Arch implementation of the software platform boundary."""
from __future__ import annotations

from pathlib import Path
import os
import platform
import re
import shutil
import shlex
import subprocess
from core.verified_download import download_verified

from core.software_workflow import (
    SoftwareArtifact, SoftwareEnvironment, SoftwarePlan, SoftwareRequest,
    SoftwareSource, run_command,
)

UPSTREAM_SOURCES = {"jq": {"url": "https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64", "version": "1.8.1", "sha256": "020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d", "checksum_url": "https://github.com/jqlang/jq/releases/download/jq-1.8.1/sha256sum.txt"}}
ALIASES = {"ripgrep": "rg", "fd-find": "fd"}


class CachyOSAdapter:
    def detect_environment(self) -> SoftwareEnvironment:
        release = {}
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    release[key] = value.strip().strip('"')
        except OSError:
            pass
        managers = [n for n in ("pacman", "paru", "yay") if shutil.which(n)]
        return SoftwareEnvironment(
            os=release.get("PRETTY_NAME") or platform.system(),
            distribution=release.get("ID", ""), architecture=platform.machine(),
            shell=os.environ.get("SHELL") or shutil.which("bash") or "",
            package_managers=managers, user=os.environ.get("USER") or os.environ.get("USERNAME") or "",
            home=str(Path.home()), privilege_capabilities=["sudo"] if shutil.which("sudo") else [],
        )

    def canonicalize_program(self, request: str) -> SoftwareRequest:
        match = re.search(r"\b(?:download|install|get|setup|set up)\s+([a-z0-9][a-z0-9+._-]*)\b", str(request or "").lower())
        if not match:
            raise ValueError("Could not identify a program name safely.")
        requested = match.group(1)
        return SoftwareRequest(str(request), requested, ALIASES.get(requested, requested))

    def _package_query(self, manager: str, program: str):
        return run_command([manager, "-Si", program], 15)

    def resolve_source(self, request: SoftwareRequest) -> SoftwareSource:
        program = {"rg": "ripgrep", "fd-find": "fd"}.get(request.canonical_name, request.canonical_name)
        executable = shutil.which(request.canonical_name)
        if executable and shutil.which("pacman"):
            rc, info = run_command(["pacman", "-Q", program], 10)
            if rc == 0:
                return SoftwareSource("already_installed", package=program, repository="local package database", version=info, reason="Executable and package are already present; installation skipped.", executable=executable)
        if shutil.which("pacman"):
            rc, info = self._package_query("pacman", program)
            if rc == 0:
                return SoftwareSource("official_repository", package=program, repository="official repository", version=info, reason="Selected the official repository package.")
        for helper in ("paru", "yay"):
            if shutil.which(helper):
                rc, info = self._package_query(helper, program)
                if rc == 0:
                    return SoftwareSource("trusted_community_repository", package=program, repository=f"AUR via {helper}", version=info, helper=helper, reason="Selected the existing trusted community repository helper.")
        if program in UPSTREAM_SOURCES:
            if platform.machine().lower() not in {"amd64", "x86_64"}:
                raise ValueError("No allowlisted upstream artifact for this architecture.")
            item = UPSTREAM_SOURCES[program]
            return SoftwareSource("official_upstream_artifact", package=program, repository="official upstream", version=item["version"], url=item["url"], checksum_sha256=item["sha256"], checksum_url=item["checksum_url"], reason="Selected the allowlisted official upstream artifact.")
        raise ValueError(f"No trusted CachyOS source matched {program!r}.")

    def create_install_plan(self, request, source, work_dir):
        if source.method == "already_installed":
            return SoftwarePlan(actions=["verify"], expected_changes="none", verification_strategy=self.verification_candidates(request))
        if source.method in {"official_repository", "trusted_community_repository"}:
            manager = source.helper or "pacman"
            prefix = "sudo -n " if manager == "pacman" else ""
            command = f"{prefix}{manager} -S --needed --noconfirm {source.package}"
            return SoftwarePlan(actions=["install"], commands=[command], expected_changes="install package", required_privilege="sudo", verification_strategy=self.verification_candidates(request))
        target = work_dir / source.package
        return SoftwarePlan(actions=["download"], commands=[f"download {source.url} to {target}"], expected_changes="create managed artifact", verification_strategy=self.verification_candidates(request))

    def preflight(self, plan):
        if plan.required_privilege == "sudo":
            try:
                rc, _ = run_command(["sudo", "-n", "-v"], 5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f"Sudo authentication unavailable: {exc}"
            if rc != 0:
                return "Installation requires sudo authentication. Authenticate on the host, then continue this task."
        return ""

    def execute_install(self, request, source, plan, work_dir):
        if source.method in {"official_repository", "trusted_community_repository"}:
            manager = source.helper or "pacman"
            command = (["sudo", "-n"] if manager == "pacman" else []) + [manager, "-S", "--needed", "--noconfirm", source.package]
            if not plan.commands or shlex.split(plan.commands[0]) != command:
                raise ValueError("Saved package command differs from the adapter command; review the plan.")
            rc, output = run_command(command, 120)
            return {"returncode": rc, "output": output, "commands": [{"command": plan.commands[0], "returncode": rc, "output": output}]}
        target = work_dir / source.package
        size, checksum = download_verified(source.url, target, source.checksum_sha256)
        artifact = SoftwareArtifact(source=source.url, destination=str(target), filename=target.name, size=size, checksum=checksum)
        return {"returncode": 0, "output": "Downloaded official artifact", "commands": [], "artifacts": [artifact]}

    def find_executable(self, request, source):
        return source.executable or shutil.which(request.canonical_name) or f"/usr/bin/{request.canonical_name}"

    def verification_candidates(self, request):
        return ["--version", "-V", "version", "--help", "-h"]

    def usage_instructions(self, request, executable):
        return f"Launch: {executable} --help"

    def update_instructions(self, source):
        if source.method in {"official_repository", "already_installed"}:
            return "sudo pacman -Syu (updates the system and installed packages)"
        if source.helper:
            return f"{source.helper} -Syu"
        return "Request a new setup using a reviewed official release."

    def removal_instructions(self, source):
        if source.method in {"official_repository", "already_installed", "trusted_community_repository"}:
            return f"sudo pacman -R {source.package}"
        return "Remove the managed artifact listed in this task."
