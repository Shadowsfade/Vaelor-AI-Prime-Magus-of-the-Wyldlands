"""Structured, fail-safe understanding of a user's requested task."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Callable, List, Optional


VALID_INTENTS = {"chat", "act"}


def _clean_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:8]


def _clean_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


@dataclass(frozen=True)
class TaskIntent:
    intent: str
    goal: str
    success_criteria: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""
    source: str = "model"

    @property
    def should_act(self) -> bool:
        return self.intent == "act" and not self.needs_clarification

    def as_agent_goal(self, original_request: str) -> str:
        criteria = self.success_criteria or ["The requested outcome is complete and verified."]
        constraints = self.constraints or ["Preserve unrelated user work."]
        return (
            f"ORIGINAL REQUEST:\n{original_request.strip()}\n\n"
            f"NORMALIZED GOAL:\n{self.goal}\n\n"
            "SUCCESS CRITERIA:\n- " + "\n- ".join(criteria) + "\n\n"
            "CONSTRAINTS:\n- " + "\n- ".join(constraints)
        )


def _extract_json(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.I | re.S)
    candidates = [fenced.group(1)] if fenced else []
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (TypeError, ValueError):
            continue
    return None


def parse_task_intent(text: str, original_request: str) -> Optional[TaskIntent]:
    data = _extract_json(text)
    if not data:
        return None
    intent = str(data.get("intent", "")).strip().lower()
    if intent not in VALID_INTENTS:
        return None
    goal = str(data.get("goal") or original_request).strip()
    needs_clarification = intent == "act" and _clean_bool(
        data.get("needs_clarification", False)
    )
    question = str(data.get("clarification_question") or "").strip()
    if needs_clarification and not question:
        question = "What outcome should I use to determine that this task is complete?"
    return TaskIntent(
        intent=intent,
        goal=goal,
        success_criteria=_clean_list(data.get("success_criteria")),
        constraints=_clean_list(data.get("constraints")),
        needs_clarification=needs_clarification,
        clarification_question=question,
    )


def classify_task(
    request: str,
    ask_classifier: Callable[[str], str],
    fallback_should_act: bool = False,
) -> TaskIntent:
    """Classify a request; malformed or unavailable model output falls back safely."""
    prompt = f"""
Classify the user's request for a local assistant. Return JSON only with this schema:
{{
  "intent": "chat" | "act",
  "goal": "concise normalized outcome",
  "success_criteria": ["observable completion condition"],
  "constraints": ["explicit user constraint only"],
  "needs_clarification": false,
  "clarification_question": ""
}}

Use intent=act only when the user wants real-world or computer work performed.
Use intent=chat for discussion, explanation, brainstorming, and questions.
Ask for clarification only when a missing fact would materially change or endanger the action.
Do not invent constraints. Do not execute the request.

USER REQUEST:
{request}
""".strip()
    try:
        parsed = parse_task_intent(ask_classifier(prompt), request)
        if parsed is not None:
            return parsed
    except Exception:
        pass
    return TaskIntent(
        intent="act" if fallback_should_act else "chat",
        goal=request.strip(),
        success_criteria=(
            ["The requested outcome is complete and verified."]
            if fallback_should_act else []
        ),
        source="fallback",
    )
