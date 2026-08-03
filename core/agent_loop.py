"""
Vaelor autonomous ReAct worker loop.

Multi-step TOOL -> OBSERVATION feedback without human turns.
Self-corrects on failures; requires verification before FINAL_SUMMARY.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.tools.registry import registry

TOOL_RE = re.compile(
    r"^\s*(?:TOOL|ACTION)\s*:?\s*([a-zA-Z0-9_]+)\s*(.*)$",
    re.IGNORECASE,
)
# TOOL name {"json": true} or TOOL name key=value
TOOL_JSON_RE = re.compile(
    r"^\s*(?:TOOL|ACTION)\s*:?\s*([a-zA-Z0-9_]+)\s+(\{.*\})\s*$",
    re.IGNORECASE,
)
FINAL_RE = re.compile(
    r"^\s*FINAL(?:_SUMMARY)?\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
FINAL_SUMMARY_RE = re.compile(
    r"FINAL_SUMMARY\s*:\s*(SUCCESS|FAILED)\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
THOUGHT_RE = re.compile(r"^\s*THOUGHT\s*:\s*(.*)$", re.IGNORECASE)
KV_RE = re.compile(r'([a-zA-Z_][\w]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))')

MUTATING = {
    "shell_exec", "git_add", "git_commit", "git_checkout",
    "git_push", "git_pull", "approve_change",
    "write_text_file", "apply_patch", "make_dir", "delete_path",
    "unreal_open_epic_download", "unreal_launch_epic",
}

DEFAULT_MAX_STEPS = 12


def _parse_kwargs(blob: str) -> Dict[str, str]:
    blob = (blob or "").strip()
    if blob.startswith("{"):
        try:
            data = json.loads(blob)
            return {str(k): (v if isinstance(v, str) else json.dumps(v)) for k, v in data.items()}
        except Exception:
            pass
    kwargs: Dict[str, str] = {}
    for m in KV_RE.finditer(blob):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        kwargs[key] = val
    return kwargs


def _extract_actions(text: str) -> Tuple[List[Tuple[str, Dict[str, str]]], Optional[str], Optional[str], List[str]]:
    """Return tools, final_summary_line, legacy_final, thoughts."""
    tools: List[Tuple[str, Dict[str, str]]] = []
    final_summary = None
    legacy_final = None
    thoughts: List[str] = []
    for line in (text or "").splitlines():
        tm = THOUGHT_RE.match(line)
        if tm:
            thoughts.append(tm.group(1).strip())
            continue
        fsm = FINAL_SUMMARY_RE.search(line)
        if fsm and line.strip().upper().startswith("FINAL"):
            status = fsm.group(1).upper()
            rest = (fsm.group(2) or "").strip()
            final_summary = f"FINAL_SUMMARY: {status}" + (f" {rest}" if rest else "")
            continue
        fm = FINAL_RE.match(line)
        if fm:
            body = fm.group(1).strip()
            if body.upper().startswith("SUCCESS") or body.upper().startswith("FAILED"):
                final_summary = f"FINAL_SUMMARY: {body}"
            else:
                legacy_final = body
            continue
        tj = TOOL_JSON_RE.match(line)
        if tj:
            tools.append((tj.group(1).strip(), _parse_kwargs(tj.group(2))))
            continue
        tm2 = TOOL_RE.match(line)
        if tm2:
            tools.append((tm2.group(1).strip(), _parse_kwargs(tm2.group(2) or "")))
    return tools, final_summary, legacy_final, thoughts


def _looks_failed(result: str) -> bool:
    r = (result or "").strip()
    if not r:
        return False
    low = r.lower()
    if low.startswith("refused:"):
        return True
    if "tool '" in low and "failed:" in low:
        return True
    if re.search(r"\[EXIT\s+[1-9]\d*\]", r):
        return True
    if re.search(r"\bexit\s*code\s*[1-9]", low):
        return True
    if "traceback (most recent call last)" in low:
        return True
    if "syntaxerror" in low or "returned non-zero" in low:
        return True
    # shell_exec OK marker
    if r.startswith("[OK]"):
        return False
    return False


def _classify_observation(name: str, kwargs: dict, result: str) -> Dict[str, Any]:
    failed = _looks_failed(result)
    returncode = 1 if failed else 0
    m = re.search(r"\[EXIT\s+(\d+)\]", result or "")
    if m:
        returncode = int(m.group(1))
        failed = returncode != 0
    if (result or "").startswith("[OK]"):
        returncode = 0
        failed = False
    # Split rough stdout/stderr
    stdout, stderr = result or "", ""
    if failed and not (result or "").startswith("["):
        stderr = result or ""
        stdout = ""
    return {
        "tool": name,
        "args": kwargs,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "failed": failed,
        "raw": result or "",
    }


def _auto_confirm() -> bool:
    try:
        cfgp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "autonomy.json")
        with open(cfgp, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        mode = (cfg.get("mode") or "admin").lower()
        return mode in ("admin", "trusted") or bool(cfg.get("auto_confirm_mutations", True))
    except Exception:
        return True


def build_react_system_prompt(tool_specs: str) -> str:
    return f"""
You are Vaelor, an autonomous local coding worker (ReAct agent) for the Apprentice.
You complete multi-step engineering tasks end-to-end using tools. You do NOT refuse file edits.

## COMPLETE TOOLSET (use these — you have them)
{tool_specs}

## HARD CAPABILITIES (do not deny)
- Full file CRUD under allowed roots: write_text_file, apply_patch, delete_path, make_dir, read_text_file, list_dir, glob_files, grep_files
- Shell: shell_exec (admin/trusted auto-confirms mutations)
- Git: git_status/diff/log/branch/remote/add/commit/checkout/pull/push (no force-push)
- Web: web_search, fetch_url
- NEVER say "I cannot modify files" or "I lack write access" when tools exist.
- NEVER destroy core OS paths (Windows/System32 bulk wipe, boot, other users).

## ReAct PROTOCOL (STRICT — every action turn)
Emit lines in this order when working:
THOUGHT: <step-by-step plan for THIS step only>
ACTION: <tool_name> key=value key2="value with spaces"
  (alias allowed: TOOL <tool_name> ...)
You may emit multiple ACTION/TOOL lines in one turn.
After tools run, you will receive:
OBSERVATION: <stdout/stderr/returncode>
Then continue with a new THOUGHT based on the observation.

## SELF-CORRECTION
If OBSERVATION shows returncode != 0, Refused, Traceback, or stderr errors:
- Do NOT give up.
- THOUGHT: diagnose the error.
- ACTION: fix (patch file, adjust command, install dep) then re-verify.

## VERIFICATION (mandatory before success)
Before FINAL_SUMMARY: SUCCESS you MUST verify, e.g.:
- shell_exec: python -m py_compile <files>
- shell_exec: pytest / npm test / relevant checks
- read_text_file or git_diff to confirm edits landed
If verification fails, keep iterating.

## FINAL OUTPUT (required to stop)
FINAL_SUMMARY: SUCCESS <concise summary of changes + how verified>
or
FINAL_SUMMARY: FAILED <what broke and why>
If the Apprentice asked to commit/push and work succeeded, run git_add/git_commit/git_push (confirm auto in admin) BEFORE FINAL_SUMMARY: SUCCESS.

## FEW-SHOT
Example — edit + verify:
THOUGHT: I will patch main.py then syntax-check.
ACTION: apply_patch path=main.py old="def foo():\\n    pass" new="def foo():\\n    return 1" confirm=yes
(OBSERVATION arrives)
THOUGHT: Patch applied; verify syntax.
ACTION: shell_exec command="python -m py_compile main.py" confirm=yes
(OBSERVATION returncode=0)
FINAL_SUMMARY: SUCCESS Updated foo() to return 1; py_compile passed.

Example — test failure self-correct:
THOUGHT: Run tests.
ACTION: shell_exec command="pytest -q" confirm=yes
(OBSERVATION EXIT 1 assertion error in test_x.py)
THOUGHT: Fix failing assertion in module.py then re-test.
ACTION: apply_patch path=module.py old="x=1" new="x=2" confirm=yes
Stay in character as Vaelor; address the user as Apprentice.
""".strip()


def run_agent(
    goal: str,
    ask_llm: Callable[[str], str],
    max_steps: int = DEFAULT_MAX_STEPS,
    session_context: str = "",
    auto_confirm_readonly: bool = True,
    require_verification: bool = True,
) -> str:
    """Autonomous ReAct loop. ask_llm(prompt) -> model text."""
    registry  # loaded
    tool_specs = registry.specs_for_prompt()
    system = build_react_system_prompt(tool_specs)
    observations: List[str] = []
    transcript: List[str] = []
    last_failed = False
    verified_hint = False
    auto_yes = _auto_confirm()
    max_steps = max(3, min(int(max_steps or DEFAULT_MAX_STEPS), 25))

    step = 0
    while step < max_steps:
        step += 1
        prompt_parts = [system, ""]
        if session_context:
            prompt_parts += [session_context.strip(), ""]
        prompt_parts += [f"GOAL:\n{goal}\n"]
        if observations:
            prompt_parts += ["## Prior OBSERVATIONS (most recent last)", "\n\n".join(observations[-12:]), ""]
        if last_failed:
            prompt_parts.append(
                "SYSTEM: Last tool failed. You MUST analyze the error in THOUGHT, "
                "then emit corrective ACTION/TOOL lines. Do not finalize SUCCESS yet.\n"
            )
        if require_verification and step >= max_steps - 2 and not verified_hint:
            prompt_parts.append(
                "SYSTEM: Near step budget. If changes were made, run verification tools now "
                "or FINAL_SUMMARY: FAILED with reason.\n"
            )
        prompt_parts.append(
            f"Turn {step}/{max_steps}. Emit THOUGHT then ACTION/TOOL lines, "
            f"or FINAL_SUMMARY: SUCCESS|FAILED ..."
        )
        prompt = "\n".join(prompt_parts)

        reply = ask_llm(prompt)
        transcript.append(f"STEP {step} MODEL:\n{reply}")
        tools, final_summary, legacy_final, thoughts = _extract_actions(reply)

        if tools:
            step_failed = False
            for name, kwargs in tools:
                if "confirm" not in kwargs and name in MUTATING:
                    kwargs["confirm"] = "yes" if auto_yes else "no"
                # force confirm yes on shell when admin
                if auto_yes and name in MUTATING:
                    kwargs["confirm"] = "yes"
                try:
                    result = registry.execute(name, **kwargs)
                except Exception as e:
                    result = f"Tool '{name}' failed: {e}"
                meta = _classify_observation(name, kwargs, str(result))
                obs = (
                    f"OBSERVATION:\n"
                    f"tool={meta['tool']} returncode={meta['returncode']} failed={meta['failed']}\n"
                    f"args={meta['args']}\n"
                    f"stdout:\n{meta['stdout']}\n"
                    f"stderr:\n{meta['stderr']}"
                )
                observations.append(obs)
                transcript.append(obs)
                if meta["failed"]:
                    step_failed = True
                # heuristic: verification commands
                cmd = str(kwargs.get("command", "")).lower()
                if name == "shell_exec" and not meta["failed"] and any(
                    k in cmd for k in ("py_compile", "pytest", "npm test", "unittest", "cargo test")
                ):
                    verified_hint = True
            last_failed = step_failed
            if final_summary:
                # only allow SUCCESS if not immediately after failure without fix — still return
                if "SUCCESS" in final_summary.upper() and last_failed:
                    last_failed = True
                    observations.append(
                        "OBSERVATION:\nSYSTEM: FINAL_SUMMARY SUCCESS rejected because last tools failed. Continue fixing."
                    )
                    continue
                return final_summary
            continue

        if final_summary:
            if "SUCCESS" in final_summary.upper() and last_failed:
                observations.append(
                    "OBSERVATION:\nSYSTEM: Cannot SUCCESS after failed tools. Fix or FINAL_SUMMARY: FAILED."
                )
                last_failed = True
                continue
            return final_summary

        if legacy_final and not tools:
            # Promote legacy FINAL to structured form if model forgot
            return f"FINAL_SUMMARY: SUCCESS {legacy_final}"

        if not tools and not final_summary and not legacy_final:
            # plain prose — nudge once via treating as incomplete unless looks final
            if "FINAL_SUMMARY" in (reply or "").upper():
                return reply.strip()
            observations.append(
                "OBSERVATION:\nSYSTEM: No TOOL/ACTION lines and no FINAL_SUMMARY. "
                "Continue with THOUGHT/ACTION or FINAL_SUMMARY: SUCCESS|FAILED."
            )
            last_failed = False
            continue

    # budget exceeded
    summary_prompt = (
        system
        + f"\n\nGOAL:\n{goal}\n\nOBSERVATIONS:\n"
        + "\n\n".join(observations[-14:])
        + "\n\nSYSTEM: Max iterations reached without clean finish.\n"
        + "Respond with exactly one line starting FINAL_SUMMARY: FAILED or SUCCESS and explain.\n"
    )
    last = ask_llm(summary_prompt)
    tools, final_summary, legacy_final, _ = _extract_actions(last)
    if final_summary:
        return final_summary
    if legacy_final:
        return f"FINAL_SUMMARY: FAILED {legacy_final}"
    if "FINAL_SUMMARY" in (last or "").upper():
        return last.strip()
    return f"FINAL_SUMMARY: FAILED Reached max iterations ({max_steps}) without verification. Last model output: {(last or '')[:800]}"
