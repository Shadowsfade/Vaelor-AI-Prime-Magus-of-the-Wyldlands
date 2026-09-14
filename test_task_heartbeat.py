from pathlib import Path
import tempfile
import time
import unittest

from core.task_heartbeat import TaskHeartbeat
from core.task_store import TaskStore


class TaskHeartbeatTests(unittest.TestCase):
    def test_temporary_read_failure_does_not_kill_heartbeat(self):
        import threading
        renewed = threading.Event()
        class FlakyStore:
            reads = 0
            def get(self, task_id):
                self.reads += 1
                if self.reads == 1:
                    raise TimeoutError("temporarily locked")
                return {"status": "running"}
            def heartbeat(self, *args):
                renewed.set()
                return True
        with TaskHeartbeat(FlakyStore(), "task", interval_seconds=0.01, owner="worker"):
            self.assertTrue(renewed.wait(2), "heartbeat did not recover after read failure")

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
            store.update(task["id"], status="running")
            store.update(task["id"], status="completed")
            with TaskHeartbeat(store, task["id"], interval_seconds=0.01):
                time.sleep(0.03)
            self.assertFalse(any(e["type"] == "heartbeat" for e in store.get(task["id"])["events"]))


if __name__ == "__main__":
    unittest.main()
