"""Atomic conversation history with bounded per-session compaction."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid
from typing import Callable, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
DEFAULT_COMPACT_AFTER = 40
DEFAULT_KEEP_RECENT = 20
MAX_SUMMARY_CHARS = 12000
MAX_TURNS = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VaelorConversationMemory:
    def __init__(self, memory_dir: Optional[Path] = None, compact_after: int = DEFAULT_COMPACT_AFTER,
                 keep_recent: int = DEFAULT_KEEP_RECENT):
        self.memory_dir = Path(memory_dir or MEMORY_DIR)
        self.turns_path = self.memory_dir / "conversations.json"
        self.sessions_path = self.memory_dir / "sessions.json"
        self.summaries_path = self.memory_dir / "conversation_summaries.json"
        self.compact_after = max(4, int(compact_after))
        self.keep_recent = max(2, min(int(keep_recent), self.compact_after - 1))
        self._lock = threading.RLock()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.turns_path, self.sessions_path, self.summaries_path):
            if not path.exists():
                self._write_json_file(path, [])

    def _load_json_file(self, path: Path, default):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    def _write_json_file(self, path: Path, data) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _load_turns(self):
        return self._load_json_file(self.turns_path, [])

    def _save_turns(self, data):
        self._write_json_file(self.turns_path, data)

    def _load_sessions(self):
        return self._load_json_file(self.sessions_path, [])

    def _save_sessions(self, data):
        self._write_json_file(self.sessions_path, data)

    def _load_summaries(self):
        return self._load_json_file(self.summaries_path, [])

    def _save_summaries(self, data):
        self._write_json_file(self.summaries_path, data)

    def ensure_session(self, session_id=None, title=None):
        with self._lock:
            sessions = self._load_sessions()
            if session_id:
                for session in sessions:
                    if session.get("id") == session_id:
                        return session
            stamp = _now()
            session = {
                "id": session_id or str(uuid.uuid4())[:12],
                "title": title or "Archive Dialogue",
                "created_at": stamp,
                "updated_at": stamp,
            }
            sessions.append(session)
            self._save_sessions(sessions)
            return session

    def list_sessions(self, limit=30):
        with self._lock:
            sessions = sorted(
                self._load_sessions(), key=lambda item: item.get("updated_at", ""), reverse=True
            )
            return sessions[:max(1, min(int(limit or 30), 200))]

    def remember_turn(self, prompt, response, session_id=None):
        with self._lock:
            history = self._load_turns()
            sid = None
            if session_id:
                session = self.ensure_session(session_id)
                sid = session["id"]
                sessions = self._load_sessions()
                for item in sessions:
                    if item.get("id") != sid:
                        continue
                    if item.get("title") in (None, "Archive Dialogue") and prompt:
                        item["title"] = (str(prompt)[:48] + "...") if len(str(prompt)) > 48 else str(prompt)
                    item["updated_at"] = _now()
                self._save_sessions(sessions)
            turn = {
                "id": str(uuid.uuid4()), "timestamp": _now(), "session_id": sid,
                "prompt": str(prompt), "response": str(response),
            }
            history.append(turn)
            self._save_turns(history[-MAX_TURNS:])
            if sid and sum(1 for item in history if item.get("session_id") == sid) > self.compact_after:
                self.compact_session(sid)
            return turn

    def recall_recent(self, limit=5, session_id=None):
        with self._lock:
            history = self._load_turns()
            if session_id:
                history = [item for item in history if item.get("session_id") == session_id]
            return history[-max(1, int(limit or 5)):]

    def recall_session_messages(self, session_id, limit=50):
        messages = []
        for turn in self.recall_recent(limit=limit, session_id=session_id):
            messages.append({"role": "user", "content": turn.get("prompt", "")})
            messages.append({"role": "assistant", "content": turn.get("response", "")})
        return messages

    def get_summary(self, session_id) -> str:
        with self._lock:
            entry = next(
                (item for item in self._load_summaries() if item.get("session_id") == session_id),
                None,
            )
            return str((entry or {}).get("summary", ""))

    @staticmethod
    def _extractive_summary(previous: str, turns: list) -> str:
        lines = [previous.strip()] if previous.strip() else []
        for turn in turns:
            prompt = " ".join(str(turn.get("prompt", "")).split())[:500]
            response = " ".join(str(turn.get("response", "")).split())[:700]
            lines.append(f"- User: {prompt}\n  Vaelor: {response}")
        text = "\n".join(line for line in lines if line)
        return text[-MAX_SUMMARY_CHARS:]

    def compact_session(self, session_id: str,
                        summarizer: Optional[Callable[[str, list], str]] = None) -> dict:
        """Archive older turns into one bounded summary while preserving recent context."""
        with self._lock:
            history = self._load_turns()
            session_turns = [item for item in history if item.get("session_id") == session_id]
            if len(session_turns) <= self.keep_recent:
                return {"compacted": 0, "kept": len(session_turns), "summary": self.get_summary(session_id)}
            old = session_turns[:-self.keep_recent]
            old_ids = {item.get("id") for item in old}
            previous = self.get_summary(session_id)
            summary = (summarizer or self._extractive_summary)(previous, old)
            summary = str(summary or "")[-MAX_SUMMARY_CHARS:]
            summaries = [item for item in self._load_summaries() if item.get("session_id") != session_id]
            summaries.append({
                "session_id": session_id, "updated_at": _now(),
                "compacted_turns": len(old), "summary": summary,
            })
            self._save_summaries(summaries[-500:])
            self._save_turns([item for item in history if item.get("id") not in old_ids])
            return {"compacted": len(old), "kept": self.keep_recent, "summary": summary}

    def clear_session(self, session_id):
        with self._lock:
            self._save_turns([
                item for item in self._load_turns() if item.get("session_id") != session_id
            ])
            self._save_sessions([
                item for item in self._load_sessions() if item.get("id") != session_id
            ])
            self._save_summaries([
                item for item in self._load_summaries() if item.get("session_id") != session_id
            ])
            return True
