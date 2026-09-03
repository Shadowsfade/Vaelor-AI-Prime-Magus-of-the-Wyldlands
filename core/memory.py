import json
import os
from datetime import datetime, timezone
from pathlib import Path
import threading
import uuid


BASE_DIR = os.path.dirname(
    os.path.dirname(__file__)
)

MEMORY_DIR = os.path.join(
    BASE_DIR,
    "memory"
)

MEMORY_FILE = os.path.join(
    MEMORY_DIR,
    "archive.json"
)


class VaelorMemory:
    """
    Persistent archive system for Vaelor.
    """

    def __init__(self, path=None):
        self.path = Path(path or MEMORY_FILE)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save([])


    def _load(self):

        try:
            with self._lock:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


    def _save(self, data):

        with self._lock:
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(data, indent=4), encoding="utf-8")
            os.replace(temp, self.path)


    def remember(
        self,
        category,
        content,
        importance=1,
        source="user_explicit",
        confidence=1.0,
        tags=None,
    ):

        archive = self._load()
        normalized = " ".join(str(content).strip().split()).casefold()


        for memory in archive:

            if (
                memory["category"] == category
                and
                " ".join(str(memory.get("content", "")).strip().split()).casefold() == normalized
            ):

                return memory


        new_memory = {

            "id": str(uuid.uuid4()),

            "timestamp":
                datetime.now(timezone.utc).isoformat(),

            "category":
                category,

            "importance":
                importance,

            "content": " ".join(str(content).strip().split()),

            "source": str(source),

            "confidence": max(0.0, min(float(confidence), 1.0)),

            "tags": [str(tag) for tag in (tags or [])][:20],
        }


        archive.append(
            new_memory
        )

        self._save(
            archive
        )


        return new_memory


    def recall(
        self,
        category=None
    ):

        archive = self._load()


        if category is None:

            return archive


        return [

            item
            for item in archive

            if item["category"] == category

        ]
