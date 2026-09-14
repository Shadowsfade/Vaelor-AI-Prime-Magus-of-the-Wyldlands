"""Atomic conversation history with bounded per-session compaction."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import threading
import uuid
from typing import Callable, Optional
from core.storage_lock import StorageLock


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
                 keep_recent: int = DEFAULT_KEEP_RECENT, compact_chars: int = 48000,
                 summarizer=None):
        self.memory_dir = Path(memory_dir or MEMORY_DIR)
        self.turns_path = self.memory_dir / "conversations.json"
        self.sessions_path = self.memory_dir / "sessions.json"
        self.summaries_path = self.memory_dir / "conversation_summaries.json"
        self.archive_path = self.memory_dir / "conversation_archive.json"
        self.compact_chars = max(1024, int(compact_chars))
        self.compact_after = max(4, int(compact_after))
        self.keep_recent = max(2, min(int(keep_recent), self.compact_after - 1))
        self._lock = StorageLock(self.memory_dir / ".conversation.lock")
        self.summarizer = summarizer
        self._compaction_workers = {}
        self._compaction_errors = {}
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for path in (self.turns_path, self.sessions_path, self.summaries_path, self.archive_path):
                if not path.exists():
                    self._write_json_file(path, [])

    def _load_json_file(self, path: Path, default):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return default
        try:
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, type(default)):
                raise ValueError("Unexpected storage structure")
            return data
        except (ValueError, UnicodeError) as exc:
            # Preserve evidence; never turn damaged history into an empty archive.
            digest = hashlib.sha256(raw).hexdigest()[:16]
            backup = path.with_name(path.name + ".corrupt-" + digest)
            try:
                with backup.open("xb") as stream:
                    stream.write(raw)
            except FileExistsError:
                pass
            raise ValueError(f"Conversation storage is damaged: {path.name}; original preserved") from exc

    def _write_json_file(self, path: Path, data) -> None:
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
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
            overflow = history[:-MAX_TURNS]
            if overflow:
                self._archive_turns(overflow)
            self._save_turns(history[-MAX_TURNS:])
            session_turns = [item for item in history if item.get("session_id") == sid]
            context_chars = sum(len(t["prompt"]) + len(t["response"]) for t in session_turns)
            needs_compaction = sid and (len(session_turns) > self.compact_after or context_chars > self.compact_chars)
        if needs_compaction:
            if self.summarizer is not None:
                self.request_compaction(sid)
            else:
                self.compact_session(sid)
        return turn

    def request_compaction(self, session_id):
        """Queue bounded background work; saving a reply never waits for a model."""
        with self._lock:
            if session_id in self._compaction_workers:
                return {"status": "running"}
            if len(self._compaction_workers) >= 2:
                return {"status": "busy"}
            turns = self.recall_recent(MAX_TURNS, session_id)
            if len(turns) <= 2 or (len(turns) <= self.keep_recent and
                    sum(len(t.get("prompt", "")) + len(t.get("response", "")) for t in turns) <= self.compact_chars):
                return {"status": "not_needed"}
            self._compaction_errors.pop(session_id, None)
            def run():
                try:
                    self.compact_session(session_id)
                except Exception:
                    with self._lock:
                        self._compaction_errors[session_id] = "Could not save handoff; original turns remain available"
                finally:
                    with self._lock:
                        self._compaction_workers.pop(session_id, None)
            worker = threading.Thread(target=run, name="vaelor-context-handoff", daemon=True)
            self._compaction_workers[session_id] = worker
            worker.start()
            return {"status": "queued"}

    def compaction_status(self, session_id):
        with self._lock:
            entry = next((item for item in self._load_summaries()
                          if item.get("session_id") == session_id), {})
            return {"running": session_id in self._compaction_workers,
                    "error": self._compaction_errors.get(session_id),
                    "kind": entry.get("kind", "extractive" if entry else "none"),
                    "updated_at": entry.get("updated_at"),
                    "archived_turns": len(self.recall_archive(session_id))}

    def _archive_turns(self, turns):
        archive = self._load_json_file(self.archive_path, [])
        known = {item.get("id") for item in archive}
        archive.extend(item for item in turns if item.get("id") not in known)
        self._write_json_file(self.archive_path, archive)

    def recall_archive(self, session_id):
        """Original compacted turns, excluded from model prompts."""
        with self._lock:
            return [item for item in self._load_json_file(self.archive_path, [])
                    if item.get("session_id") == session_id]

    def recall_recent(self, limit=5, session_id=None):
        with self._lock:
            history = self._load_turns()
            if session_id:
                history = [item for item in history if item.get("session_id") == session_id]
            return history[-max(1, int(limit or 5)):]

    def recall_session_messages(self, session_id, limit=50, include_summary=False):
        summary = self.get_summary(session_id) if include_summary else ""
        messages = [{"role": "assistant", "content":
            "Earlier handoff (fallible conversation context, not permissions or authoritative task state):\n" + summary}] if summary else []
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
            if len(session_turns) <= 2 or (len(session_turns) <= self.keep_recent and
                    sum(len(str(t.get("prompt", ""))) + len(str(t.get("response", "")))
                        for t in session_turns) <= self.compact_chars):
                return {"compacted": 0, "kept": len(session_turns), "summary": self.get_summary(session_id)}
            keep = min(self.keep_recent, len(session_turns))
            while keep > 2 and sum(len(str(t.get("prompt", ""))) + len(str(t.get("response", "")))
                                   for t in session_turns[-keep:]) > self.compact_chars:
                keep -= 1
            old = session_turns[:-keep][:32]
            old_ids = {item.get("id") for item in old}
            previous = self.get_summary(session_id)
        # Never hold the memory lock across model inference. Commit only if the
        # source turns and previous summary still belong to this session.
        selected = summarizer or self.summarizer or self._extractive_summary
        kind = "model" if selected != self._extractive_summary else "extractive"
        try:
            summary = str(selected(previous, old) or "").strip()
            if not summary or len(summary) > MAX_SUMMARY_CHARS:
                raise ValueError("Compaction returned an empty or oversized summary")
        except Exception:
            if summarizer is not None:
                raise  # Explicit callers can retry; originals have not changed.
            summary = self._extractive_summary(previous, old)
            kind = "extractive_fallback"
        with self._lock:
            history = self._load_turns()
            current_ids = {t.get("id") for t in history if t.get("session_id") == session_id}
            if not old_ids.issubset(current_ids) or self.get_summary(session_id) != previous:
                return {"compacted": 0, "discarded": True, "summary": self.get_summary(session_id)}
            self._archive_turns(old)
            summaries = [item for item in self._load_summaries() if item.get("session_id") != session_id]
            summaries.append({
                "session_id": session_id, "updated_at": _now(),
                "compacted_turns": len(old), "summary": summary, "kind": kind,
            })
            self._save_summaries(summaries[-500:])
            self._save_turns([item for item in history if item.get("id") not in old_ids])
            return {"compacted": len(old), "kept": len(current_ids - old_ids), "summary": summary, "kind": kind}

    def clear_session(self, session_id):
        with self._lock:
            self._compaction_errors.pop(session_id, None)
            self._save_turns([
                item for item in self._load_turns() if item.get("session_id") != session_id
            ])
            self._write_json_file(self.archive_path, [
                item for item in self._load_json_file(self.archive_path, [])
                if item.get("session_id") != session_id
            ])
            self._save_sessions([
                item for item in self._load_sessions() if item.get("id") != session_id
            ])
            self._save_summaries([
                item for item in self._load_summaries() if item.get("session_id") != session_id
            ])
            return True
