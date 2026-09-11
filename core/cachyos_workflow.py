"""Deterministic, governed CachyOS/Arch software setup workflow."""
from __future__ import annotations
from pathlib import Path
import os, platform, re, shutil, subprocess, urllib.request
from core.approval_policy import ActionContext, ApprovalDecision

UPSTREAM_SOURCES = {"jq": {"url": "https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-linux-amd64", "method": "official_binary", "version": "1.8.1"}}
ALIASES = {"ripgrep": "rg", "fd-find": "fd"}

def is_cachyos_request(request):
    text = str(request or "").lower()
    return ("cachyos" in text or "arch linux" in text or "linux" in text) and any(w in text for w in ("download", "install", "set up", "setup"))

def detect_environment():
    release = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1); release[key] = value.strip().strip('"')
    except OSError: pass
    managers = [n for n in ("pacman", "paru", "yay") if shutil.which(n)]
    return {"os": release.get("PRETTY_NAME") or platform.system(), "distribution": release.get("ID", ""), "architecture": platform.machine(), "shell": os.environ.get("SHELL") or shutil.which("bash") or "", "package_managers": managers, "user": os.environ.get("USER") or os.environ.get("USERNAME") or "", "home": str(Path.home())}

def extract_program(request):
    match = re.search(r"\b(?:download|install|get|setup|set up)\s+([a-z0-9][a-z0-9+._-]*)\b", str(request or "").lower())
    if not match: raise ValueError("Could not identify a program name safely.")
    return ALIASES.get(match.group(1), match.group(1))
_program = extract_program

def _run(command, timeout=20):
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return completed.returncode, (completed.stdout + completed.stderr).strip()[:4000]
def _package_query(manager, program): return _run([manager, "-Si", program], 15)

def resolve_source(program):
    executable = shutil.which(program)
    if executable:
        rc, info = _run(["pacman", "-Q", program], 10)
        if rc == 0: return {"method": "already_installed", "source": "local package database", "package": program, "executable": executable, "version": info}
    if shutil.which("pacman"):
        rc, info = _package_query("pacman", program)
        if rc == 0: return {"method": "pacman", "source": "official repository", "package": program, "version": info}
    for helper in ("paru", "yay"):
        if shutil.which(helper):
            rc, info = _package_query(helper, program)
            if rc == 0: return {"method": "aur", "source": f"AUR via {helper}", "package": program, "helper": helper, "version": info}
    if program in UPSTREAM_SOURCES: return dict(UPSTREAM_SOURCES[program])
    raise ValueError(f"No trusted CachyOS source matched {program!r}.")

def _authorize(policy, task, tool, arguments, workspace):
    if policy is None: return True, ""
    assessment = policy.evaluate(ActionContext(tool=tool, arguments=dict(arguments), task_id=task["id"], session_id=task.get("session_id") or "", workspace=str(workspace)))
    if assessment.decision == ApprovalDecision.AUTO_APPROVE: return True, ""
    return False, f"{assessment.decision.value}: {assessment.reason}"
def _waiting(store, task_id, recovery, reason, summary):
    store.set_recovery(task_id, recovery, reason, status="waiting"); return f"FINAL_SUMMARY: {summary} {reason}"
def _verify(executable):
    commands = []
    for flag in ("--version", "-V", "version", "--help", "-h"):
        rc, output = _run([str(executable), flag]); commands.append({"command": f"{executable} {flag}", "returncode": rc, "output": output})
        if rc == 0: return {"status": "passed", "executable": str(executable), "command": commands[-1]["command"], "output": output}, commands
    return {"status": "failed", "executable": str(executable), "commands": commands}, commands
def _finish_verified(store, task, workflow, executable, owner):
    verification, commands = _verify(executable); workflow["commands"].extend(commands); workflow["verification"].append(verification); workflow["current_step"] = "completed" if verification["status"] == "passed" else "verification_failed"; store.update_workflow(task["id"], workflow, "workflow_verified")
    step = store.begin_step(task["id"], owner, "cachyos_workflow", "verification"); store.finish_step(task["id"], owner, step["id"], "succeeded" if verification["status"] == "passed" else "failed", verification["status"], verification_state=verification["status"])
    if verification["status"] != "passed": store.set_recovery(task["id"], "TERMINAL_FAILURE", "Executable verification failed.", status="failed"); return "FINAL_SUMMARY: FAILED Executable verification failed."
    work = Path(workflow["work_dir"]); summary = f"FINAL_SUMMARY: SUCCESS Set up and verified {workflow['program']} on CachyOS.\nMethod: {workflow['method']}. Launch: {executable} --help\nFiles: {', '.join(a['destination'] for a in workflow['artifacts']) or 'none'}\nUpdate: use the same package/source method. Remove: remove {work}."
    store.update(task["id"], status="completed", result=summary); store.add_event(task["id"], "task_succeeded", {"workflow": workflow["name"], "verification": verification}); return summary

def run_cachyos_workflow(task, store, policy=None, owner=""):
    task_id = task["id"]; environment = detect_environment(); workflow = {"name": "cachyos_application_setup", "program": None, "method": None, "source": None, "current_step": "environment_detected", "environment": environment, "work_dir": str(Path.home()/".local"/"share"/"vaelor"/"tasks"/task_id), "artifacts": [], "commands": [], "verification": []}; store.update_workflow(task_id, workflow, "environment_detected")
    if environment["distribution"].lower() not in {"cachyos", "arch", "manjaro"}: return _waiting(store, task_id, "BLOCKED", "CachyOS/Arch environment was not detected.", "WAITING_USER")
    try: program, source = extract_program(task["request"]), resolve_source(extract_program(task["request"]))
    except ValueError as exc: return _waiting(store, task_id, "BLOCKED", str(exc), "BLOCKED")
    work = Path(workflow["work_dir"])/program; work.mkdir(parents=True, exist_ok=True); reason = {"already_installed":"Executable and package are already present; installation skipped.","pacman":"Selected pacman because the package exists in the official repository.","aur":"Selected the existing AUR helper because no official repository package matched.","official_binary":"Selected the allowlisted official upstream artifact because no package source matched."}.get(source["method"],"Trusted source selected."); workflow.update({"program": program, "package": source.get("package", program), "method": source["method"], "source": source.get("url") or source.get("source"), "source_reason": reason, "current_step": "source_selected", "plan": {"program": program, "method": source["method"], "source": source.get("url") or source.get("source"), "commands": [], "verify": ["executable_exists", "--version", "-V", "version", "--help", "-h"], "expected_changes": "install package" if source["method"] in {"pacman","aur"} else "none or managed artifact"}})
    if source["method"] == "already_installed": workflow["current_step"] = "verifying"; store.update_workflow(task_id, workflow, "workflow_source_selected"); return _finish_verified(store, task, workflow, Path(source["executable"]), owner)
    if source["method"] in {"pacman", "aur"}:
        manager = source.get("helper", "pacman"); command = f"sudo -n {manager} -S --needed --noconfirm {program}"; workflow["plan"]["commands"] = [command]; store.update_workflow(task_id, workflow, "workflow_source_selected"); allowed, reason = _authorize(policy, task, "shell_exec", {"command": command, "mutates": True}, work)
        if not allowed: return _waiting(store, task_id, "WAIT_FOR_APPROVAL", reason, "WAITING_APPROVAL")
        rc, output = _run(["sudo", "-n", "-v"], 5)
        if rc != 0: return _waiting(store, task_id, "WAIT_FOR_APPROVAL", "Installation requires sudo authentication. Authenticate, then tell Vaelor to continue.", "WAITING_USER")
        store.update_workflow(task_id, workflow, "workflow_source_selected"); step = store.begin_step(task_id, owner, "cachyos_workflow", "install"); rc, output = _run(["sudo", "-n", manager, "-S", "--needed", "--noconfirm", program], 120); workflow["commands"].append({"command": command, "returncode": rc, "output": output}); store.update_workflow(task_id, workflow, "install_finished"); store.finish_step(task_id, owner, step["id"], "succeeded" if rc == 0 else "failed", output, "TRANSIENT" if rc else None, retry_eligible=rc != 0)
        if rc != 0: store.set_recovery(task_id, "RETRY_SAFE", f"Install failed: {output}", status="retrying"); return "FINAL_SUMMARY: RETRY_SCHEDULED Install failed."
        return _finish_verified(store, task, workflow, Path(shutil.which(program) or "/usr/bin/"+program), owner)
    target = work/program; workflow["plan"]["commands"] = [f"download {source.get('url', '')} to {target}"]; store.update_workflow(task_id, workflow, "workflow_source_selected"); allowed, reason = _authorize(policy, task, "write_text_file", {"path": str(target), "mutates": True}, work)
    if not allowed: return _waiting(store, task_id, "WAIT_FOR_APPROVAL", reason, "WAITING_APPROVAL")
    store.update_workflow(task_id, workflow, "workflow_source_selected"); step = store.begin_step(task_id, owner, "cachyos_workflow", "download")
    try:
        urllib.request.urlretrieve(source["url"], target); size = target.stat().st_size
        if size <= 0: raise RuntimeError("Downloaded file is empty.")
        target.chmod(target.stat().st_mode | 0o111); workflow["artifacts"].append({"source_url": source["url"], "destination": str(target), "filename": target.name, "size": size, "temporary": False, "method": source["method"]}); store.update_workflow(task_id, workflow, "artifact_downloaded"); store.finish_step(task_id, owner, step["id"], "succeeded", "Downloaded official artifact", verification_state="not_required")
    except Exception as exc:
        store.finish_step(task_id, owner, step["id"], "failed", str(exc), "TRANSIENT", retry_eligible=True, error=str(exc)); store.record_runner_failure(task_id, owner, str(exc), 5, 60); return f"FINAL_SUMMARY: FAILED Download failed: {exc}"
    return _finish_verified(store, task, workflow, target, owner)
