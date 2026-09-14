"""Independent, provider-neutral post-action verification for local mutations."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from core.governance import contract_json_value, freeze_contract_value


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_REQUIRED = "not_required"


_GIT_TIMEOUT = 4
_GIT_OUTPUT = 12000
_GIT_TOOLS = {"git_add", "git_commit", "git_checkout", "git_push", "git_pull"}


def _safe(value: Any, limit: int = 800) -> str:
    return str(value or "")[:limit]


def _jsonable(value: Any) -> Any:
    return contract_json_value(value)


@dataclass(frozen=True)
class VerificationRequirement:
    requirement_id: str
    action_fingerprint: str
    tool: str
    operation_category: str
    expected_postcondition: Mapping[str, Any]
    pre_execution_state: Mapping[str, Any]
    verifier_adapter: str
    task_id: str = ""
    step_id: str = ""
    arguments: Mapping[str, Any] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_postcondition", freeze_contract_value(self.expected_postcondition))
        object.__setattr__(self, "pre_execution_state", freeze_contract_value(self.pre_execution_state))
        object.__setattr__(self, "arguments", freeze_contract_value(self.arguments or {}))

    def to_dict(self) -> dict:
        return {"requirement_id": self.requirement_id, "action_fingerprint": self.action_fingerprint,
                "tool": self.tool, "operation_category": self.operation_category,
                "expected_postcondition": _jsonable(self.expected_postcondition),
                "pre_execution_state": _jsonable(self.pre_execution_state),
                "verifier_adapter": self.verifier_adapter, "task_id": self.task_id,
                "step_id": self.step_id, "arguments": _jsonable(self.arguments or {})}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "VerificationRequirement":
        required = ("requirement_id", "action_fingerprint", "tool", "operation_category",
                    "expected_postcondition", "pre_execution_state", "verifier_adapter",
                    "task_id", "step_id", "arguments")
        if not isinstance(raw, Mapping) or any(k not in raw for k in required):
            raise ValueError("incomplete verification requirement")
        ids = ("requirement_id", "action_fingerprint", "tool", "operation_category", "verifier_adapter", "task_id", "step_id")
        if not all(isinstance(raw[k], str) and raw[k] for k in ids):
            raise ValueError("malformed verification requirement identity")
        if not isinstance(raw["expected_postcondition"], Mapping) or not isinstance(raw["pre_execution_state"], Mapping) or not isinstance(raw["arguments"], Mapping):
            raise ValueError("malformed verification requirement state")
        return cls(raw["requirement_id"], raw["action_fingerprint"], raw["tool"], raw["operation_category"],
                   raw["expected_postcondition"], raw["pre_execution_state"], raw["verifier_adapter"],
                   raw["task_id"], raw["step_id"], raw["arguments"])


@dataclass(frozen=True)
class VerificationRecord:
    task_id: str
    step_id: str
    governed_fingerprint: str
    evidence_id: str
    verifier_identity: str
    status: VerificationStatus
    fresh_observed_evidence: Mapping[str, Any]
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", VerificationStatus(self.status))
        object.__setattr__(self, "fresh_observed_evidence", freeze_contract_value(self.fresh_observed_evidence))

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "governed_fingerprint": self.governed_fingerprint,
            "evidence_id": self.evidence_id,
            "verifier_identity": self.verifier_identity,
            "status": self.status.value,
            "fresh_observed_evidence": _jsonable(self.fresh_observed_evidence),
            "reason": _safe(self.reason),
        }


def _target(arguments: Mapping[str, Any]) -> str:
    return os.path.abspath(os.path.expanduser(str(arguments.get("path") or arguments.get("target") or "")))


def _file_state(path: str) -> dict:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {"path": path, "exists": False}
    kind = "symlink" if os.path.islink(path) else "directory" if os.path.isdir(path) else "file" if os.path.isfile(path) else "other"
    value = {"path": path, "exists": True, "type": kind, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if kind == "file" and st.st_size <= 2_000_000:
        value["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return value


def _git(root: str, args: list[str], timeout: int = _GIT_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "GIT_PAGER": "cat", "PAGER": "cat"})
    except (OSError, subprocess.SubprocessError):
        return 124, ""
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))[:_GIT_OUTPUT]
    return proc.returncode, output.strip()


def _git_value(root: str, args: list[str]) -> str | None:
    code, output = _git(root, args)
    return output if code == 0 and output else None


def _repo(cwd: str) -> str | None:
    root = _git_value(cwd, ["rev-parse", "--show-toplevel"])
    return os.path.realpath(root) if root else None


def _git_state(cwd: str) -> dict | None:
    root = _repo(cwd)
    if not root:
        return None
    head = _git_value(root, ["rev-parse", "HEAD"])
    branch = _git_value(root, ["symbolic-ref", "--short", "-q", "HEAD"]) or "DETACHED"
    status = _git_value(root, ["status", "--porcelain=v1"]) or ""
    return {"repository": root, "head": head, "branch": branch,
            "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
            "index_tree": _git_value(root, ["write-tree"])}


def _remote_identity(root: str, remote: str) -> str | None:
    value = _git_value(root, ["remote", "get-url", remote])
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def _git_requirement(tool: str, arguments: Mapping[str, Any], fingerprint: str, task_id: str, step_id: str) -> VerificationRequirement:
    cwd = str(arguments.get("repo") or arguments.get("cwd") or os.getcwd())
    state = _git_state(cwd)
    if state is None:
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "git", {}, {}, "git.local", task_id, step_id, dict(arguments))
    root = state["repository"]
    args = dict(arguments)
    expected: dict[str, Any] = {"repository": root}
    if tool == "git_add":
        expected.update({"pathspec": str(args.get("path") or "."), "index_before": state["index_tree"], "branch": state["branch"]})
    elif tool == "git_commit":
        expected.update({"parent": state["head"], "staged_tree": state["index_tree"]})
    elif tool == "git_checkout":
        ref = str(args.get("branch") or "")
        expected.update({"requested_ref": ref, "requested_oid": _git_value(root, ["rev-parse", "--verify", ref])})
    elif tool == "git_push":
        remote, branch = str(args.get("remote") or "origin"), str(args.get("branch") or state["branch"])
        expected.update({"remote": remote, "remote_identity": _remote_identity(root, remote), "ref": f"refs/heads/{branch}",
                         "source_head": state["head"], "remote_before": _git_value(root, ["ls-remote", remote, f"refs/heads/{branch}"])})
    else:
        remote, branch = str(args.get("remote") or "origin"), str(args.get("branch") or state["branch"])
        expected.update({"remote": remote, "branch": branch, "upstream": f"{remote}/{branch}",
                         "head_before": state["head"], "remote_identity": _remote_identity(root, remote)})
    return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, tool, expected, state, "git.local", task_id, step_id, args)


def build_requirement(tool: str, arguments: Mapping[str, Any], fingerprint: str, task_id: str, step_id: str) -> VerificationRequirement | None:
    if tool in {"computer_input", "computer_focus"}:
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool,
            "computer_interaction", {"requires_independent_goal_check": True}, {},
            "computer.unverified", task_id, step_id, dict(arguments))
    path = _target(arguments)
    if tool in {"write_text_file", "apply_patch"}:
        expected = {"path": path, "type": "file"}
        if tool == "write_text_file":
            content = str(arguments.get("content", "")).replace("\\n", "\n").replace("\\t", "\t")
            expected.update({"sha256": hashlib.sha256(content.encode()).hexdigest(), "size": len(content.encode())})
        else:
            try:
                before = Path(path).read_text(encoding="utf-8-sig")
                old = str(arguments.get("old", "")).replace("\\n", "\n").replace("\\t", "\t")
                new = str(arguments.get("new", "")).replace("\\n", "\n").replace("\\t", "\t")
                if old and old in before:
                    content = before.replace(old, new, 1).encode()
                    expected.update({"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
            except (OSError, UnicodeError):
                pass
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "file_write", expected, _file_state(path), "local.file", task_id, step_id, dict(arguments))
    if tool == "delete_path":
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "file_delete", {"path": path, "absent": True}, _file_state(path), "local.file", task_id, step_id, dict(arguments))
    if tool == "make_dir":
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "directory_create", {"path": path, "type": "directory"}, _file_state(path), "local.file", task_id, step_id, dict(arguments))
    if tool in _GIT_TOOLS:
        return _git_requirement(tool, arguments, fingerprint, task_id, step_id)
    return None


def _git_verify(req: VerificationRequirement) -> tuple[VerificationStatus, dict, str]:
    expected, root = req.expected_postcondition, str(req.pre_execution_state.get("repository") or "")
    if not root or expected.get("repository") != root or not os.path.isdir(root):
        return VerificationStatus.UNAVAILABLE, {}, "repository identity is unavailable"
    now = _git_state(root)
    if not now or now.get("repository") != root:
        return VerificationStatus.UNAVAILABLE, {}, "fresh repository state is unavailable"
    observed: dict[str, Any] = {"repository": root, "head": now.get("head"), "branch": now.get("branch")}
    if req.tool == "git_add":
        pathspec = str(expected.get("pathspec") or "")
        names = _git_value(root, ["diff", "--cached", "--name-only", "--", pathspec]) or ""
        staged = [line for line in names.splitlines() if line]
        observed.update({"staged_paths": staged[:100], "index_tree": now.get("index_tree")})
        intended = pathspec in ("", ".") and bool(staged) or pathspec not in ("", ".") and pathspec in staged
        changed = now.get("index_tree") != expected.get("index_before")
        ok = intended and changed and now.get("branch") == expected.get("branch")
        return (VerificationStatus.PASSED if ok else VerificationStatus.FAILED, observed, "intended path is staged" if ok else "intended staged path transition not proven")
    if req.tool == "git_commit":
        parent, tree = _git_value(root, ["rev-parse", "HEAD^1"]), _git_value(root, ["rev-parse", "HEAD^{tree}"])
        observed.update({"parent": parent, "tree": tree})
        if not expected.get("parent") or not expected.get("staged_tree"):
            return VerificationStatus.UNAVAILABLE, observed, "initial commits are not supported by this verifier"
        ok = now.get("head") != expected["parent"] and parent == expected["parent"] and tree == expected["staged_tree"]
        return (VerificationStatus.PASSED if ok else VerificationStatus.FAILED, observed, "HEAD advanced with the approved parent and staged tree" if ok else "approved commit transition not proven")
    if req.tool == "git_checkout":
        ref, oid = str(expected.get("requested_ref") or ""), expected.get("requested_oid")
        observed["requested_oid"] = _git_value(root, ["rev-parse", "--verify", ref]) if ref else None
        ok = bool(ref and oid and now.get("branch") == ref and now.get("head") == oid)
        return (VerificationStatus.PASSED if ok else VerificationStatus.FAILED, observed, "requested checkout target is exact" if ok else "checkout target differs from approved ref")
    if req.tool == "git_push":
        remote, ref = str(expected.get("remote") or ""), str(expected.get("ref") or "")
        if not expected.get("remote_identity") or not expected.get("source_head"):
            return VerificationStatus.UNAVAILABLE, observed, "remote identity or source ref is unavailable"
        code, line = _git(root, ["ls-remote", remote, ref])
        if code != 0:
            return VerificationStatus.UNAVAILABLE, observed, "remote state could not be observed"
        remote_oid = line.split()[0] if line and line.split() else None
        observed.update({"remote": remote, "ref": ref, "remote_oid": remote_oid})
        ok = remote_oid == expected["source_head"] and expected.get("remote_before") != remote_oid
        return (VerificationStatus.PASSED if ok else VerificationStatus.FAILED, observed, "remote ref matches the pushed source HEAD" if ok else "remote push transition not proven")
    if req.tool == "git_pull":
        remote, branch = str(expected.get("remote") or ""), str(expected.get("branch") or "")
        if not expected.get("remote_identity") or expected.get("head_before") is None:
            return VerificationStatus.UNAVAILABLE, observed, "upstream identity or pre-state is unavailable"
        code, line = _git(root, ["ls-remote", remote, f"refs/heads/{branch}"])
        if code != 0:
            return VerificationStatus.UNAVAILABLE, observed, "upstream state could not be observed"
        remote_oid = line.split()[0] if line and line.split() else None
        observed.update({"remote": remote, "branch": branch, "remote_oid": remote_oid})
        ok = now.get("branch") == branch and now.get("head") == remote_oid and now.get("head") != expected["head_before"]
        return (VerificationStatus.PASSED if ok else VerificationStatus.FAILED, observed, "local branch matches the intended upstream after pull" if ok else "pull transition not proven")
    return VerificationStatus.UNAVAILABLE, observed, "unsupported Git operation"


def verify_requirement(requirement: VerificationRequirement, task_id: str, step_id: str, governed_fingerprint: str) -> VerificationRecord:
    try:
        if not isinstance(requirement, VerificationRequirement):
            raise ValueError("requirement is not a verified contract")
        if task_id != requirement.task_id or step_id != requirement.step_id:
            raise ValueError("task or step binding mismatch")
        if governed_fingerprint != requirement.action_fingerprint:
            raise ValueError("governed fingerprint binding mismatch")
        if not requirement.tool or not requirement.verifier_adapter or not requirement.expected_postcondition:
            raise ValueError("incomplete verification contract")
        if requirement.verifier_adapter == "git.local":
            status, observed, reason = _git_verify(requirement)
        elif requirement.verifier_adapter == "local.file":
            expected = requirement.expected_postcondition
            observed = _file_state(str(expected.get("path", "")))
            if requirement.operation_category == "file_delete":
                status = VerificationStatus.PASSED if not observed.get("exists") else VerificationStatus.FAILED
                reason = "target is absent" if status == VerificationStatus.PASSED else "target still exists"
            elif requirement.operation_category == "directory_create":
                status = VerificationStatus.PASSED if observed.get("type") == "directory" and not os.path.islink(str(expected.get("path"))) else VerificationStatus.FAILED
                reason = "directory identity and type match" if status == VerificationStatus.PASSED else "target is not the approved real directory"
            else:
                matches = observed.get("type") == "file" and not os.path.islink(str(expected.get("path")))
                if "sha256" in expected:
                    matches = matches and observed.get("sha256") == expected["sha256"] and observed.get("size") == expected.get("size")
                status = VerificationStatus.PASSED if matches else VerificationStatus.FAILED
                reason = "fresh file state matches postcondition" if status == VerificationStatus.PASSED else "fresh file state contradicts postcondition"
        else:
            status, observed, reason = VerificationStatus.UNAVAILABLE, {"adapter": _safe(requirement.verifier_adapter)}, "no supported independent verifier adapter"
    except (TypeError, ValueError, KeyError) as exc:
        status, observed, reason = VerificationStatus.FAILED, {}, _safe(str(exc))
    evidence_id = hashlib.sha256(json.dumps(_jsonable(observed), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return VerificationRecord(task_id, step_id, governed_fingerprint, evidence_id, requirement.verifier_adapter, status, observed, _safe(reason))
