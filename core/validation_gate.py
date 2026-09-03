"""Engine-agnostic evidence contracts and honest confidence gates."""
from __future__ import annotations

from typing import Any, Dict, List


VALID_STATUSES = {"passed", "failed", "unknown", "skipped"}
MAX_CHECKS = 100


def evaluate_validation(checks: List[Dict[str, Any]], threshold: int = 95) -> dict:
    """Score supplied evidence without allowing unknown checks to inflate confidence."""
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks must be a non-empty list")
    if len(checks) > MAX_CHECKS:
        raise ValueError(f"checks cannot exceed {MAX_CHECKS}")
    threshold = max(1, min(int(threshold or 95), 100))
    normalized = []
    total_weight = 0.0
    passed_weight = 0.0
    blockers = []
    unknowns = []
    for index, raw in enumerate(checks):
        if not isinstance(raw, dict):
            raise ValueError(f"check {index + 1} must be an object")
        name = str(raw.get("name") or "").strip()
        status = str(raw.get("status") or "unknown").lower().strip()
        evidence = str(raw.get("evidence") or "").strip()
        required = bool(raw.get("required", True))
        try:
            weight = float(raw.get("weight", 1))
        except (TypeError, ValueError):
            raise ValueError(f"check {index + 1} has invalid weight")
        if not name:
            raise ValueError(f"check {index + 1} requires a name")
        if status not in VALID_STATUSES:
            raise ValueError(f"check {name!r} has invalid status: {status}")
        if weight <= 0 or weight > 100:
            raise ValueError(f"check {name!r} weight must be between 0 and 100")
        total_weight += weight
        if status == "passed":
            passed_weight += weight
        if required and status == "failed":
            blockers.append(name)
        if required and status in {"unknown", "skipped"}:
            unknowns.append(name)
        normalized.append({
            "name": name[:200], "status": status, "required": required,
            "weight": weight, "evidence": evidence[:4000],
        })
    confidence = round(100 * passed_weight / total_weight, 1) if total_weight else 0.0
    ready = confidence >= threshold and not blockers and not unknowns
    return {
        "ready_to_promote": ready,
        "confidence_percent": confidence,
        "threshold_percent": threshold,
        "summary": {
            status: sum(1 for check in normalized if check["status"] == status)
            for status in sorted(VALID_STATUSES)
        },
        "blocking_failures": blockers,
        "required_unknowns": unknowns,
        "checks": normalized,
        "rule": "Unknown, skipped, or failed evidence earns no confidence credit.",
    }
