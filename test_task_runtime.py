import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.task_store import TaskStore


class DurableRuntimeTests(unittest.TestCase):
    def make_store(self):
        self.temp = tempfile.TemporaryDirectory()
        return TaskStore(Path(self.temp.name) / "tasks.json")

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_exclusive_claim_and_stale_reclaim(self):
        store = self.make_store()
        task = store.create("work")
        now = datetime.now(timezone.utc)
        self.assertIsNotNone(store.claim(task["id"], "worker-a", lease_seconds=10, now=now))
        self.assertIsNone(store.claim(task["id"], "worker-b", lease_seconds=10, now=now))
        reclaimed = store.claim(task["id"], "worker-b", lease_seconds=10,
                                now=now + timedelta(seconds=11))
        self.assertEqual(reclaimed["lease"]["owner"], "worker-b")

    def test_heartbeat_extends_lease_and_finished_task_cannot_claim(self):
        store = self.make_store()
        task = store.create("work")
        now = datetime.now(timezone.utc)
        store.claim(task["id"], "worker-a", lease_seconds=10, now=now)
        self.assertTrue(store.heartbeat(task["id"], "worker-a", lease_seconds=30,
                                         now=now + timedelta(seconds=5)))
        lease = store.get(task["id"])["lease"]
        self.assertGreater(datetime.fromisoformat(lease["lease_expires_at"]),
                           now + timedelta(seconds=30))
        store.update(task["id"], status="completed", result="done")
        store.release(task["id"], "worker-a")
        self.assertIsNone(store.claim(task["id"], "worker-b"))

    def test_step_record_survives_reload_and_failure_is_bounded(self):
        store = self.make_store()
        task = store.create("work")
        store.claim(task["id"], "worker-a")
        step = store.begin_step(task["id"], "worker-a", "powershell", "read", retry_limit=2)
        failure = store.record_failure(task["id"], "worker-a", step["id"],
                                       "temporary network timeout", mutation=False)
        self.assertEqual(failure["category"], "TRANSIENT")
        self.assertTrue(failure["retryable"])
        reloaded = TaskStore(store.path)
        saved = reloaded.get(task["id"])
        self.assertEqual(saved["steps"][0]["state"], "failed")
        self.assertEqual(saved["recovery"]["decision"], "RETRY_SAFE")

    def test_terminal_and_approval_failures_do_not_retry(self):
        store = self.make_store()
        task = store.create("work")
        store.claim(task["id"], "worker-a")
        step = store.begin_step(task["id"], "worker-a", "shell", "read", retry_limit=2)
        failure = store.record_failure(task["id"], "worker-a", step["id"],
                                       "invalid configuration", category="TERMINAL")
        self.assertFalse(failure["retryable"])
        self.assertEqual(store.get(task["id"])["status"], "failed")

        task2 = store.create("approval work")
        store.request_approval(task2["id"], {"fingerprint": "f"})
        self.assertIsNone(store.claim(task2["id"], "worker-a"))

    def test_uncertain_mutation_requires_verification_before_retry(self):
        store = self.make_store()
        task = store.create("mutate")
        store.claim(task["id"], "worker-a")
        step = store.begin_step(task["id"], "worker-a", "shell", "mutation")
        failure = store.record_failure(task["id"], "worker-a", step["id"],
                                       "worker died", category="RECOVERABLE", mutation=True)
        self.assertFalse(failure["retryable"])
        self.assertEqual(store.get(task["id"])["recovery"]["decision"],
                         "VERIFY_BEFORE_RETRY")
        reloaded = TaskStore(store.path)
        self.assertEqual(reloaded.get(task["id"])["recovery"]["decision"],
                         "VERIFY_BEFORE_RETRY")
        self.assertIsNone(reloaded.claim(task["id"], "worker-b"))

    def test_restart_recovery_records_safe_decision(self):
        store = self.make_store()
        task = store.create("inspect")
        store.claim(task["id"], "worker-a", now=datetime.now(timezone.utc) - timedelta(hours=1))
        TaskStore(store.path)
        recovered = TaskStore(store.path).get(task["id"])
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["recovery"]["decision"], "RESUME_SAFE")
        self.assertIsNotNone(TaskStore(store.path).claim(task["id"], "worker-b"))

if __name__ == "__main__":
    unittest.main()
