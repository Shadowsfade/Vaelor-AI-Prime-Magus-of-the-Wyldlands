"""User-controlled preferences and provenance-aware outcome feedback."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid
from typing import Optional


EXPLICIT_PATTERNS = [
    re.compile(r"\b(?:i prefer|my preference is|remember that i prefer)\s+(.{3,240})", re.I),
]


def _now():
    return datetime.now(timezone.utc).isoformat()


class PreferenceStore:
    def __init__(self, path: Optional[Path] = None):
        root = Path(__file__).resolve().parent.parent
        self.path = Path(path or root / "memory" / "preferences.json")
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"preferences": [], "feedback": []})

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                data.setdefault("preferences", [])
                data.setdefault("feedback", [])
                return data
        except Exception:
            pass
        return {"preferences": [], "feedback": []}

    def _write(self, data):
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def add(self, statement, scope="global", source="user_explicit", confidence=1.0, status="active"):
        clean = " ".join(str(statement).strip().split())[:500]
        if not clean:
            raise ValueError("Preference statement cannot be empty")
        if status not in {"active", "proposed", "disabled"}:
            raise ValueError("Invalid preference status")
        key = clean.casefold()
        with self._lock:
            data = self._read()
            for item in data["preferences"]:
                if item.get("statement", "").casefold() == key and item.get("scope") == scope:
                    item["evidence_count"] = int(item.get("evidence_count", 1)) + 1
                    item["updated_at"] = _now()
                    if source == "user_explicit":
                        item["status"] = "active"
                        item["confidence"] = 1.0
                    self._write(data)
                    return item.copy()
            stamp = _now()
            item = {
                "id": str(uuid.uuid4())[:12],
                "statement": clean,
                "scope": str(scope or "global")[:120],
                "source": str(source)[:80],
                "confidence": max(0.0, min(float(confidence), 1.0)),
                "status": status,
                "evidence_count": 1,
                "created_at": stamp,
                "updated_at": stamp,
            }
            data["preferences"].append(item)
            self._write(data)
            return item.copy()

    def learn_explicit(self, message):
        learned = []
        for pattern in EXPLICIT_PATTERNS:
            match = pattern.search(message or "")
            if match:
                statement = match.group(1).strip().rstrip(".!?")
                learned.append(self.add(statement, source="user_explicit", confidence=1.0))
        return learned

    def list(self, status=None):
        with self._lock:
            items = self._read()["preferences"]
            if status:
                items = [item for item in items if item.get("status") == status]
            return [item.copy() for item in items]

    def set_status(self, preference_id, status):
        if status not in {"active", "proposed", "disabled"}:
            raise ValueError("Invalid preference status")
        with self._lock:
            data = self._read()
            for item in data["preferences"]:
                if item.get("id") == preference_id:
                    item["status"] = status
                    item["updated_at"] = _now()
                    self._write(data)
                    return item.copy()
        raise KeyError(f"Unknown preference: {preference_id}")

    def context(self, scope="global", limit=12):
        active = [
            item for item in self.list("active")
            if item.get("scope") in {"global", scope}
        ][-max(1, min(int(limit or 12), 30)):]
        if not active:
            return ""
        return "User-confirmed preferences:\n" + "\n".join(
            f"- {item['statement']}" for item in active
        )

    def record_feedback(self, task_id, rating, comment=""):
        normalized = str(rating).lower().strip()
        if normalized not in {"positive", "negative"}:
            raise ValueError("Rating must be positive or negative")
        with self._lock:
            data = self._read()
            entry = {
                "id": str(uuid.uuid4())[:12],
                "task_id": str(task_id),
                "rating": normalized,
                "comment": str(comment).strip()[:2000],
                "timestamp": _now(),
            }
            data["feedback"].append(entry)
            data["feedback"] = data["feedback"][-1000:]
            self._write(data)
        # Negative feedback is evidence to review, not permission to rewrite behavior.
        if normalized == "negative" and entry["comment"]:
            self.add(
                entry["comment"],
                scope="global",
                source=f"task_feedback:{task_id}",
                confidence=0.5,
                status="proposed",
            )
        return entry
