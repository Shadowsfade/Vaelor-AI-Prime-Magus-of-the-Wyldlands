"""Deterministic local-first approval policy for governed actions."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
import re
import threading
import uuid

class ActionClass(str, Enum):
    READ_ONLY="READ_ONLY"; TRUSTED_WORKSPACE_WRITE="TRUSTED_WORKSPACE_WRITE"; TEST_EXECUTION="TEST_EXECUTION"
    SAFE_PROCESS_EXECUTION="SAFE_PROCESS_EXECUTION"; NETWORK_READ="NETWORK_READ"; NETWORK_MUTATION="NETWORK_MUTATION"
    GIT_READ="GIT_READ"; GIT_FEATURE_BRANCH="GIT_FEATURE_BRANCH"; GIT_COMMIT="GIT_COMMIT"
    GIT_PUSH_FEATURE_BRANCH="GIT_PUSH_FEATURE_BRANCH"; CANONICAL_BRANCH_CHANGE="CANONICAL_BRANCH_CHANGE"
    DESTRUCTIVE_FILESYSTEM="DESTRUCTIVE_FILESYSTEM"; CREDENTIAL_ACCESS="CREDENTIAL_ACCESS"
    SYSTEM_CONFIGURATION="SYSTEM_CONFIGURATION"; RELEASE_OPERATION="RELEASE_OPERATION"; UNKNOWN="UNKNOWN"

class RiskTier(str, Enum):
    LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; CRITICAL="CRITICAL"

class ApprovalDecision(str, Enum):
    AUTO_APPROVE="AUTO_APPROVE"; REQUIRE_USER="REQUIRE_USER"; DENY="DENY"; AMBIGUOUS="AMBIGUOUS"

class AutoApproveMode(str, Enum):
    OFF="OFF"; SAFE="SAFE"; TRUSTED_WORKSPACE="TRUSTED_WORKSPACE"

@dataclass(frozen=True)
class ActionContext:
    tool: str
    arguments: dict = field(default_factory=dict)
    task_id: str = ""
    session_id: str = ""
    workspace: str = ""
    repo: str = ""
    branch: str = ""
    fingerprint: str = ""

@dataclass(frozen=True)
class ActionAssessment:
    action_class: ActionClass
    risk: RiskTier
    decision: ApprovalDecision
    reason: str
    scope: str = ""
    capability_id: str = ""

@dataclass
class ApprovalCapability:
    capability_id: str
    task_id: str = ""
    session_id: str = ""
    workspace: str = ""
    allowed_classes: frozenset = frozenset()
    denied_classes: frozenset = frozenset()
    created_at: str = ""
    expires_at: str = ""
    max_uses: int | None = None
    provenance: tuple[str, ...] = ()
    used: int = 0

    def valid(self, context: ActionContext, action_class: ActionClass, now=None) -> bool:
        current = now or datetime.now(timezone.utc)
        try: expires = datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError): return False
        if expires.tzinfo is None or expires <= current: return False
        if self.task_id and self.task_id != context.task_id: return False
        if self.session_id and self.session_id != context.session_id: return False
        if action_class not in self.allowed_classes or action_class in self.denied_classes: return False
        if self.workspace and not _under(context.arguments.get("path") or context.arguments.get("cwd") or self.workspace, self.workspace): return False
        if self.max_uses is not None and self.used >= self.max_uses: return False
        return True

    def consume(self):
        if self.max_uses is not None: self.used += 1

def _under(path, root):
    try:
        return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(root)).rstrip("\\/") + os.sep)
    except (TypeError, ValueError, OSError):
        return False

def classify_action(context: ActionContext) -> tuple[ActionClass, RiskTier]:
    tool = str(context.tool or "").lower()
    args = context.arguments or {}
    command = str(args.get("command") or "").strip().lower()
    if tool in {"file_reader","project_scanner","list_dir","scan_unused_files","file_editor_propose","stage_file","list_proposals"}:
        return ActionClass.READ_ONLY, RiskTier.LOW
    if tool in {"web_search","fetch_url"}: return ActionClass.NETWORK_READ, RiskTier.LOW
    if tool in {"git_status","git_log","git_diff"} or re.search(r"\bgit\s+(status|log|diff)\b", command):
        return ActionClass.GIT_READ, RiskTier.LOW
    if re.search(r"\b(git\s+push|pushd?)\b", command) or tool == "git_push":
        branch = context.branch or str(args.get("branch") or "")
        if branch.lower() in {"main","master","canonical"} or re.search(r"\b(main|master|canonical)\b", command) or "--force" in command or re.search(r"\bgit\s+push\s+-f", command):
            return ActionClass.CANONICAL_BRANCH_CHANGE, RiskTier.CRITICAL
        return ActionClass.GIT_PUSH_FEATURE_BRANCH, RiskTier.HIGH
    if re.search(r"\b(git\s+(tag|merge|rebase)|release|publish)\b", command) or tool in {"git_tag","git_merge","release"}:
        return ActionClass.RELEASE_OPERATION, RiskTier.CRITICAL
    if re.search(r"\b(git\s+(checkout|switch)\s+-c|git\s+branch\s+)", command):
        return ActionClass.GIT_FEATURE_BRANCH, RiskTier.MEDIUM
    if re.search(r"\bgit\s+commit\b", command) or tool == "git_commit":
        return ActionClass.GIT_COMMIT, RiskTier.MEDIUM
    if re.search(r"\b(rm|del|erase|remove-item|rmdir|format|diskpart)\b", command) or tool in {"delete_file","delete_dir"}:
        return ActionClass.DESTRUCTIVE_FILESYSTEM, RiskTier.CRITICAL if not context.workspace else RiskTier.HIGH
    if re.search(r"\b(password|token|secret|credential|api[_ -]?key)\b", command) or tool in {"credential_access","secret_write"}:
        return ActionClass.CREDENTIAL_ACCESS, RiskTier.CRITICAL
    if re.search(r"\b(install|set-itemproperty|reg\s+add|sc\s+config|systemctl)\b", command):
        return ActionClass.SYSTEM_CONFIGURATION, RiskTier.HIGH
    if re.search(r"\b(curl|wget|invoke-webrequest)\b.*\b(post|put|patch|delete)\b", command):
        return ActionClass.NETWORK_MUTATION, RiskTier.HIGH
    if re.search(r"\b(pytest|unittest|py_compile|npm\s+(test|run\s+test)|cargo\s+test|go\s+test)\b", command):
        return ActionClass.TEST_EXECUTION, RiskTier.LOW
    if tool in {"shell_exec","terminal_run"} and command:
        return ActionClass.SAFE_PROCESS_EXECUTION, RiskTier.MEDIUM
    if not getattr(args, "mutates", True) and tool: return ActionClass.READ_ONLY, RiskTier.LOW
    if args.get("path") or tool in {"write_text_file","apply_patch","file_editor"}:
        return ActionClass.TRUSTED_WORKSPACE_WRITE, RiskTier.MEDIUM
    return ActionClass.UNKNOWN, RiskTier.HIGH

class ApprovalPolicy:
    def __init__(self, mode=AutoApproveMode.OFF):
        self.mode = AutoApproveMode(str(mode).upper()) if not isinstance(mode, AutoApproveMode) else mode
        self._lock = threading.RLock()
        self._capabilities = {}

    def issue_capability(self, task_id="", session_id="", workspace="", allowed_classes=None,
                         denied_classes=None, lifetime_seconds=3600, max_uses=None, provenance=()):
        now=datetime.now(timezone.utc)
        cap=ApprovalCapability("cap_"+uuid.uuid4().hex[:12], task_id, session_id, workspace,
            frozenset(ActionClass(x) for x in (allowed_classes or ())), frozenset(ActionClass(x) for x in (denied_classes or ())),
            now.isoformat(), (now+timedelta(seconds=max(1,int(lifetime_seconds)))).isoformat(), max_uses, tuple(provenance))
        with self._lock: self._capabilities[cap.capability_id]=cap
        return cap

    def evaluate(self, context: ActionContext, now=None) -> ActionAssessment:
        action_class,risk=classify_action(context)
        scope = "trusted_workspace" if context.workspace and _under(context.arguments.get("path") or context.arguments.get("cwd") or context.workspace, context.workspace) else "external"
        if action_class in {ActionClass.CANONICAL_BRANCH_CHANGE,ActionClass.RELEASE_OPERATION,ActionClass.CREDENTIAL_ACCESS}:
            return ActionAssessment(action_class,risk,ApprovalDecision.REQUIRE_USER,"hard stop rule",scope)
        with self._lock:
            cap = next((c for c in self._capabilities.values() if c.valid(context,action_class,now)), None)
            if cap:
                cap.consume()
                return ActionAssessment(action_class,risk,ApprovalDecision.AUTO_APPROVE,"scoped capability",scope,cap.capability_id)
        if self.mode == AutoApproveMode.OFF:
            return ActionAssessment(action_class,risk,ApprovalDecision.REQUIRE_USER,"auto approve is off",scope)
        if action_class == ActionClass.UNKNOWN:
            return ActionAssessment(action_class,risk,ApprovalDecision.AMBIGUOUS,"action classification is ambiguous",scope)
        if self.mode == AutoApproveMode.SAFE and risk == RiskTier.LOW:
            return ActionAssessment(action_class,risk,ApprovalDecision.AUTO_APPROVE,"safe low-risk action",scope)
        if self.mode == AutoApproveMode.TRUSTED_WORKSPACE and (risk == RiskTier.LOW or (risk == RiskTier.MEDIUM and scope=="trusted_workspace")):
            return ActionAssessment(action_class,risk,ApprovalDecision.AUTO_APPROVE,"trusted workspace policy",scope)
        return ActionAssessment(action_class,risk,ApprovalDecision.REQUIRE_USER,"risk or scope exceeds policy",scope)

    def set_mode(self, mode):
        self.mode = AutoApproveMode(str(mode).upper()) if not isinstance(mode, AutoApproveMode) else mode

    def status(self):
        with self._lock:
            return {"mode": self.mode.value, "capabilities": len(self._capabilities)}

def action_fingerprint(context: ActionContext) -> str:
    return hashlib.sha256(json.dumps({"tool":context.tool,"arguments":context.arguments},sort_keys=True,separators=(",",":")).encode()).hexdigest()
