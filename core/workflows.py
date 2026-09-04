"""Bounded, inspectable project workflows that never bypass normal tool policy."""
from __future__ import annotations

import json
from pathlib import Path
import re

from core.project_context import _git_root, resolve_workspace


WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_WORKFLOW_BYTES = 32768
MAX_WORKFLOW_STEPS = 16
MAX_WORKFLOWS = 50
RISK_ORDER = {"read": 0, "low": 1, "medium": 2, "high": 3}
PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z0-9][A-Za-z0-9_-]{0,63})\}")
RESERVED_INPUTS = {"workspace"}


def _roots(workspace: Path) -> tuple[Path, list[Path]]:
    discovered = _git_root(workspace)
    try:
        root = resolve_workspace(str(discovered)) if discovered else workspace
    except (ValueError, PermissionError, FileNotFoundError):
        root = workspace
    try:
        relative = workspace.relative_to(root)
    except ValueError:
        root = workspace
        relative = Path(".")
    directories = [root]
    current = root
    for part in relative.parts:
        if part == ".":
            continue
        current = current / part
        directories.append(current)
    return root, directories


def _workflow_files(workspace: Path) -> tuple[Path, dict[str, Path]]:
    root, directories = _roots(workspace)
    found: dict[str, Path] = {}
    for directory in directories:
        workflow_dir = directory / ".vaelor" / "workflows"
        if not workflow_dir.is_dir():
            continue
        for candidate in sorted(workflow_dir.glob("*.json"), key=lambda p: p.name.casefold()):
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            name = candidate.stem
            if WORKFLOW_NAME_RE.fullmatch(name):
                key = name.casefold()
                if key in found or len(found) < MAX_WORKFLOWS:
                    found[key] = resolved  # deeper directories intentionally override
    return root, found


def _load(path: Path, root: Path) -> dict:
    if path.stat().st_size > MAX_WORKFLOW_BYTES:
        raise ValueError(f"workflow exceeds {MAX_WORKFLOW_BYTES} bytes")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("workflow must be a JSON object")
    name = str(data.get("name", path.stem)).strip()
    if name.casefold() != path.stem.casefold() or not WORKFLOW_NAME_RE.fullmatch(name):
        raise ValueError("workflow name must match its filename")
    description = " ".join(str(data.get("description", "")).split())[:500]
    raw_inputs = data.get("inputs", {})
    if not isinstance(raw_inputs, dict) or len(raw_inputs) > 20:
        raise ValueError("workflow inputs must be an object with at most 20 entries")
    inputs = {}
    for key, value in raw_inputs.items():
        if not WORKFLOW_NAME_RE.fullmatch(str(key)):
            raise ValueError(f"invalid workflow input name: {key}")
        inputs[str(key)] = str(value)[:500]
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_WORKFLOW_STEPS:
        raise ValueError(f"workflow must contain 1-{MAX_WORKFLOW_STEPS} steps")

    from core.tools.registry import registry
    validated = []
    highest_risk = "read"
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{index}] must be an object")
        tool_name = step.get("tool")
        arguments = step.get("arguments", {})
        tool = registry.get(tool_name) if isinstance(tool_name, str) else None
        if tool is None or tool_name in {"list_project_workflows", "read_project_workflow"}:
            raise ValueError(f"steps[{index}] names an unknown or recursive tool")
        if not isinstance(arguments, dict):
            raise ValueError(f"steps[{index}].arguments must be an object")
        placeholders = set(PLACEHOLDER_RE.findall(json.dumps(arguments, ensure_ascii=False)))
        undeclared = sorted(placeholders - set(inputs) - RESERVED_INPUTS)
        if undeclared:
            raise ValueError(
                f"steps[{index}] uses undeclared input(s): " + ", ".join(undeclared)
            )
        error = registry.validate_call(tool_name, arguments)
        if error:
            raise ValueError(f"steps[{index}] is invalid: {error}")
        risk = tool.risk
        if RISK_ORDER[risk] > RISK_ORDER[highest_risk]:
            highest_risk = risk
        validated.append({"tool": tool_name, "arguments": arguments, "risk": risk})
    return {
        "name": name,
        "description": description,
        "inputs": inputs,
        "steps": validated,
        "highest_risk": highest_risk,
        "source": path.relative_to(root).as_posix(),
        "policy": (
            "Substitute declared inputs and ${workspace}, then execute each step through the "
            "normal agent action and approval pipeline. Step risk is recalculated at execution."
        ),
    }


def list_project_workflows(workspace: str) -> str:
    """List valid workflows in effective broad-to-specific project scope."""
    resolved = resolve_workspace(workspace)
    root, files = _workflow_files(resolved)
    workflows = []
    for path in files.values():
        try:
            item = _load(path, root)
            workflows.append({key: item[key] for key in (
                "name", "description", "inputs", "highest_risk", "source"
            )})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            workflows.append({"name": path.stem, "source": path.relative_to(root).as_posix(), "error": str(exc)})
    return json.dumps({"workflows": workflows}, indent=2)


def read_project_workflow(workspace: str, name: str) -> str:
    """Read and validate one effective project workflow without executing it."""
    if not WORKFLOW_NAME_RE.fullmatch(str(name or "")):
        raise ValueError("invalid workflow name")
    resolved = resolve_workspace(workspace)
    root, files = _workflow_files(resolved)
    path = files.get(name.casefold())
    if path is None:
        raise KeyError(f"unknown project workflow: {name}")
    return json.dumps(_load(path, root), indent=2)
