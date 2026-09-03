"""Disposable Git worktrees for isolated validation runs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from core.tools.fs_ops import _resolve_path
from core.tools.git_ops import _auto_ok
from core.tools.git_ops import review_git_changes
from core.tools.shell_exec import _audit
from core.validation_gate import evaluate_validation


SANDBOX_ROOT = Path(tempfile.gettempdir()) / "VaelorSandboxes"
ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def _locations():
    return SANDBOX_ROOT / "worktrees", SANDBOX_ROOT / "manifests"


def _git(repo: Path, args, timeout=90):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        timeout=timeout,
    )


def _manifest_path(sandbox_id: str) -> Path:
    if not ID_PATTERN.fullmatch(str(sandbox_id or "")):
        raise ValueError("invalid sandbox id")
    return _locations()[1] / f"{sandbox_id}.json"


def _write_manifest(data: dict):
    path = _manifest_path(data["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_manifest(sandbox_id: str) -> dict:
    path = _manifest_path(sandbox_id)
    if not path.is_file():
        raise KeyError(f"unknown validation sandbox: {sandbox_id}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _head(repo: Path) -> str:
    result = _git(repo, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "cannot resolve HEAD").strip())
    return result.stdout.strip()


def create_validation_sandbox(repo: str, ref: str = "HEAD", confirm: str = "no") -> dict:
    """Create a detached worktree from committed Git state, outside the real project."""
    if not _auto_ok(confirm):
        raise PermissionError("sandbox creation requires confirmation or trusted/admin mode")
    source = Path(_resolve_path(repo, must_exist=True)).resolve()
    if not source.is_dir():
        raise ValueError(f"repo is not a directory: {source}")
    check = _git(source, ["rev-parse", "--show-toplevel"])
    if check.returncode != 0:
        raise ValueError("repo is not a Git worktree")
    top = Path(check.stdout.strip()).resolve()
    # Re-apply allowed-root policy to Git's discovered root.
    top = Path(_resolve_path(str(top), must_exist=True)).resolve()
    sandbox_id = uuid.uuid4().hex[:12]
    worktrees, _ = _locations()
    destination = (worktrees / sandbox_id).resolve()
    worktrees.mkdir(parents=True, exist_ok=True)
    result = _git(top, ["worktree", "add", "--detach", str(destination), ref], timeout=180)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git worktree add failed").strip())
    manifest = {
        "id": sandbox_id,
        "source_repo": str(top),
        "path": str(destination),
        "ref": str(ref),
        "base_commit": _head(destination),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "active",
    }
    _write_manifest(manifest)
    _audit({"tool": "create_validation_sandbox", **manifest})
    return {**manifest, "note": "Sandbox starts from committed Git state; source changes are untouched."}


def list_validation_sandboxes() -> list:
    """List managed sandboxes without traversing arbitrary temporary directories."""
    _, manifests = _locations()
    if not manifests.is_dir():
        return []
    items = []
    for path in sorted(manifests.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            data["exists"] = Path(data.get("path", "")).is_dir()
            items.append(data)
        except (OSError, ValueError, TypeError):
            continue
    return items


def review_validation_sandbox(sandbox_id: str) -> str:
    """Review one exact managed sandbox through the secret-redacting Git review path."""
    data = _load_manifest(sandbox_id)
    worktrees, _ = _locations()
    destination = Path(data["path"]).resolve()
    destination.relative_to(worktrees.resolve())
    if not destination.is_dir():
        raise FileNotFoundError(f"validation sandbox is missing: {sandbox_id}")
    return (
        f"Validation sandbox {sandbox_id}\n"
        f"source={data['source_repo']}\nref={data['ref']}\npath={destination}\n\n"
        + review_git_changes(repo=str(destination))
    )


def record_sandbox_validation(sandbox_id: str, checks: list, threshold: int = 95) -> dict:
    """Bind a passing evidence report to the sandbox's exact current commit."""
    data = _load_manifest(sandbox_id)
    worktrees, _ = _locations()
    destination = Path(data["path"]).resolve()
    destination.relative_to(worktrees.resolve())
    if not destination.is_dir():
        raise FileNotFoundError(f"validation sandbox is missing: {sandbox_id}")
    status = _git(destination, ["status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("sandbox must have all intended changes committed before validation")
    report = evaluate_validation(checks, threshold)
    data["validation"] = report
    data["validated_head"] = _head(destination)
    data["validated_at"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(data)
    _audit({
        "tool": "record_sandbox_validation", "id": sandbox_id,
        "validated_head": data["validated_head"],
        "ready_to_promote": report["ready_to_promote"],
    })
    return {
        "id": sandbox_id, "validated_head": data["validated_head"],
        "validation": report,
    }


def promote_validation_sandbox(sandbox_id: str, confirm: str = "no") -> dict:
    """Fast-forward exact validated sandbox commits when the source has not drifted."""
    if not _auto_ok(confirm):
        raise PermissionError("sandbox promotion requires confirmation or trusted/admin mode")
    data = _load_manifest(sandbox_id)
    worktrees, _ = _locations()
    destination = Path(data["path"]).resolve()
    destination.relative_to(worktrees.resolve())
    source = Path(_resolve_path(data["source_repo"], must_exist=True)).resolve()
    if not destination.is_dir():
        raise FileNotFoundError(f"validation sandbox is missing: {sandbox_id}")
    validation = data.get("validation") or {}
    if not validation.get("ready_to_promote"):
        raise PermissionError("sandbox evidence gate has not passed")
    sandbox_head = _head(destination)
    if data.get("validated_head") != sandbox_head:
        raise ValueError("sandbox changed after validation; validate the current commit again")
    if data.get("base_commit") != _head(source):
        raise ValueError("source repository changed after sandbox creation; recreate or rebase safely")
    for label, repo in (("source", source), ("sandbox", destination)):
        status = _git(repo, ["status", "--porcelain"])
        if status.returncode != 0 or status.stdout.strip():
            raise ValueError(f"{label} worktree must be clean before promotion")
    ancestor = _git(source, ["merge-base", "--is-ancestor", data["base_commit"], sandbox_head])
    if ancestor.returncode != 0 or sandbox_head == data["base_commit"]:
        raise ValueError("sandbox has no promotable commits descending from its baseline")
    result = _git(source, ["merge", "--ff-only", sandbox_head], timeout=180)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "fast-forward promotion failed").strip())
    data["state"] = "promoted"
    data["promoted_head"] = sandbox_head
    data["promoted_at"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(data)
    _audit({"tool": "promote_validation_sandbox", "id": sandbox_id, "head": sandbox_head})
    return {
        "id": sandbox_id, "state": "promoted", "source_repo": str(source),
        "promoted_head": sandbox_head, "confidence_percent": validation["confidence_percent"],
    }


def discard_validation_sandbox(sandbox_id: str, confirm: str = "no") -> dict:
    """Remove one exact managed worktree; never accepts an arbitrary deletion path."""
    if not _auto_ok(confirm):
        raise PermissionError("sandbox discard requires confirmation or trusted/admin mode")
    manifest_path = _manifest_path(sandbox_id)
    data = _load_manifest(sandbox_id)
    worktrees, _ = _locations()
    destination = Path(data["path"]).resolve()
    destination.relative_to(worktrees.resolve())
    source = Path(_resolve_path(data["source_repo"], must_exist=True)).resolve()
    result = _git(source, ["worktree", "remove", "--force", str(destination)], timeout=180)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git worktree remove failed").strip())
    manifest_path.unlink()
    _audit({"tool": "discard_validation_sandbox", "id": sandbox_id, "path": str(destination)})
    return {"id": sandbox_id, "path": str(destination), "state": "discarded"}
