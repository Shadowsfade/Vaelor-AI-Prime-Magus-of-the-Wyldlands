import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.approval_policy import ActionContext, ApprovalPolicy, AutoApproveMode
from core.scheduler import SchedulerService
from core.supervisor import SupervisorRunner
from core.task_store import TaskStore


class RuntimeStatusTests(unittest.TestCase):
    def test_task_aggregates_include_waiting_blocked_retry_and_recent_event(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            waiting = store.create("approval")
            waiting = store.request_approval(waiting["id"], {"fingerprint": "fp"})
            blocked = store.create("blocked")
            blocked = store.set_recovery(blocked["id"], "BLOCKED", "needs input", status="waiting")
            retry = store.create("retry")
            retry["retry"] = {"retryable": True, "next_retry_at": "2099-01-01T00:00:00+00:00"}
            Path(store.path).write_text(json.dumps([waiting, blocked, retry]), encoding="utf-8")
            counts = store.aggregate_counts()
            self.assertEqual(counts["waiting_approval"], 1)
            self.assertEqual(counts["blocked"], 1)
            self.assertEqual(counts["retry_scheduled"], 1)
            self.assertIsNotNone(store.recent_event())

    def test_supervisor_health_starts_cycles_and_stops(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            runner = SupervisorRunner(store, brain=None, backoff_base_seconds=0)
            runner.start(0.05)
            time.sleep(0.15)
            status = runner.status()
            self.assertTrue(status["running"])
            self.assertTrue(status["thread_alive"])
            self.assertIsNotNone(status["started_at"])
            self.assertIsNotNone(status["last_cycle_at"])
            self.assertIsNotNone(status["last_successful_cycle_at"])
            runner.stop()
            self.assertFalse(runner.status()["running"])

    def test_supervisor_error_is_visible_without_crashing_loop(self):
        class BrokenStore:
            def list(self, limit=200):
                raise RuntimeError("task store unavailable")
        runner = SupervisorRunner(BrokenStore(), brain=None)
        runner.run_once = lambda now=None: (_ for _ in ()).throw(RuntimeError("cycle exploded"))
        self.assertEqual(runner._cycle(), [])
        status = runner.status()
        self.assertIn("cycle exploded", status["last_error_summary"])
        self.assertEqual(status["last_event"]["type"], "supervisor_error")

    def test_scheduler_status_is_structured(self):
        service = SchedulerService(object(), object(), poll_seconds=1)
        self.assertFalse(service.status()["running"])

    def test_approval_status_records_last_decision_without_model(self):
        policy = ApprovalPolicy(AutoApproveMode.SAFE)
        with patch("core.approval_policy.classify_action", wraps=__import__("core.approval_policy", fromlist=["classify_action"]).classify_action) as classifier:
            policy.evaluate(ActionContext("git_status", {}))
            classifier.assert_called_once()
        decision = policy.status()["last_decision"]
        self.assertEqual(decision["decision"], "AUTO_APPROVE")
        self.assertEqual(decision["action_class"], "GIT_READ")
        self.assertEqual(policy.status()["mode"], "SAFE")

    def test_runtime_status_endpoint_is_local_and_machine_readable(self):
        import api.server as server
        with patch.object(server.brain, "get_auto_approve_status", return_value={"mode": "SAFE"}),              patch.object(server.supervisor_runner, "status", return_value={"running": True}),              patch.object(server.scheduler_service, "status", return_value={"running": True}):
            payload = server.runtime_status()
        self.assertEqual(payload["server"]["status"], "ok")
        self.assertTrue(payload["supervisor"]["running"])
        self.assertEqual(payload["governance"]["mode"], "SAFE")
        self.assertIn("pending", payload["tasks"])

    def test_runtime_status_degrades_when_task_store_is_unreadable(self):
        import api.server as server
        with patch.object(server.brain.tasks, "aggregate_counts", side_effect=RuntimeError("store offline")):
            payload = server.runtime_status()
        self.assertEqual(payload["tasks"]["status"], "degraded")
        self.assertIn("store offline", payload["tasks"]["error"])

if __name__ == "__main__":
    unittest.main()
