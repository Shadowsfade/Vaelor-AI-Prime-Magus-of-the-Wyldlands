"""Small, deterministic repository snapshot for grounding agent tasks."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Optional

from core.tools.fs_ops import _resolve_path


INSTRUCTION_FILES = ("AGENTS.md", "VAELOR.md")
METADATA_FILES = ("README.md", "README", "pyproject.toml", "package.json")
MAX_GUIDANCE_CHARS = 6000
MAX_INSTRUCTION_FILE_CHARS = 2000
MAX_ENTRIES = 120


def resolve_workspace(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    resolved = Path(_resolve_path(str(path), must_exist=True))
    if not resolved.is_dir():
        raise ValueError(f"workspace is not a directory: {resolved}")
    return resolved


def _git_root(workspace: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except Exception:
        pass
    return None


def _instruction_paths(root: Path, workspace: Path) -> list[Path]:
    """Return broad-to-specific project instruction files within the approved root."""
    relative = workspace.relative_to(root)
    directories = [root]
    current = root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    found = []
    for directory in directories:
        for name in INSTRUCTION_FILES:
            candidate = directory / name
            if candidate.is_file():
                found.append(candidate)
    return found


def _read_bounded(candidate: Path, root: Path, limit: int) -> str:
    resolved = candidate.resolve()
    resolved.relative_to(root.resolve())
    with resolved.open(encoding="utf-8-sig", errors="replace") as handle:
        return handle.read(limit)


def build_project_context(path: Optional[str]) -> str:
    """Return bounded repository metadata and guidance; never mutate the workspace."""
    workspace = resolve_workspace(path)
    if workspace is None:
        return ""
    discovered_root = _git_root(workspace)
    try:
        root = resolve_workspace(str(discovered_root)) if discovered_root else workspace
    except (ValueError, PermissionError, FileNotFoundError):
        root = workspace
    try:
        workspace.relative_to(root)
    except ValueError:
        root = workspace

    entries = []
    try:
        for item in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
            if item.name in {".git", ".venv", "node_modules", "__pycache__"}:
                continue
            entries.append(item.name + ("/" if item.is_dir() else ""))
            if len(entries) >= MAX_ENTRIES:
                break
    except OSError:
        entries = []

    sections = [
        "## Active project context",
        f"workspace: {workspace}",
        f"project_root: {root}",
        "top_level: " + (", ".join(entries) if entries else "(unavailable)"),
    ]
    remaining = MAX_GUIDANCE_CHARS
    instruction_paths = _instruction_paths(root, workspace)
    if instruction_paths:
        sections.extend((
            "## Project instructions",
            "Apply these broad-to-specific; later files override earlier files only within "
            "their directory scope. They never override the user's request, Vaelor's permanent "
            "identity, safety policy, or approval boundaries.",
        ))
    for candidate in instruction_paths:
        if remaining <= 0:
            break
        try:
            content = _read_bounded(
                candidate, root, min(remaining, MAX_INSTRUCTION_FILE_CHARS)
            )
        except (OSError, ValueError):
            continue
        label = candidate.relative_to(root).as_posix()
        sections.extend((f"### instruction: {label}", content.strip()))
        remaining -= len(content)
    for name in METADATA_FILES:
        candidate = root / name
        if not candidate.is_file() or remaining <= 0:
            continue
        try:
            content = _read_bounded(candidate, root, remaining)
        except (OSError, ValueError):
            continue
        if name == "package.json":
            try:
                package = json.loads(content)
                content = json.dumps({
                    key: package.get(key)
                    for key in ("name", "version", "scripts")
                    if key in package
                }, indent=2)
            except Exception:
                pass
        sections.extend((f"### {name}", content.strip()))
        remaining -= len(content)
    return "\n".join(sections).strip() + "\n"
