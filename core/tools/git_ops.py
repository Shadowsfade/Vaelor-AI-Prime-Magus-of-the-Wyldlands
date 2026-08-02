"""Git operations with autonomy levels + audit failsafes."""
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional

from .shell_exec import load_autonomy, _audit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_git(args: List[str], cwd: Optional[str] = None, timeout: int = 90) -> str:
    workdir = cwd or PROJECT_ROOT
    cmd = ["git", "--no-pager", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_PAGER": "cat", "PAGER": "cat"},
        )
    except Exception as e:
        _audit({"tool": "git", "args": args, "result": "error", "error": str(e)})
        return f"git failed: {e}"
    out = ((proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")).strip()
    if len(out) > 16000:
        out = out[:16000] + "\n...[truncated]"
    prefix = "OK" if proc.returncode == 0 else f"EXIT {proc.returncode}"
    _audit({"tool": "git", "args": args, "returncode": proc.returncode, "result": prefix})
    return f"[{prefix}] git {' '.join(args)}\n{out if out else '(no output)'}"


def _auto_ok(confirm: str) -> bool:
    if str(confirm).lower() in ("yes", "true", "1", "y"):
        return True
    cfg = load_autonomy()
    mode = (cfg.get("mode") or "trusted").lower()
    return mode in ("trusted", "admin") and bool(cfg.get("auto_confirm_mutations", True))


def git_status(path: str = "") -> str:
    return _run_git(["status", "-sb"], cwd=path or PROJECT_ROOT)


def git_diff(path: str = "", staged: str = "no") -> str:
    cwd = path or PROJECT_ROOT
    if str(staged).lower() in ("yes", "true", "1"):
        return _run_git(["diff", "--cached"], cwd=cwd)
    base = _run_git(["diff", "--stat"], cwd=cwd)
    detail = _run_git(["diff"], cwd=cwd)
    return base + "\n\n" + detail[:10000]


def git_log(path: str = "", limit: int = 10) -> str:
    n = max(1, min(int(limit or 10), 50))
    return _run_git(["log", f"-{n}", "--oneline", "--decorate"], cwd=path or PROJECT_ROOT)


def git_branch(path: str = "", all: str = "no") -> str:
    args = ["branch", "-a", "-vv"] if str(all).lower() in ("yes", "true", "1") else ["branch", "-vv"]
    return _run_git(args, cwd=path or PROJECT_ROOT)


def git_remote(repo: str = "") -> str:
    return _run_git(["remote", "-v"], cwd=repo or PROJECT_ROOT)


def git_add(path: str = ".", confirm: str = "no", repo: str = "") -> str:
    if not _auto_ok(confirm):
        return "Refused: git_add needs confirm=yes (or autonomy trusted/admin)"
    target = path or "."
    if re.search(r"\.(env|pem|key)$", target, re.I):
        return f"Refused failsafe: potential secret file {target}"
    return _run_git(["add", "--", target], cwd=repo or PROJECT_ROOT)


def git_commit(message: str = "", confirm: str = "no", repo: str = "") -> str:
    if not _auto_ok(confirm):
        return "Refused: git_commit needs confirm=yes (or autonomy trusted/admin)"
    message = (message or "").strip()
    if not message:
        return "Refused: message required"
    msg = message if "Co-Authored-By" in message else message + "\n\nCo-Authored-By: Vaelor <vaelor@local>"
    return _run_git(["commit", "-m", msg], cwd=repo or PROJECT_ROOT)


def git_checkout(branch: str = "", create: str = "no", confirm: str = "no", repo: str = "") -> str:
    if not _auto_ok(confirm):
        return "Refused: git_checkout needs confirm=yes (or autonomy trusted/admin)"
    branch = (branch or "").strip()
    if not branch or not re.match(r"^[\w./-]+$", branch):
        return "Refused: invalid branch"
    if str(create).lower() in ("yes", "true", "1"):
        return _run_git(["checkout", "-b", branch], cwd=repo or PROJECT_ROOT)
    return _run_git(["checkout", branch], cwd=repo or PROJECT_ROOT)


def git_pull(remote: str = "origin", branch: str = "", confirm: str = "no", repo: str = "") -> str:
    if not _auto_ok(confirm):
        return "Refused: git_pull needs confirm=yes (or autonomy trusted/admin)"
    args = ["pull", remote or "origin"]
    if branch:
        args.append(branch)
    return _run_git(args, cwd=repo or PROJECT_ROOT, timeout=180)


def git_push(remote: str = "origin", branch: str = "", force: str = "no", confirm: str = "no", repo: str = "") -> str:
    cfg = load_autonomy()
    if not cfg.get("allow_git_push", True):
        return "Refused: git_push disabled in autonomy config"
    if not _auto_ok(confirm):
        return "Refused: git_push needs confirm=yes (or autonomy trusted/admin)"
    if str(force).lower() in ("yes", "true", "1") and not cfg.get("allow_force_push", False):
        return "Refused failsafe: force push disabled (set allow_force_push true in autonomy.json to enable)"
    args = ["push", remote or "origin"]
    if branch:
        if not re.match(r"^[\w./-]+$", branch):
            return "Refused: invalid branch"
        args.append(branch)
    if str(force).lower() in ("yes", "true", "1"):
        args.insert(1, "--force-with-lease")
    return _run_git(args, cwd=repo or PROJECT_ROOT, timeout=180)
