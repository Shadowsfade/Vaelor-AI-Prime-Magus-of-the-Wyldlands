import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.brain import VaelorBrain
from core.task_store import TaskStore
from core.software_workflow import run_software_workflow
from test_software_workflow import FakePlatformAdapter


class SoftwareApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "tasks.json")
        self.task = self.store.claim(self.store.create("Install fake tool")["id"], "owner")
        self.adapter = FakePlatformAdapter(self.temp.name)

    def run_workflow(self):
        return run_software_workflow(self.task, self.store, self.adapter, owner="owner")

    def approve_and_claim(self):
        pending = self.store.get(self.task["id"])["pending_approval"]
        self.store.approve_action(self.task["id"], pending["fingerprint"])
        self.task = self.store.claim(self.task["id"], "owner")
        return pending["fingerprint"]

    def test_approve_once_executes_and_consumes_exact_saved_plan(self):
        self.assertIn("WAITING_APPROVAL", self.run_workflow())
        self.assertEqual(self.store.get(self.task["id"])["waiting_reason"], "approval")
        # Approval cards and their exact operation survive a process restart.
        self.store = TaskStore(self.store.path)
        fingerprint = self.approve_and_claim()
        self.assertIn("SUCCESS", self.run_workflow())
        self.assertFalse(self.store.consume_action_approval(self.task["id"], fingerprint))
        self.assertEqual(len([s for s in self.store.get(self.task["id"])["steps"] if s["action_category"] == "install"]), 1)

    def test_changed_source_requires_fresh_approval(self):
        self.run_workflow()
        previous = self.approve_and_claim()
        workflow = self.task["workflow"]
        workflow["source"]["package"] = "different-package"
        self.store.update_workflow(self.task["id"], workflow)
        self.adapter.execute_install = Mock(side_effect=AssertionError("stale approval"))
        self.assertIn("WAITING_APPROVAL", self.run_workflow())
        pending = self.store.get(self.task["id"])["pending_approval"]
        self.assertNotEqual(pending["fingerprint"], previous)
        self.adapter.execute_install.assert_not_called()

    def test_sudo_wait_preserves_approval_until_credentials_available(self):
        self.run_workflow()
        fingerprint = self.approve_and_claim()
        self.adapter.preflight = Mock(return_value="Authenticate on the host, then recheck.")
        self.assertIn("WAITING_USER", self.run_workflow())
        saved = self.store.get(self.task["id"])
        self.assertEqual(saved["waiting_reason"], "privilege")
        self.assertEqual(saved["authorized_action"], fingerprint)
        brain = object.__new__(VaelorBrain)
        brain.tasks = self.store
        brain.continue_software_task(self.task["id"])
        self.task = self.store.claim(self.task["id"], "owner")
        self.adapter.preflight.return_value = ""
        self.assertIn("SUCCESS", self.run_workflow())

    def test_continue_cannot_bypass_approval(self):
        self.run_workflow()
        brain = object.__new__(VaelorBrain)
        brain.tasks = self.store
        with self.assertRaises(ValueError):
            brain.continue_software_task(self.task["id"])

    def test_policy_denial_cannot_be_overridden_by_saved_approval(self):
        from core.approval_policy import ActionAssessment, ActionClass, ApprovalDecision, RiskTier
        self.run_workflow()
        self.approve_and_claim()
        policy = Mock()
        policy.evaluate.return_value = ActionAssessment(ActionClass.SYSTEM_CONFIGURATION,
            RiskTier.HIGH, ApprovalDecision.DENY, "Denied by policy")
        self.adapter.execute_install = Mock(side_effect=AssertionError("must not install"))
        result = run_software_workflow(self.task, self.store, self.adapter, policy, "owner")
        self.assertIn("BLOCKED", result)
        self.adapter.execute_install.assert_not_called()

    def test_api_recheck_rejects_ineligible_task(self):
        import api.server as server
        from conftest import SynchronousASGIClient
        brain = Mock()
        brain.continue_software_task.side_effect = ValueError("Not waiting for host authentication")
        with patch.object(server, "brain", brain):
            client = SynchronousASGIClient(server.app)
            try:
                response = client.post("/tasks/other/continue-software", json={"max_steps": 12})
            finally:
                client.close()
        self.assertEqual(response.status_code, 409)
        brain.run_prepared_task.assert_not_called()

    def test_api_recheck_queues_same_task(self):
        import api.server as server
        from conftest import SynchronousASGIClient
        brain = Mock()
        brain.continue_software_task.return_value = {"id": self.task["id"], "status": "pending"}
        with patch.object(server, "brain", brain):
            client = SynchronousASGIClient(server.app)
            try:
                response = client.post(f"/tasks/{self.task['id']}/continue-software", json={"max_steps": 12})
            finally:
                client.close()
        self.assertEqual(response.status_code, 200)
        brain.run_prepared_task.assert_called_once_with(self.task["id"], 12)
