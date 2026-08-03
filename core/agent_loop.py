"""
Free multi-step tool agent loop for Vaelor.

Uses the local LLM + registered tools. No paid APIs.
Protocol: model emits TOOL lines; loop executes and continues until FINAL.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from core.tools.registry import registry


TOOL_RE = re.compile(
    r"^\s*TOOL\s+([a-zA-Z0-9_]+)\s*(.*)$",
    re.IGNORECASE,
)
FINAL_RE = re.compile(r"^\s*FINAL\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
KV_RE = re.compile(r"([a-zA-Z_][\w]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))")


def _parse_kwargs(blob: str) -> Dict[str, str]:
    kwargs = {}
    for m in KV_RE.finditer(blob or ""):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        kwargs[key] = val
    return kwargs


def _extract_actions(text: str):
    """Return list of ('tool', name, kwargs) and optional final string."""
    tools = []
    final = None
    for line in (text or "").splitlines():
        fm = FINAL_RE.match(line)
        if fm:
            final = fm.group(1).strip()
            continue
        tm = TOOL_RE.match(line)
        if tm:
            name = tm.group(1).strip()
            kwargs = _parse_kwargs(tm.group(2) or "")
            tools.append((name, kwargs))
    # also allow FINAL block at end without prefix if no tools
    if final is None and not tools:
        # if model just answered normally
        final = text.strip() if text and "TOOL " not in text.upper() else None
    return tools, final


def run_agent(
    goal: str,
    ask_llm,
    max_steps: int = 10,
    session_context: str = "",
    auto_confirm_readonly: bool = True,
) -> str:
    """
    ask_llm(prompt: str) -> str
    """
    registry  # ensure loaded
    tool_specs = registry.specs_for_prompt()
    transcript: List[str] = []
    observations: List[str] = []

    system = f"""
You are Vaelor acting as a local free-tool agent for the Apprentice.
You may use ONLY these tools:

{tool_specs}

Protocol (strict):
- To call a tool, output one or more lines:
  TOOL <tool_name> key=value key2="value with spaces"
- When finished, output:
  FINAL: <your answer to the Apprentice>
- Prefer read-only tools first.
- Mutating tools (shell_exec writes, git_add/commit/push, approve_change) require confirm=yes.
- Never claim you ran a tool unless you emitted TOOL lines.
- Stay in character as Vaelor; address the Architect as Apprentice.
- You CAN create/edit/delete files under allowed roots (user profile, install/project drives) via write_text_file/apply_patch/delete_path/make_dir/shell_exec.
Never destroy core OS paths (Windows/System32/Program Files bulk wipe, boot, other users).
Auto-approval: in admin/trusted mode mutating tools should use confirm=yes.
Game consoles ONLY for hacking/homebrew: use console_homebrew_help and only verified public guides (switch.hacks.guide, 3ds.hacks.guide, etc). No non-console targets.
You may run admin-capable shell commands the OS allows for this user; still never OS-wipe.
""".strip()

    step = 0
    while step < max_steps:
        step += 1
        prompt = (
            system
            + "\n\n"
            + (session_context + "\n\n" if session_context else "")
            + f"Goal:\n{goal}\n\n"
        )
        if observations:
            prompt += "Observations so far:\n" + "\n\n".join(observations[-8:]) + "\n\n"
        prompt += (
            f"Step {step}/{max_steps}. "
            "Emit TOOL lines and/or a FINAL answer."
        )

        reply = ask_llm(prompt)
        transcript.append(f"STEP {step} MODEL:\n{reply}")
        tools, final = _extract_actions(reply)

        if tools:
            # Load autonomy: admin/trusted => auto-approve mutations
            auto_yes = True
            try:
                import json, os
                cfgp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "autonomy.json")
                with open(cfgp, "r", encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                mode = (cfg.get("mode") or "admin").lower()
                auto_yes = mode in ("admin", "trusted") or bool(cfg.get("auto_confirm_mutations", True))
            except Exception:
                auto_yes = True
            for name, kwargs in tools:
                # default confirm based on autonomy
                if "confirm" not in kwargs and name in {
                    "shell_exec", "git_add", "git_commit", "git_checkout",
                    "git_push", "git_pull", "approve_change",
                    "write_text_file", "apply_patch", "make_dir", "delete_path",
                }:
                    kwargs["confirm"] = "yes" if auto_yes else "no"
                result = registry.execute(name, **kwargs)
                obs = f"TOOL {name} {kwargs}\nRESULT:\n{result}"
                observations.append(obs)
                transcript.append(obs)

        if final:
            return final

        # If model returned tools but no final, continue loop with observations
        if not tools and not final:
            # plain text answer
            return reply.strip()

    # budget exceeded — summarize
    summary_prompt = (
        system
        + "\n\nGoal:\n"
        + goal
        + "\n\nObservations:\n"
        + "\n\n".join(observations[-10:])
        + "\n\nTool budget reached. Provide best FINAL answer now as Vaelor.\n"
        + "FINAL: "
    )
    last = ask_llm(summary_prompt)
    tools, final = _extract_actions(last)
    if final:
        return final
    if last.upper().startswith("FINAL:"):
        return last.split(":", 1)[1].strip()
    return last.strip()
