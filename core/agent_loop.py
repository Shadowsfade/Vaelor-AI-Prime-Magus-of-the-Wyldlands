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
from core.action_protocol import parse_structured_response

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
MAX_TOOL_RESULT_CHARS = 12000
MAX_OBSERVATION_CONTEXT_CHARS = 30000


def _bounded_text(value: Any, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    marker = f"\n...[truncated {len(text) - limit} or more chars]...\n"
    available = max(2, limit - len(marker))
    head = max(1, int(available * 0.7))
    tail = max(1, available - head)
    return text[:head] + marker + text[-tail:]


def _recent_observations(observations: List[str], limit: int = MAX_OBSERVATION_CONTEXT_CHARS) -> str:
    selected = []
    used = 0
    for observation in reversed(observations):
        separator = 2 if selected else 0
        remaining = limit - used - separator
        if remaining <= 0:
            break
        piece = observation if len(observation) <= remaining else observation[-remaining:]
        selected.append(piece)
        used += len(piece) + separator
    return "\n\n".join(reversed(selected))


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
    if low.startswith("unknown tool:"):
        return True
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
        # Missing or malformed policy must never grant mutation access.
        return False


def _is_verification_action(name: str, kwargs: dict) -> bool:
    """Return whether a tool call is a recognized, outcome-bearing check."""
    if name != "shell_exec":
        return False
    cmd = str(kwargs.get("command", "")).lower()
    return any(
        marker in cmd
        for marker in (
            "py_compile", "pytest", "unittest", "npm test", "npm run test",
            "pnpm test", "yarn test", "cargo test", "go test", "dotnet test",
        )
    )


def _is_mutating_action(name: str) -> bool:
    """Use registry metadata as the source of truth, with a safe fallback."""
    tool = registry.get(name)
    if tool is not None:
        return not tool.read_only
    return name in MUTATING


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

## ReAct PROTOCOL (STRICT — every turn)
Return exactly one JSON object:
{{
  "thought": "plan for this step only",
  "actions": [{{"tool": "tool_name", "arguments": {{"key": "typed value"}}}}],
  "final": null
}}
When stopping, use an empty actions array and:
"final": {{"status": "SUCCESS" or "FAILED", "summary": "concise result"}}
You may include final with actions only when those actions must succeed first.
Legacy ACTION/TOOL lines remain accepted for compatibility, but JSON is preferred.
After tools run, you will receive:
OBSERVATION: <stdout/stderr/returncode>
Then return a new JSON decision based on the observation.

## SELF-CORRECTION
If OBSERVATION shows returncode != 0, Refused, Traceback, or stderr errors:
- Do NOT give up.
- Diagnose the error in thought.
- Call a corrective tool, then re-verify.

## VERIFICATION (mandatory before success)
Before final.status SUCCESS you MUST verify, e.g.:
- shell_exec: python -m py_compile <files>
- shell_exec: pytest / npm test / relevant checks
If verification fails, keep iterating.

## FINAL OUTPUT (required to stop)
Return actions=[] and final with status SUCCESS or FAILED plus a concise summary.
If the Apprentice asked to commit/push and work succeeded, run git_add/git_commit/git_push before final SUCCESS.

## FEW-SHOT
Example — edit + verify:
{{"thought":"patch main.py","actions":[{{"tool":"apply_patch","arguments":{{"path":"main.py","old":"def foo():\\n    pass","new":"def foo():\\n    return 1"}}}}],"final":null}}
(OBSERVATION arrives)
{{"thought":"verify syntax","actions":[{{"tool":"shell_exec","arguments":{{"command":"python -m py_compile main.py"}}}}],"final":null}}
(OBSERVATION returncode=0)
{{"thought":"done","actions":[],"final":{{"status":"SUCCESS","summary":"Updated foo; py_compile passed."}}}}

Example — test failure self-correct:
{{"thought":"run tests","actions":[{{"tool":"shell_exec","arguments":{{"command":"pytest -q"}}}}],"final":null}}
(OBSERVATION EXIT 1 assertion error in test_x.py)
{{"thought":"fix failure","actions":[{{"tool":"apply_patch","arguments":{{"path":"module.py","old":"x=1","new":"x=2"}}}}],"final":null}}
Stay in character as Vaelor; address the user as Apprentice.
""".strip()


def run_agent(
    goal: str,
    ask_llm: Callable[[str], str],
    max_steps: int = DEFAULT_MAX_STEPS,
    session_context: str = "",
    auto_confirm_readonly: bool = True,
    require_verification: bool = True,
    event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    model_retries: int = 2,
) -> str:
    """Autonomous ReAct loop. ask_llm(prompt) -> model text."""
    registry  # loaded
    tool_specs = registry.specs_for_prompt()
    system = build_react_system_prompt(tool_specs)
    observations: List[str] = []
    transcript: List[str] = []
    last_failed = False
    verified_hint = False
    unverified_mutation = False
    auto_yes = _auto_confirm()
    max_steps = max(3, min(int(max_steps or DEFAULT_MAX_STEPS), 25))
    model_retries = max(0, min(int(model_retries or 0), 3))

    def emit(event_type: str, **data: Any) -> None:
        if event_callback is None:
            return
        try:
            event_callback(event_type, data)
        except Exception:
            # Progress recording must never break task execution.
            pass

    def cancelled() -> bool:
        try:
            return bool(should_cancel and should_cancel())
        except Exception:
            return False

    def ask_model(prompt: str, phase: str, step_number: int) -> str:
        last_error = None
        for attempt in range(model_retries + 1):
            if cancelled():
                emit("cancellation_observed", phase=f"before_{phase}", step=step_number)
                return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."
            try:
                return ask_llm(prompt)
            except Exception as exc:
                last_error = exc
                emit(
                    "model_retry",
                    phase=phase,
                    step=step_number,
                    attempt=attempt + 1,
                    retries_remaining=model_retries - attempt,
                    error=str(exc),
                )
        raise RuntimeError(
            f"Model call failed after {model_retries + 1} attempt(s): {last_error}"
        ) from last_error

    step = 0
    while step < max_steps:
        if cancelled():
            emit("cancellation_observed", phase="before_model")
            return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."
        step += 1
        prompt_parts = [system, ""]
        if session_context:
            prompt_parts += [session_context.strip(), ""]
        prompt_parts += [f"GOAL:\n{goal}\n"]
        if observations:
            prompt_parts += [
                "## Prior OBSERVATIONS (most recent last)",
                _recent_observations(observations),
                "",
            ]
        if last_failed:
            prompt_parts.append(
                "SYSTEM: Last tool failed. Analyze the error in thought, then return "
                "corrective JSON actions. Do not finalize SUCCESS yet.\n"
            )
        if require_verification and step >= max_steps - 2 and not verified_hint:
            prompt_parts.append(
                "SYSTEM: Near step budget. If changes were made, run verification tools now "
                "or return final.status FAILED with a reason.\n"
            )
        prompt_parts.append(
            f"Turn {step}/{max_steps}. Return one JSON protocol object."
        )
        prompt = "\n".join(prompt_parts)

        reply = ask_model(prompt, "decision", step)
        if reply.upper().startswith("FINAL_SUMMARY: CANCELLED"):
            return reply
        if cancelled():
            emit("cancellation_observed", phase="after_model", step=step)
            return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."
        transcript.append(f"STEP {step} MODEL:\n{reply}")
        structured = parse_structured_response(reply)
        if structured.matched and structured.error:
            emit("protocol_error", step=step, error=structured.error)
            observations.append(
                "OBSERVATION:\nSYSTEM: Invalid action protocol: " + structured.error
                + " Return one valid JSON object and try again."
            )
            # No tool ran, so this is a correctable format error rather than
            # an execution failure that should block a subsequent final result.
            last_failed = False
            continue
        if structured.matched:
            tools = structured.actions
            final_summary = structured.final_summary
            legacy_final = None
            thoughts = structured.thoughts
        else:
            tools, final_summary, legacy_final, thoughts = _extract_actions(reply)
        emit("decision", step=step, actions=[name for name, _ in tools], has_final=bool(final_summary or legacy_final))

        if tools:
            call_errors = []
            for index, (name, kwargs) in enumerate(tools):
                error = registry.validate_call(name, kwargs)
                if error:
                    call_errors.append(f"actions[{index}] {name}: {error}")
            if call_errors:
                emit("schema_error", step=step, errors=call_errors)
                observations.append(
                    "OBSERVATION:\nSYSTEM: Tool-call schema validation failed; no tools ran:\n- "
                    + "\n- ".join(call_errors)
                    + "\nCorrect the JSON arguments and try again."
                )
                last_failed = False
                continue
            step_failed = False
            for name, kwargs in tools:
                if cancelled():
                    emit("cancellation_observed", phase="before_tool", step=step, tool=name)
                    return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."
                is_verification = _is_verification_action(name, kwargs)
                is_mutating = _is_mutating_action(name)
                supports_confirm = registry.accepts_argument(name, "confirm")
                if "confirm" not in kwargs and is_mutating and supports_confirm:
                    kwargs["confirm"] = "yes" if auto_yes else "no"
                # force confirm yes on shell when admin
                if auto_yes and is_mutating and supports_confirm:
                    kwargs["confirm"] = "yes"
                emit("tool_started", step=step, tool=name, arguments=kwargs)
                try:
                    result = registry.execute(name, **kwargs)
                except Exception as e:
                    result = f"Tool '{name}' failed: {e}"
                meta = _classify_observation(name, kwargs, _bounded_text(result))
                emit(
                    "tool_completed",
                    step=step,
                    tool=name,
                    failed=meta["failed"],
                    returncode=meta["returncode"],
                    result=meta["raw"],
                )
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
                if is_verification and not meta["failed"]:
                    verified_hint = True
                    unverified_mutation = False
                elif is_mutating and not meta["failed"]:
                    # Any successful mutation after a check invalidates that check.
                    unverified_mutation = True
                    verified_hint = False
            last_failed = step_failed
            if final_summary:
                # only allow SUCCESS if not immediately after failure without fix — still return
                if "SUCCESS" in final_summary.upper() and last_failed:
                    last_failed = True
                    observations.append(
                        "OBSERVATION:\nSYSTEM: FINAL_SUMMARY SUCCESS rejected because last tools failed. Continue fixing."
                    )
                    continue
                if require_verification and "SUCCESS" in final_summary.upper() and unverified_mutation:
                    observations.append(
                        "OBSERVATION:\nSYSTEM: FINAL_SUMMARY SUCCESS rejected because changes "
                        "were made after the last passing verification. Run a relevant test."
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
            if require_verification and "SUCCESS" in final_summary.upper() and unverified_mutation:
                observations.append(
                    "OBSERVATION:\nSYSTEM: Cannot report SUCCESS: mutations have not been "
                    "verified. Run a relevant test first."
                )
                continue
            return final_summary

        if legacy_final and not tools:
            # Promote legacy FINAL to structured form if model forgot
            if require_verification and unverified_mutation:
                observations.append(
                    "OBSERVATION:\nSYSTEM: Cannot report SUCCESS: mutations have not been "
                    "verified. Run a relevant test first."
                )
                continue
            return f"FINAL_SUMMARY: SUCCESS {legacy_final}"

        if not tools and not final_summary and not legacy_final:
            # plain prose — nudge once via treating as incomplete unless looks final
            if "FINAL_SUMMARY" in (reply or "").upper():
                return reply.strip()
            observations.append(
                "OBSERVATION:\nSYSTEM: No TOOL/ACTION lines and no FINAL_SUMMARY. "
                "Return one structured JSON action or final result."
            )
            last_failed = False
            continue

    # budget exceeded
    if cancelled():
        emit("cancellation_observed", phase="before_summary")
        return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."
    summary_prompt = (
        system
        + f"\n\nGOAL:\n{goal}\n\nOBSERVATIONS:\n"
        + _recent_observations(observations)
        + "\n\nSYSTEM: Max iterations reached without clean finish.\n"
        + "Return one JSON object with actions=[] and final status SUCCESS or FAILED.\n"
    )
    last = ask_model(summary_prompt, "summary", max_steps)
    if last.upper().startswith("FINAL_SUMMARY: CANCELLED"):
        return last
    structured = parse_structured_response(last)
    if structured.matched and not structured.error:
        tools = structured.actions
        final_summary = structured.final_summary
        legacy_final = None
    else:
        tools, final_summary, legacy_final, _ = _extract_actions(last)
    if final_summary:
        if require_verification and unverified_mutation and "SUCCESS" in final_summary.upper():
            return "FINAL_SUMMARY: FAILED Reached max iterations with unverified changes."
        return final_summary
    if legacy_final:
        return f"FINAL_SUMMARY: FAILED {legacy_final}"
    if "FINAL_SUMMARY" in (last or "").upper():
        return last.strip()
    return f"FINAL_SUMMARY: FAILED Reached max iterations ({max_steps}) without verification. Last model output: {(last or '')[:800]}"
