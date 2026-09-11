import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.approval_policy import ApprovalPolicy, AutoApproveMode
from core.brain import VaelorBrain
from core.cachyos_workflow import run_cachyos_workflow
from core.task_store import TaskStore


class CachyOSWorkflowTests(unittest.TestCase):
    def _task(self, store, request):
        task = store.create(request)
        return store.claim(task["id"], "test-owner")

    def test_real_workflow_persists_artifacts_commands_and_verification(self):
        request = "Download jq, open it, and tell me how to use it on CachyOS."
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = self._task(store, request)
            policy = ApprovalPolicy(AutoApproveMode.TRUSTED_WORKSPACE)
            with patch("core.cachyos_workflow.detect_environment", return_value={
                "os": "CachyOS", "distribution": "cachyos", "architecture": "x86_64",
                "shell": "/bin/bash", "package_managers": ["pacman"], "user": "test", "home": root,
            }), patch("core.cachyos_workflow.urllib.request.urlretrieve", side_effect=lambda url, target: Path(target).write_bytes(b"binary")),                  patch("core.cachyos_workflow._run", side_effect=[(0, "jq-1.8.1"), (0, "help")]):
                result = run_cachyos_workflow(task, store, policy, "test-owner")
            saved = store.get(task["id"])
            self.assertTrue(result.startswith("FINAL_SUMMARY: SUCCESS"))
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["workflow"]["current_step"], "completed")
            self.assertEqual(len(saved["artifacts"]), 1)
            self.assertEqual(len(saved["commands"]), 2)
            self.assertEqual(saved["verification"][0]["status"], "passed")
            self.assertIn("task_succeeded", [e["type"] for e in saved["events"]])

    def test_off_policy_stops_before_workspace_write(self):
        request = "Download jq and set it up on CachyOS."
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = self._task(store, request)
            with patch("core.cachyos_workflow.detect_environment", return_value={"distribution": "cachyos"}):
                result = run_cachyos_workflow(task, store, ApprovalPolicy(AutoApproveMode.OFF), "test-owner")
            saved = store.get(task["id"])
            self.assertTrue(result.startswith("FINAL_SUMMARY: WAITING_APPROVAL"))
            self.assertEqual(saved["status"], "waiting")
            self.assertEqual(saved["recovery"]["decision"], "WAIT_FOR_APPROVAL")

    def test_brain_prepare_uses_deterministic_contract_for_workflow(self):
        with tempfile.TemporaryDirectory() as root:
            brain = object.__new__(VaelorBrain)
            brain.tasks = TaskStore(Path(root) / "tasks.json")
            request = "Download jq, open it, and tell me how to use it on CachyOS."
            with patch.object(brain, "understand_task", side_effect=AssertionError("model should not classify routine workflow")):
                task = brain.prepare_task(request)
            self.assertEqual(task["contract"]["source"], "deterministic_cachyos_workflow")
            self.assertEqual(task["status"], "pending")


if __name__ == "__main__":
    unittest.main()
