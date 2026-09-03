from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.brain import VaelorBrain
from core.task_intent import TaskIntent
from core.task_store import TaskStore


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.brain = VaelorBrain.__new__(VaelorBrain)
        self.brain.tasks = TaskStore(Path(self.temp.name) / "tasks.json")
        self.brain.conversations = MagicMock()
        self.brain.build_system_prompt = MagicMock(return_value="system")
        self.brain._context_prefix = MagicMock(return_value="context")
        self.brain._history_text = MagicMock(return_value="")
        self.contract = TaskIntent(
            intent="act",
            goal="inspect project",
            success_criteria=["status recorded"],
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_act_records_progress_and_completion(self):
        def fake_run_agent(**kwargs):
            kwargs["event_callback"]("tool_completed", {"tool": "git_status"})
            return "FINAL_SUMMARY: SUCCESS status recorded"

        with patch("core.agent_loop.run_agent", side_effect=fake_run_agent):
            result = self.brain.act("inspect project", task_contract=self.contract)

        task = self.brain.list_tasks()[0]
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS status recorded")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["attempts"], 1)
        self.assertEqual(task["events"][-1]["type"], "tool_completed")

    def test_crash_is_persisted_before_exception_escapes(self):
        with patch("core.agent_loop.run_agent", side_effect=RuntimeError("backend lost")):
            with self.assertRaises(RuntimeError):
                self.brain.act("inspect project", task_contract=self.contract)

        task = self.brain.list_tasks()[0]
        self.assertEqual(task["status"], "failed")
        self.assertIn("backend lost", task["result"])
        self.assertEqual(task["events"][-1]["type"], "crashed")

    def test_resume_reuses_task_and_increments_attempts(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict(), "s1")
        self.brain.tasks.update(task["id"], status="interrupted")
        with patch("core.agent_loop.run_agent", return_value="FINAL_SUMMARY: SUCCESS resumed"):
            result = self.brain.resume_task(task["id"])

        resumed = self.brain.get_task(task["id"])
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS resumed")
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["attempts"], 1)
        self.assertEqual(len(self.brain.list_tasks()), 1)


if __name__ == "__main__":
    unittest.main()
