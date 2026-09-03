"""Truthful operational readiness checks for Vaelor."""
from __future__ import annotations

from pathlib import Path
from typing import Callable


def assess_readiness(brain, tools, detect_backends: Callable[[], dict]) -> dict:
    checks = {}
    issues = []

    registered = tools.list_tools()
    checks["tools"] = {"ok": bool(registered), "count": len(registered)}
    if not registered:
        issues.append("No tools are registered.")

    task_path = Path(brain.tasks.path)
    storage_ok = task_path.parent.exists() and task_path.exists()
    checks["task_storage"] = {"ok": storage_ok, "path": str(task_path)}
    if not storage_ok:
        issues.append("Durable task storage is unavailable.")

    try:
        backends = detect_backends() or {}
        running = []
        models = []
        for name, details in backends.items():
            if not isinstance(details, dict):
                continue
            if details.get("running") or details.get("ok"):
                running.append(name)
            models.extend(str(model) for model in (details.get("models") or []))
        checks["model_backend"] = {
            "ok": bool(running and models),
            "running": running,
            "models": models[:50],
        }
        if not running:
            issues.append("No local model backend is running.")
        elif not models:
            issues.append("A model backend is running but no model is available.")
    except Exception as exc:
        checks["model_backend"] = {"ok": False, "error": str(exc)}
        issues.append("Local model backend detection failed.")

    ready = all(check.get("ok", False) for check in checks.values())
    return {
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "issues": issues,
    }
