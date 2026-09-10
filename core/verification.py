"""Independent, provider-neutral post-action verification for local mutations."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_REQUIRED = "not_required"


def _safe(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    return text[:limit]


@dataclass(frozen=True)
class VerificationRequirement:
    requirement_id: str
    action_fingerprint: str
    tool: str
    operation_category: str
    expected_postcondition: Mapping[str, Any]
    pre_execution_state: Mapping[str, Any]
    verifier_adapter: str

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "action_fingerprint": self.action_fingerprint,
            "tool": self.tool,
            "operation_category": self.operation_category,
            "expected_postcondition": dict(self.expected_postcondition),
            "pre_execution_state": dict(self.pre_execution_state),
            "verifier_adapter": self.verifier_adapter,
        }


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

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["fresh_observed_evidence"] = dict(self.fresh_observed_evidence)
        return data


def _target(arguments: Mapping[str, Any]) -> str:
    # Preserve the approved path identity; resolving symlinks here would make a
    # later symlink substitution appear to be the original target.
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


def _git_state(cwd: str) -> dict | None:
    try:
        root = subprocess.check_output(["git", "-C", cwd, "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL).strip()
        head = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        branch = subprocess.check_output(["git", "-C", root, "symbolic-ref", "--short", "-q", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip() or "DETACHED"
        status = subprocess.check_output(["git", "-C", root, "status", "--porcelain=v1"], text=True, stderr=subprocess.DEVNULL)
        return {"repository": os.path.realpath(root), "head": head, "branch": branch,
                "status_sha256": hashlib.sha256(status.encode()).hexdigest()}
    except (OSError, subprocess.SubprocessError):
        return None


def build_requirement(tool: str, arguments: Mapping[str, Any], fingerprint: str,
                      task_id: str, step_id: str) -> VerificationRequirement | None:
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
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "file_write", expected,
                                        _file_state(path), "local.file")
    if tool == "delete_path":
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "file_delete",
                                        {"path": path, "absent": True}, _file_state(path), "local.file")
    if tool == "make_dir":
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "directory_create",
                                        {"path": path, "type": "directory"}, _file_state(path), "local.file")
    if tool in {"git_add", "git_commit", "git_checkout", "git_push", "git_pull"}:
        cwd = str(arguments.get("repo") or arguments.get("cwd") or os.getcwd())
        state = _git_state(cwd)
        if state is None:
            return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "git", {}, {}, "git.local")
        return VerificationRequirement(f"vr-{task_id}-{step_id}", fingerprint, tool, "git", {"repository": state["repository"]}, state, "git.local")
    return None


def verify_requirement(requirement: VerificationRequirement, task_id: str, step_id: str,
                        governed_fingerprint: str) -> VerificationRecord:
    expected = requirement.expected_postcondition
    observed: dict[str, Any]
    status = VerificationStatus.UNAVAILABLE
    reason = "no supported independent verifier adapter"
    if requirement.verifier_adapter == "local.file":
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
    elif requirement.verifier_adapter == "git.local":
        observed = _git_state(str(requirement.pre_execution_state.get("repository") or os.getcwd())) or {}
        status = VerificationStatus.PASSED if observed.get("repository") == requirement.pre_execution_state.get("repository") and observed != requirement.pre_execution_state else VerificationStatus.FAILED
        reason = "repository state changed as expected" if status == VerificationStatus.PASSED else "repository identity/state did not show an expected transition"
    else:
        observed = {"adapter": requirement.verifier_adapter}
    evidence_id = hashlib.sha256(json.dumps(observed, sort_keys=True, default=str).encode()).hexdigest()
    return VerificationRecord(task_id, step_id, governed_fingerprint, evidence_id,
                              requirement.verifier_adapter, status, observed, _safe(reason))
