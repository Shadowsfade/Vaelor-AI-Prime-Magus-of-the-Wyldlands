from pathlib import Path
import tempfile
import time
import unittest

from core.task_heartbeat import TaskHeartbeat
from core.task_store import TaskStore


class TaskHeartbeatTests(unittest.TestCase):
    def test_emits_only_while_task_is_running_and_stops_on_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp) / "tasks.json")
            task = store.create("work")
            store.update(task["id"], status="running")
            with TaskHeartbeat(store, task["id"], interval_seconds=0.01):
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    if any(e["type"] == "heartbeat" for e in store.get(task["id"])["events"]):
                        break
                    time.sleep(0.01)
            count = len(store.get(task["id"])["events"])
            time.sleep(0.03)
            self.assertEqual(len(store.get(task["id"])["events"]), count)
            heartbeat = next(e for e in store.get(task["id"])["events"] if e["type"] == "heartbeat")
            self.assertIn("still working", heartbeat["data"]["message"])

    def test_terminal_task_state_stops_heartbeat_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp) / "tasks.json")
            task = store.create("work")
            store.update(task["id"], status="completed")
            with TaskHeartbeat(store, task["id"], interval_seconds=0.01):
                time.sleep(0.03)
            self.assertFalse(any(e["type"] == "heartbeat" for e in store.get(task["id"])["events"]))


if __name__ == "__main__":
    unittest.main()
