from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.scheduler import ScheduleStore, SchedulerService


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args
    def start(self):
        self.target(*self.args)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ScheduleStore(Path(self.temp.name) / "schedules.json")
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def create_due(self, **kwargs):
        item = self.store.create("check", "inspect project", 300, **kwargs)
        with self.store._lock:
            values = self.store._read()
            values[0]["next_run_at"] = (self.now - timedelta(seconds=1)).isoformat()
            self.store._write(values)
        return item

    def test_create_is_durable_and_defaults_to_future_run(self):
        item = self.store.create("check", "inspect", 300)
        self.assertEqual(ScheduleStore(self.store.path).get(item["id"])["prompt"], "inspect")
        self.assertGreater(datetime.fromisoformat(item["next_run_at"]), datetime.fromisoformat(item["created_at"]))

    def test_rejects_too_frequent_schedule(self):
        with self.assertRaisesRegex(ValueError, "interval_seconds"):
            self.store.create("too fast", "inspect", 60)

    def test_corrupt_storage_fails_closed_without_overwrite(self):
        self.store.path.write_text("{broken", encoding="utf-8")
        before = self.store.path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "storage is unreadable"):
            self.store.create("check", "inspect", 300)
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), before)

    def test_claim_is_atomic_and_advances_before_launch(self):
        item = self.create_due()
        claimed = self.store.claim(item["id"], self.now)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["run_count"], 1)
        self.assertIsNone(self.store.claim(item["id"], self.now))

    def test_service_launches_due_task_through_brain(self):
        item = self.create_due()
        brain = MagicMock()
        brain.get_task.return_value = None
        brain.prepare_task.return_value = {"id": "task-1", "status": "pending"}
        service = SchedulerService(self.store, brain, thread_factory=ImmediateThread)
        self.assertEqual(service.run_due_once(self.now), ["task-1"])
        brain.prepare_task.assert_called_once_with(
            "inspect project", session_id=f"schedule:{item['id']}",
            workspace=None, max_runtime_seconds=900,
        )
        brain.run_prepared_task.assert_called_once_with("task-1", 12)
        self.assertEqual(self.store.get(item["id"])["last_task_id"], "task-1")

    def test_service_never_overlaps_active_previous_task(self):
        item = self.create_due()
        self.store.record_task(item["id"], task_id="existing")
        brain = MagicMock()
        brain.get_task.return_value = {"id": "existing", "status": "waiting"}
        service = SchedulerService(self.store, brain, thread_factory=ImmediateThread)
        self.assertEqual(service.run_due_once(self.now), [])
        brain.prepare_task.assert_not_called()
        self.assertEqual(self.store.get(item["id"])["run_count"], 0)

    def test_prepare_failure_is_recorded_after_claim(self):
        item = self.create_due()
        brain = MagicMock()
        brain.get_task.return_value = None
        brain.prepare_task.side_effect = RuntimeError("model unavailable")
        service = SchedulerService(self.store, brain, thread_factory=ImmediateThread)
        self.assertEqual(service.run_due_once(self.now), [])
        saved = self.store.get(item["id"])
        self.assertEqual(saved["run_count"], 1)
        self.assertIn("model unavailable", saved["last_error"])

    def test_pause_and_resume_resets_next_run(self):
        item = self.store.create("check", "inspect", 300)
        self.assertFalse(self.store.set_enabled(item["id"], False)["enabled"])
        resumed = self.store.set_enabled(item["id"], True)
        self.assertTrue(resumed["enabled"])
        self.assertGreater(datetime.fromisoformat(resumed["next_run_at"]), datetime.now(timezone.utc))

    def test_string_false_does_not_accidentally_enable_schedule(self):
        item = self.store.create("check", "inspect", 300, enabled="false")
        self.assertFalse(item["enabled"])
        self.assertTrue(self.store.set_enabled(item["id"], "true")["enabled"])

    def test_interrupted_previous_run_does_not_block_future_recurrence(self):
        item = self.create_due()
        self.store.record_task(item["id"], task_id="interrupted-task")
        brain = MagicMock()
        brain.get_task.return_value = {"id": "interrupted-task", "status": "interrupted"}
        brain.prepare_task.return_value = {"id": "replacement", "status": "waiting"}
        service = SchedulerService(self.store, brain, thread_factory=ImmediateThread)
        self.assertEqual(service.run_due_once(self.now), ["replacement"])
        brain.run_prepared_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
