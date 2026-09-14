import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.supervisor import SupervisorRunner
from core.task_store import TaskStore


class FakeBrain:
    def __init__(self, store, fail=False):
        self.store, self.fail, self.calls = store, fail, 0

    def act(self, goal, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("transient executor failure")
        self.store.update(kwargs["task_id"], status="completed", result="FINAL_SUMMARY: SUCCESS verified")
        return "FINAL_SUMMARY: SUCCESS verified"


class SupervisorRunnerTests(unittest.TestCase):
    def make(self):
        self.tmp = tempfile.TemporaryDirectory()
        return TaskStore(Path(self.tmp.name) / "tasks.json")

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_queued_task_claims_and_completes(self):
        store = self.make()
        task = store.create("work")
        brain = FakeBrain(store)
        result = SupervisorRunner(store, brain, owner="runner-a").run_once()
        self.assertEqual(result[0]["id"], task["id"])
        self.assertEqual(store.get(task["id"])["status"], "completed")

    def test_second_runner_cannot_execute_valid_lease(self):
        store = self.make()
        task = store.create("work")
        store.claim(task["id"], "runner-a")
        self.assertEqual(SupervisorRunner(store, FakeBrain(store), owner="runner-b").eligible(), [])

    def test_retry_waits_then_becomes_eligible(self):
        store = self.make()
        task = store.create("work")
        store.claim(task["id"], "runner-a")
        scheduled = store.schedule_retry(task["id"], "runner-a", "network", base_seconds=60)
        self.assertEqual(SupervisorRunner(store, owner="runner-b").eligible(), [])
        due = datetime.fromisoformat(scheduled["retry"]["next_retry_at"]) + timedelta(seconds=1)
        self.assertEqual(len(SupervisorRunner(store, owner="runner-b").eligible(due)), 1)

    def test_approval_block_and_cancel_never_execute(self):
        store = self.make()
        approval = store.create("approval")
        store.request_approval(approval["id"], {"fingerprint": "f"})
        blocked = store.create("blocked")
        store.set_recovery(blocked["id"], "BLOCKED", "blocked", status="waiting")
        cancelled = store.create("cancel")
        store.cancel(cancelled["id"])
        runner = SupervisorRunner(store, FakeBrain(store))
        self.assertEqual(runner.run_once(), [])

    def test_uncertain_mutation_verifies_before_execution(self):
        store = self.make()
        task = store.create("mutate")
        store.claim(task["id"], "old")
        step = store.begin_step(task["id"], "old", "shell", "mutation")
        store.record_failure(task["id"], "old", step["id"], "worker died",
                             category="RECOVERABLE", mutation=True)
        store.release(task["id"], "old")
        calls = []
        brain = FakeBrain(store)
        runner = SupervisorRunner(store, brain, owner="new",
                                  verifier=lambda value: calls.append(value["id"]) or True)
        runner.run_once()
        self.assertEqual(calls, [task["id"]])
        self.assertEqual(brain.calls, 1)

    def test_failed_task_isolated_from_next_task(self):
        store = self.make()
        first, second = store.create("one"), store.create("two")
        class Selective(FakeBrain):
            def act(self, goal, **kwargs):
                self.calls += 1
                if goal == "one":
                    raise RuntimeError("executor unavailable")
                return super().act(goal, **kwargs)
        brain = Selective(store)
        runner = SupervisorRunner(store, brain, owner="runner")
        runner.run_once()
        self.assertEqual(brain.calls, 3)
        self.assertEqual(store.get(second["id"])["status"], "completed")
        self.assertEqual(store.get(first["id"])["status"], "interrupted")

    def test_restart_discovers_recoverable_task(self):
        store = self.make()
        task = store.create("restart")
        store.claim(task["id"], "dead", now=datetime.now(timezone.utc) - timedelta(hours=1))
        TaskStore(store.path)
        runner = SupervisorRunner(TaskStore(store.path), FakeBrain(TaskStore(store.path)), owner="new")
        self.assertEqual(len(runner.eligible()), 1)


if __name__ == "__main__":
    unittest.main()
