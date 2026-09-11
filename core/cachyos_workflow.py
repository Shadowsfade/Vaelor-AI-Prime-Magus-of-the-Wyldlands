"""Small deterministic CachyOS application setup workflow."""
from __future__ import annotations
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import urllib.request

from core.approval_policy import ActionContext, ApprovalDecision

SOURCES = {
    "jq": {
        "url": "https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64",
        "method": "official_binary",
        "version": "1.8.1",
    },
}

def is_cachyos_request(request: str) -> bool:
    text = str(request or "").lower()
    return ("cachyos" in text or "arch linux" in text or "linux" in text) and any(
        word in text for word in ("download", "install", "set up", "setup")
    )

def detect_environment() -> dict:
    release = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                release[key] = value.strip().strip('"')
    except OSError:
        pass
    managers = [name for name in ("pacman", "paru", "yay") if shutil.which(name)]
    return {
        "os": release.get("PRETTY_NAME") or platform.system(),
        "distribution": release.get("ID", ""),
        "architecture": platform.machine(),
        "shell": os.environ.get("SHELL") or shutil.which("bash") or "",
        "package_managers": managers,
        "user": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "home": str(Path.home()),
    }

def _program(request: str) -> str:
    match = re.search(r"\b(jq)\b", str(request or "").lower())
    if not match:
        raise ValueError("This bring-up currently supports the harmless jq application.")
    return match.group(1)

def _run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    return completed.returncode, (completed.stdout + completed.stderr).strip()[:4000]

def resolve_source(program: str) -> dict:
    cached = sorted(path for path in Path("/var/cache/pacman/pkg").glob(f"{program}-*.pkg.tar.*")
                    if not path.name.endswith(".sig"))
    if cached:
        return {"method": "official_pacman_cache", "source": str(cached[-1]), "cache_path": str(cached[-1])}
    return dict(SOURCES[program])

def _authorize(policy, task, tool, arguments, workspace):
    if policy is None:
        return True, ""
    assessment = policy.evaluate(ActionContext(
        tool=tool, arguments=dict(arguments), task_id=task["id"],
        session_id=task.get("session_id") or "", workspace=str(workspace),
    ))
    if assessment.decision == ApprovalDecision.AUTO_APPROVE:
        return True, ""
    return False, f"{assessment.decision.value}: {assessment.reason}"

def run_cachyos_workflow(task: dict, store, policy=None, owner: str = "") -> str:
    task_id = task["id"]
    environment = detect_environment()
    workflow = {
        "name": "cachyos_application_setup",
        "program": None,
        "method": None,
        "source": None,
        "current_step": "environment_detected",
        "environment": environment,
        "work_dir": str(Path.home() / ".local" / "share" / "vaelor" / "tasks" / task_id),
        "artifacts": [],
        "commands": [],
        "verification": [],
    }
    store.update_workflow(task_id, workflow, "environment_detected")
    if environment["distribution"].lower() not in {"cachyos", "arch", "manjaro"}:
        store.set_recovery(task_id, "BLOCKED", "CachyOS/Arch environment was not detected.", status="waiting")
        return "FINAL_SUMMARY: WAITING_USER CachyOS workflow requires a CachyOS or Arch Linux host."
    program = _program(task["request"])
    source = resolve_source(program)
    work = Path(workflow["work_dir"]) / program
    work.mkdir(parents=True, exist_ok=True)
    target = work / program
    workflow.update({"program": program, "method": source["method"],
                     "source": source.get("url") or source.get("source"),
                     "current_step": "downloading"})
    if source.get("url"):
        allowed, reason = _authorize(policy, task, "fetch_url", {"url": source["url"], "mutates": False}, work)
        if not allowed:
            store.set_recovery(task_id, "WAIT_FOR_APPROVAL", reason, status="waiting")
            return f"FINAL_SUMMARY: WAITING_APPROVAL {reason}"
    allowed, reason = _authorize(policy, task, "write_text_file", {"path": str(target)}, work)
    if not allowed:
        store.set_recovery(task_id, "WAIT_FOR_APPROVAL", reason, status="waiting")
        return f"FINAL_SUMMARY: WAITING_APPROVAL {reason}"
    store.update_workflow(task_id, workflow, "workflow_source_selected")
    step = store.begin_step(task_id, owner, "cachyos_workflow", "download")
    try:
        if source.get("cache_path"):
            extracted = subprocess.run(["bsdtar", "-xOf", source["cache_path"], "usr/bin/jq"],
                                       capture_output=True, timeout=20)
            if extracted.returncode != 0 or not extracted.stdout:
                raise RuntimeError("Cached official pacman package did not contain usr/bin/jq.")
            target.write_bytes(extracted.stdout)
        else:
            urllib.request.urlretrieve(source["url"], target)
        size = target.stat().st_size
        if size <= 0: raise RuntimeError("Downloaded file is empty.")
        artifact = {"source_url": source.get("url") or source.get("source"),
                    "destination": str(target), "filename": target.name,
                    "size": size, "temporary": False, "method": source["method"]}
        workflow["artifacts"].append(artifact)
        workflow["current_step"] = "verifying"
        store.update_workflow(task_id, workflow, "artifact_downloaded")
        store.finish_step(task_id, owner, step["id"], "succeeded", "Downloaded official jq binary.",
                          verification_state="not_required")
    except Exception as exc:
        store.finish_step(task_id, owner, step["id"], "failed", str(exc), "TRANSIENT", retry_eligible=True, error=str(exc))
        store.record_runner_failure(task_id, owner, str(exc), 5, 60)
        return f"FINAL_SUMMARY: FAILED Download failed: {exc}"
    target.chmod(target.stat().st_mode | 0o111)
    allowed, reason = _authorize(policy, task, "shell_exec", {"command": f"{target} --version", "cwd": str(work)}, work)
    if not allowed:
        store.set_recovery(task_id, "WAIT_FOR_APPROVAL", reason, status="waiting")
        return f"FINAL_SUMMARY: WAITING_APPROVAL {reason}"
    version_rc, version_out = _run([str(target), "--version"])
    help_rc, help_out = _run([str(target), "--help"])
    workflow["commands"] = [
        {"command": f"{target} --version", "returncode": version_rc, "output": version_out},
        {"command": f"{target} --help", "returncode": help_rc, "output": help_out},
    ]
    verification = {"status": "passed" if version_rc == 0 and help_rc == 0 else "failed",
                    "program": program, "version_output": version_out, "help_output": help_out,
                    "executable": str(target)}
    workflow["verification"].append(verification)
    workflow["current_step"] = "completed" if verification["status"] == "passed" else "verification_failed"
    store.update_workflow(task_id, workflow, "workflow_verified")
    step2 = store.begin_step(task_id, owner, "cachyos_workflow", "verification")
    store.finish_step(task_id, owner, step2["id"], "succeeded" if verification["status"] == "passed" else "failed",
                     verification["status"], verification_state=verification["status"])
    if verification["status"] != "passed":
        store.set_recovery(task_id, "TERMINAL_FAILURE", "Executable verification failed.", status="failed")
        return "FINAL_SUMMARY: FAILED Executable verification failed."
    summary = (
        f"FINAL_SUMMARY: SUCCESS Installed and verified {program} on CachyOS.\n"
        f"Files: {target}\n"
        f"Launch: {target} --help\n"
        "Usage: jq filters JSON, for example: echo '{\"name\":\"Vaelor\"}' | jq .name\n"
        f"Update: rerun this task for the latest official binary. Remove: delete {work}."
    )
    store.update(task_id, status="completed", result=summary)
    store.add_event(task_id, "task_succeeded", {"workflow": workflow["name"], "verification": verification})
    return summary
