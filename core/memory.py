import json
import os
from datetime import datetime
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

    def __init__(self):

        os.makedirs(
            MEMORY_DIR,
            exist_ok=True
        )

        if not os.path.exists(MEMORY_FILE):

            self._save([])


    def _load(self):

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)


    def _save(self, data):

        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4
            )


    def remember(
        self,
        category,
        content,
        importance=1
    ):

        archive = self._load()


        for memory in archive:

            if (
                memory["category"] == category
                and
                memory["content"] == content
            ):

                return memory


        new_memory = {

            "id": str(uuid.uuid4()),

            "timestamp":
                datetime.now().isoformat(),

            "category":
                category,

            "importance":
                importance,

            "content":
                content
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