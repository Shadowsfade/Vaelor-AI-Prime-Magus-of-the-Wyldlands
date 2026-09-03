"""Validated JSON protocol for Vaelor agent decisions and tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Dict, List, Optional, Tuple


TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.I | re.S)
MAX_ACTIONS_PER_TURN = 8


@dataclass
class ProtocolResponse:
    matched: bool = False
    actions: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    final_summary: Optional[str] = None
    thoughts: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _candidate(text: str) -> Tuple[bool, str]:
    raw = (text or "").strip()
    fenced = JSON_FENCE_RE.match(raw)
    if fenced:
        return True, fenced.group(1).strip()
    if raw.startswith("{"):
        return True, raw
    return False, raw


def parse_structured_response(text: str) -> ProtocolResponse:
    """Parse and validate one structured agent response without executing it."""
    matched, raw = _candidate(text)
    if not matched:
        return ProtocolResponse(matched=False)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return ProtocolResponse(matched=True, error=f"Invalid JSON: {exc}")
    if not isinstance(data, dict):
        return ProtocolResponse(matched=True, error="Response must be a JSON object.")

    thought = data.get("thought", "")
    if thought is not None and not isinstance(thought, str):
        return ProtocolResponse(matched=True, error="'thought' must be a string.")
    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        return ProtocolResponse(matched=True, error="'actions' must be an array.")
    if len(raw_actions) > MAX_ACTIONS_PER_TURN:
        return ProtocolResponse(matched=True, error=f"A turn may contain at most {MAX_ACTIONS_PER_TURN} actions.")

    actions: List[Tuple[str, Dict[str, Any]]] = []
    for index, action in enumerate(raw_actions):
        if not isinstance(action, dict):
            return ProtocolResponse(matched=True, error=f"actions[{index}] must be an object.")
        tool = action.get("tool")
        arguments = action.get("arguments", {})
        if not isinstance(tool, str) or not TOOL_NAME_RE.fullmatch(tool):
            return ProtocolResponse(matched=True, error=f"actions[{index}].tool must be a valid tool name.")
        if not isinstance(arguments, dict):
            return ProtocolResponse(matched=True, error=f"actions[{index}].arguments must be an object.")
        actions.append((tool, arguments))

    final_summary = None
    final = data.get("final")
    if final is not None:
        if not isinstance(final, dict):
            return ProtocolResponse(matched=True, error="'final' must be an object or null.")
        status = final.get("status")
        summary = final.get("summary", "")
        if not isinstance(status, str) or status.upper() not in {"SUCCESS", "FAILED"}:
            return ProtocolResponse(matched=True, error="final.status must be 'SUCCESS' or 'FAILED'.")
        if not isinstance(summary, str):
            return ProtocolResponse(matched=True, error="final.summary must be a string.")
        final_summary = f"FINAL_SUMMARY: {status.upper()}"
        if summary.strip():
            final_summary += " " + summary.strip()

    if not actions and final_summary is None:
        return ProtocolResponse(matched=True, error="Response must contain at least one action or a final result.")
    return ProtocolResponse(
        matched=True,
        actions=actions,
        final_summary=final_summary,
        thoughts=[thought.strip()] if thought and thought.strip() else [],
    )
