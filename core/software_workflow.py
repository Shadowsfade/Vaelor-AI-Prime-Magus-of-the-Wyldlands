"""Small platform-neutral software workflow contracts and orchestration."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
import subprocess
from typing import Any, Protocol


@dataclass
class SoftwareRequest:
    original_request: str
    requested_program: str
    canonical_name: str
    action: str = "install"


@dataclass
class SoftwareEnvironment:
    os: str
    distribution: str
    architecture: str
    shell: str = ""
    package_managers: list[str] = field(default_factory=list)
    user: str = ""
    home: str = ""
    privilege_capabilities: list[str] = field(default_factory=list)


@dataclass
class SoftwareSource:
    method: str
    package: str = ""
    repository: str = ""
    version: str = ""
    reason: str = ""
    url: str = ""
    helper: str = ""
    executable: str = ""


@dataclass
class SoftwareArtifact:
    source: str = ""
    destination: str = ""
    filename: str = ""
    size: int | None = None
    checksum: str = ""
    temporary: bool = False


@dataclass
class SoftwarePlan:
    actions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    expected_changes: str = ""
    required_privilege: str = "none"
    verification_strategy: list[str] = field(default_factory=list)


@dataclass
class SoftwareVerification:
    executable: str
    probe_attempted: str = ""
    return_code: int | None = None
    output: str = ""
    status: str = "failed"
    attempts: list[dict[str, Any]] = field(default_factory=list)


def serializable(value: Any) -> dict[str, Any]:
    """Serialize one of the compact workflow records for TaskStore JSON."""
    return asdict(value)


class SoftwarePlatformAdapter(Protocol):
    def detect_environment(self) -> SoftwareEnvironment: ...
    def canonicalize_program(self, request: str) -> SoftwareRequest: ...
    def resolve_source(self, request: SoftwareRequest) -> SoftwareSource: ...
    def create_install_plan(self, request: SoftwareRequest, source: SoftwareSource, work_dir: Path) -> SoftwarePlan: ...
    def execute_install(self, request: SoftwareRequest, source: SoftwareSource, plan: SoftwarePlan, work_dir: Path) -> dict[str, Any]: ...
    def find_executable(self, request: SoftwareRequest, source: SoftwareSource) -> str | None: ...
    def verification_candidates(self, request: SoftwareRequest) -> list[str]: ...
    def usage_instructions(self, request: SoftwareRequest, executable: str) -> str: ...
    def update_instructions(self, source: SoftwareSource) -> str: ...
    def removal_instructions(self, source: SoftwareSource) -> str: ...


def run_command(command: list[str], timeout: int = 20) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return completed.returncode, (completed.stdout + completed.stderr).strip()[:4000]


def verify_executable(executable: str, candidates: list[str], runner=run_command) -> tuple[SoftwareVerification, list[dict[str, Any]]]:
    """Run only bounded, argument-based probes; never launch an interactive program."""
    attempts: list[dict[str, Any]] = []
    if not executable or not (Path(executable).exists() or shutil.which(executable)):
        return SoftwareVerification(executable=executable, status="failed", attempts=attempts), attempts
    for probe in candidates[:6]:
        try:
            rc, output = runner([executable, probe], 10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            rc, output = -1, str(exc)[:4000]
        item = {"command": f"{executable} {probe}", "returncode": rc, "output": output}
        attempts.append(item)
        if rc == 0:
            return SoftwareVerification(executable=executable, probe_attempted=probe, return_code=rc, output=output, status="passed", attempts=attempts), attempts
    return SoftwareVerification(executable=executable, status="failed", attempts=attempts), attempts


def select_platform_adapter(environment: SoftwareEnvironment | None = None) -> SoftwarePlatformAdapter | None:
    """Select a deterministic adapter; unsupported platforms remain blocked."""
    from core.software_platforms import CachyOSAdapter
    adapter = CachyOSAdapter()
    detected = environment or adapter.detect_environment()
    if detected.distribution.lower() in {"cachyos", "arch", "manjaro"}:
        return adapter
    return None


def run_software_workflow(task: dict, store, adapter: SoftwarePlatformAdapter, policy=None, owner: str = "") -> str:
    """Run the portable durable workflow against any adapter.

    The persisted workflow is the source of truth on resume.  A waiting task
    therefore continues its saved source/plan and never repeats a completed
    mutation step.
    """
    task_id = task["id"]
    task = store.get(task_id) or task
    saved = task.get("workflow") or {}
    # Translate Slice 8 evidence without performing source discovery again.
    if saved.get("source") and not isinstance(saved["source"], dict):
        method = {"pacman": "official_repository", "aur": "trusted_community_repository",
                  "official_binary": "official_upstream_artifact"}.get(saved.get("method"), saved.get("method"))
        old_plan = saved.get("plan") or {}
        commands = old_plan.get("commands", [])
        helper = next((name for name in ("paru", "yay") if any(name in cmd.split() for cmd in commands)), "")
        program = saved["program"]
        saved = {**saved, "legacy_plan": old_plan,
                 "request": serializable(SoftwareRequest(task["request"], program, program)),
                 "source": serializable(SoftwareSource(method, package=saved.get("package", program),
                    repository=saved["source"], reason=saved.get("source_reason", ""),
                    url=saved["source"] if method == "official_upstream_artifact" else "", helper=helper)),
                 "plan": serializable(SoftwarePlan(
                    actions=["verify" if method == "already_installed" else "download" if method == "official_upstream_artifact" else "install"],
                    commands=commands, expected_changes=old_plan.get("expected_changes", ""),
                    required_privilege="sudo" if method in {"official_repository", "trusted_community_repository"} else "none"))}
    environment = SoftwareEnvironment(**saved["environment"]) if saved.get("environment") else adapter.detect_environment()
    work_dir = Path(saved.get("work_dir") or (Path(environment.home) / ".local" / "share" / "vaelor" / "tasks" / task_id))
    request = SoftwareRequest(**saved["request"]) if saved.get("request") else adapter.canonicalize_program(task["request"])
    source = SoftwareSource(**saved["source"]) if saved.get("source") else adapter.resolve_source(request)
    plan = SoftwarePlan(**saved["plan"]) if saved.get("plan") else adapter.create_install_plan(request, source, work_dir)
    workflow = {
        **saved,
        "name": "software_workflow", "request": serializable(request), "environment": serializable(environment),
        "source": serializable(source), "plan": serializable(plan), "work_dir": str(work_dir),
        "program": request.canonical_name, "method": source.method, "artifacts": saved.get("artifacts", []),
        "commands": saved.get("commands", []), "verification": saved.get("verification", []),
        "current_step": saved.get("current_step", "plan_persisted"),
    }
    store.update_workflow(task_id, workflow, "software_plan_persisted")
    if source.method == "already_installed" or "install" not in plan.actions and "download" not in plan.actions:
        return _verify_and_finish(task, store, adapter, request, source, workflow, owner)
    mutations = [step for step in task.get("steps", [])
                 if step.get("action_category") in {"install", "download"}]
    completed = any(step.get("state") == "succeeded" for step in mutations)
    if mutations and not completed:
        store.set_recovery(task_id, "BLOCKED", "Previous mutation has an uncertain outcome; inspect installed state before retrying.", status="waiting")
        return "FINAL_SUMMARY: BLOCKED Previous mutation requires reconciliation."
    if not completed:
        preflight = getattr(adapter, "preflight", None)
        reason = preflight(plan) if preflight else ""
        if reason:
            store.set_recovery(task_id, "WAIT_FOR_APPROVAL", reason, status="waiting")
            return f"FINAL_SUMMARY: WAITING_USER {reason}"
        from core.approval_policy import ActionContext, ApprovalDecision, ApprovalPolicy
        policy = policy or ApprovalPolicy()
        assessment = policy.evaluate(ActionContext(tool="shell_exec", arguments={"command": plan.commands[0] if plan.commands else "", "mutates": True}, task_id=task_id, session_id=task.get("session_id") or "", workspace=str(work_dir)))
        store.add_event(task_id, "approval_policy_decided", {
            "decision": assessment.decision.value, "action_class": assessment.action_class.value,
            "risk_tier": assessment.risk.value, "reason": assessment.reason,
            "scope": assessment.scope, "capability_id": assessment.capability_id or None,
        })
        if assessment.decision != ApprovalDecision.AUTO_APPROVE:
            store.set_recovery(task_id, "WAIT_FOR_APPROVAL", f"{assessment.decision.value}: {assessment.reason}", status="waiting")
            return f"FINAL_SUMMARY: WAITING_APPROVAL {assessment.reason}"
        step_name = "install" if "install" in plan.actions else "download"
        step = store.begin_step(task_id, owner, "software_workflow", step_name)
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            result = adapter.execute_install(request, source, plan, work_dir)
            workflow["commands"].extend(result.get("commands", [])); workflow["artifacts"].extend([serializable(a) if hasattr(a, "__dataclass_fields__") else a for a in result.get("artifacts", [])])
            store.update_workflow(task_id, workflow, "mutation_finished")
            store.finish_step(task_id, owner, step["id"], "succeeded" if result.get("returncode", 1) == 0 else "failed", result.get("output", ""), "REQUIRES_ACTION" if result.get("returncode", 1) else None, retry_eligible=False)
            if result.get("returncode", 1) != 0:
                store.set_recovery(task_id, "BLOCKED", "Software mutation failed; inspect installed state before retrying.", status="waiting")
                return "FINAL_SUMMARY: BLOCKED Software mutation requires reconciliation."
        except Exception as exc:
            store.finish_step(task_id, owner, step["id"], "failed", str(exc), "REQUIRES_ACTION", retry_eligible=False, error=str(exc))
            store.set_recovery(task_id, "BLOCKED", str(exc), status="waiting")
            return f"FINAL_SUMMARY: BLOCKED {exc}"
    return _verify_and_finish(task, store, adapter, request, source, workflow, owner)


def _verify_and_finish(task, store, adapter, request, source, workflow, owner):
    step = store.begin_step(task["id"], owner, "software_workflow", "verification")
    executable = adapter.find_executable(request, source)
    if workflow["artifacts"]:
        executable = workflow["artifacts"][-1].get("destination") or executable
    verification, attempts = verify_executable(executable or "", adapter.verification_candidates(request))
    workflow["verification"].append(serializable(verification)); workflow["commands"].extend(attempts); workflow["current_step"] = "completed" if verification.status == "passed" else "verification_failed"
    store.update_workflow(task["id"], workflow, "workflow_verified")
    store.finish_step(task["id"], owner, step["id"], "succeeded" if verification.status == "passed" else "failed", verification.output, verification_state=verification.status)
    if verification.status != "passed":
        store.set_recovery(task["id"], "TERMINAL_FAILURE", "Executable verification failed.", status="failed")
        return "FINAL_SUMMARY: FAILED Executable verification failed."
    summary = (f"FINAL_SUMMARY: SUCCESS Set up and verified {request.canonical_name}.\n"
               f"Method: {source.method}. {adapter.usage_instructions(request, executable)}\n"
               f"Update: {adapter.update_instructions(source)}\nRemove: {adapter.removal_instructions(source)}")
    store.update(task["id"], status="completed", result=summary)
    store.add_event(task["id"], "task_succeeded", {"workflow": workflow["name"], "verification": serializable(verification)})
    return summary
