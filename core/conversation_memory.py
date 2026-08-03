import json
import os
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
CONVERSATION_FILE = os.path.join(MEMORY_DIR, "conversations.json")
SESSIONS_FILE = os.path.join(MEMORY_DIR, "sessions.json")


class VaelorConversationMemory:
    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        if not os.path.exists(CONVERSATION_FILE):
            self._save_turns([])
        if not os.path.exists(SESSIONS_FILE):
            self._save_sessions([])

    def _load_json_file(self, path, default):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = f.read().strip()
            if not raw:
                return default
            data = json.loads(raw)
            # conversations must be a list of turns
            if path.endswith("conversations.json") and isinstance(data, dict):
                return default
            return data
        except Exception:
            try:
                self._write_json_file(path, default)
            except Exception:
                pass
            return default

    def _write_json_file(self, path, data):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=4)

    def _load_turns(self):
        data = self._load_json_file(CONVERSATION_FILE, [])
        return data if isinstance(data, list) else []

    def _save_turns(self, data):
        self._write_json_file(CONVERSATION_FILE, data)

    def _load_sessions(self):
        data = self._load_json_file(SESSIONS_FILE, [])
        return data if isinstance(data, list) else []

    def _save_sessions(self, data):
        self._write_json_file(SESSIONS_FILE, data)

    def ensure_session(self, session_id=None, title=None):
        sessions = self._load_sessions()
        if session_id:
            for s in sessions:
                if s.get("id") == session_id:
                    return s
        new_id = session_id or str(uuid.uuid4())[:12]
        session = {
            "id": new_id,
            "title": title or "Archive Dialogue",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        sessions.append(session)
        self._save_sessions(sessions)
        return session

    def list_sessions(self, limit=30):
        sessions = sorted(
            self._load_sessions(),
            key=lambda s: s.get("updated_at", ""),
            reverse=True,
        )
        return sessions[:limit]

    def remember_turn(self, prompt, response, session_id=None):
        history = self._load_turns()
        sid = None
        if session_id:
            session = self.ensure_session(session_id)
            sid = session["id"]
            if session.get("title") in (None, "Archive Dialogue") and prompt:
                session["title"] = (prompt[:48] + "...") if len(prompt) > 48 else prompt
                session["updated_at"] = datetime.now().isoformat()
                sessions = self._load_sessions()
                for i, s in enumerate(sessions):
                    if s.get("id") == sid:
                        sessions[i] = session
                self._save_sessions(sessions)
        turn = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "session_id": sid,
            "prompt": prompt,
            "response": response,
        }
        history.append(turn)
        if len(history) > 2000:
            history = history[-2000:]
        self._save_turns(history)
        return turn

    def recall_recent(self, limit=5, session_id=None):
        history = self._load_turns()
        if session_id:
            history = [t for t in history if t.get("session_id") == session_id]
        return history[-limit:]

    def recall_session_messages(self, session_id, limit=50):
        turns = self.recall_recent(limit=limit, session_id=session_id)
        messages = []
        for t in turns:
            messages.append({"role": "user", "content": t.get("prompt", "")})
            messages.append({"role": "assistant", "content": t.get("response", "")})
        return messages

    def clear_session(self, session_id):
        history = [t for t in self._load_turns() if t.get("session_id") != session_id]
        self._save_turns(history)
        sessions = [s for s in self._load_sessions() if s.get("id") != session_id]
        self._save_sessions(sessions)
        return True
