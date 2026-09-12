"""Reviewed Windows CLI tools through exact, per-user WinGet installs."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

from core.software_workflow import SoftwareEnvironment, SoftwareRequest, SoftwareSource, SoftwarePlan, SoftwareArtifact, run_command
from core.verified_download import download_verified

PACKAGES = {"jq": ("jqlang.jq", "jq.exe"), "ripgrep": ("BurntSushi.ripgrep.MSVC", "rg.exe"),
            "git": ("Git.Git", "git.exe")}
ALIASES = {"rg": "ripgrep", **{key.lower(): name for name, (key, _) in PACKAGES.items()}}
JQ_URL = "https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-windows-amd64.exe"
JQ_SHA256 = "a6fc67fedaf9128a3309a1e2ebb8b986aeccf70122ee46d2cb4849e423f0c627"
JQ_CHECKSUM_URL = "https://github.com/jqlang/jq/releases/download/jq-1.8.2/sha256sum.txt"


class WindowsAdapter:
    def detect_environment(self):
        return SoftwareEnvironment("Windows", "windows", platform.machine(),
            shell=shutil.which("pwsh") or shutil.which("powershell") or "",
            package_managers=["winget"] if shutil.which("winget") else [],
            user=os.environ.get("USERNAME", ""), home=str(Path.home()),
            privilege_capabilities=["user_scope"])

    def work_directory(self, environment, task_id):
        return Path(environment.home) / "AppData" / "Local" / "Vaelor" / "tasks" / task_id

    def canonicalize_program(self, request):
        match = re.search(r"\b(?:download|install|get|setup|set up)\s+([a-z0-9][a-z0-9+._-]*)\b", request.lower())
        token = match.group(1) if match else ""
        name = ALIASES.get(token, token)
        if name not in PACKAGES:
            raise ValueError("Supported Windows tools: jq, ripgrep (rg), and git. Specify one tool explicitly.")
        return SoftwareRequest(request, token, name)

    def resolve_source(self, request):
        package, executable = PACKAGES[request.canonical_name]
        installed = self.find_executable(request, SoftwareSource("", package=package))
        if installed:
            return SoftwareSource("already_installed", package=package, repository="local executable",
                                  executable=installed, reason="Executable already present; verify without reinstalling.")
        winget = shutil.which("winget")
        if winget:
            rc, output = run_command([winget, "show", "--id", package, "--exact", "--source", "winget",
                                      "--scope", "user", "--disable-interactivity"], 30)
            version = re.search(r"(?m)^Version:\s*([\w.+-]+)\s*$", output)
            if rc == 0 and package in output and version:
                return SoftwareSource("winget", package=package, repository="winget", version=version.group(1),
                    helper=winget, reason="Exact reviewed WinGet ID and version; user scope, no elevation or hash bypass.")
        if request.canonical_name == "jq" and platform.machine().lower() in {"amd64", "x86_64"}:
            return SoftwareSource("official_upstream_artifact", package="jq.exe", repository="official upstream",
                version="1.8.2", url=JQ_URL, checksum_sha256=JQ_SHA256, checksum_url=JQ_CHECKSUM_URL,
                reason="Verified official portable jq binary; stored in this task's managed directory.")
        raise ValueError("WinGet could not resolve a noninteractive per-user package/version. Check App Installer and source agreements on the host.")

    def install_command(self, source):
        if source.package not in {item[0] for item in PACKAGES.values()} or not re.fullmatch(r"[\w.+-]+", source.version):
            raise ValueError("Unreviewed WinGet package or missing exact version.")
        executable = shutil.which("winget")
        if not executable or source.helper != executable:
            raise ValueError("WinGet executable changed or is unavailable; prepare a fresh plan.")
        return [executable, "install", "--id", source.package, "--exact", "--version", source.version,
                "--source", "winget", "--scope", "user", "--silent", "--disable-interactivity",
                "--accept-package-agreements", "--accept-source-agreements", "--no-upgrade"]

    def create_install_plan(self, request, source, work_dir):
        if source.method == "already_installed":
            return SoftwarePlan(actions=["verify"], expected_changes="none")
        if source.method == "winget":
            return SoftwarePlan(actions=["install"], commands=[subprocess.list2cmdline(self.install_command(source))],
                expected_changes="Install the exact package version for this user and accept its package/source agreements. No elevation or automatic reboot.",
                verification_strategy=["--version"])
        if source.method != "official_upstream_artifact":
            raise ValueError("Unsupported Windows software source.")
        return SoftwarePlan(actions=["download"], commands=[f"download {source.url} to {work_dir / source.package}"],
                            expected_changes="Create a SHA-256 verified portable executable in the task directory.")

    def execute_install(self, request, source, plan, work_dir):
        expected = self.create_install_plan(request, source, work_dir)
        if plan.commands != expected.commands:
            raise ValueError("Saved command changed; prepare a fresh reviewed plan.")
        if source.method == "winget":
            rc, output = run_command(self.install_command(source), 120)
            return {"returncode": rc, "output": output, "commands": [{"command": plan.commands[0], "returncode": rc, "output": output}]}
        target = work_dir / source.package
        if source.url != JQ_URL or source.checksum_sha256 != JQ_SHA256 or source.package != "jq.exe":
            raise ValueError("Unreviewed Windows upstream artifact.")
        size, digest = download_verified(source.url, target, source.checksum_sha256)
        return {"returncode": 0, "output": "Verified portable executable", "artifacts": [
            SoftwareArtifact(source=source.url, destination=str(target), filename=target.name, size=size, checksum=digest)]}

    def find_executable(self, request, source):
        executable = PACKAGES[request.canonical_name][1]
        candidates = [source.executable, shutil.which(executable),
            str(Path.home() / "AppData/Local/Microsoft/WinGet/Links" / executable)]
        if request.canonical_name == "git":
            candidates.append(str(Path.home() / "AppData/Local/Programs/Git/cmd/git.exe"))
        return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)

    def verification_candidates(self, request):
        return ["--version"]

    def usage_instructions(self, request, executable):
        return f'PowerShell: & "{executable}" --help'

    def update_instructions(self, source):
        return f"Request a reviewed update for {source.package}."

    def removal_instructions(self, source):
        return (f"winget uninstall --id {source.package} --exact" if source.method == "winget"
                else "Remove the managed artifact shown in this task; existing installations were not changed.")
