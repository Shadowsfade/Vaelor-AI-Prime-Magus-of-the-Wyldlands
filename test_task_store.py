import json
from pathlib import Path
import tempfile
import unittest

from core.task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.json"
        self.store = TaskStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_task_lifecycle_and_events(self):
        task = self.store.create("fix startup", {"goal": "repair startup"}, "s1")
        self.store.update(task["id"], status="running")
        self.store.add_event(task["id"], "tool_completed", {"tool": "git_status"})
        self.store.update(task["id"], status="completed", result="SUCCESS")

        reopened = TaskStore(self.path).get(task["id"])
        self.assertEqual(reopened["status"], "completed")
        self.assertEqual(reopened["attempts"], 1)
        self.assertEqual(reopened["events"][0]["type"], "tool_completed")
        self.assertEqual(reopened["result"], "SUCCESS")

    def test_running_tasks_become_interrupted_after_restart(self):
        task = self.store.create("long task")
        self.store.update(task["id"], status="running")
        reopened = TaskStore(self.path).get(task["id"])
        self.assertEqual(reopened["status"], "interrupted")
        self.assertEqual(reopened["events"][-1]["type"], "interrupted")

    def test_writes_valid_json_atomically(self):
        self.store.create("task")
        self.assertIsInstance(json.loads(self.path.read_text(encoding="utf-8")), list)
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())

    def test_rejects_invalid_status(self):
        task = self.store.create("task")
        with self.assertRaises(ValueError):
            self.store.update(task["id"], status="imaginary")


if __name__ == "__main__":
    unittest.main()
