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

    def test_prepare_task_persists_contract_before_execution(self):
        contract = TaskIntent(
            intent="act",
            goal="build index",
            success_criteria=["index exists"],
        )
        self.brain.understand_task = MagicMock(return_value=contract)
        task = self.brain.prepare_task("build the index", "s2")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["contract"]["goal"], "build index")
        self.assertEqual(task["session_id"], "s2")

    def test_prepare_task_persists_validated_workspace(self):
        self.brain.understand_task = MagicMock(return_value=self.contract)
        with patch("core.brain.resolve_workspace") as resolve:
            task = self.brain.prepare_task("inspect project", "s2", "C:/demo")
        resolve.assert_called_once_with("C:/demo")
        self.assertEqual(task["workspace"], "C:/demo")

    def test_prepare_task_records_clarification_wait(self):
        contract = TaskIntent(
            intent="act",
            goal="delete project",
            needs_clarification=True,
            clarification_question="Which project?",
        )
        self.brain.understand_task = MagicMock(return_value=contract)
        task = self.brain.prepare_task("delete it")
        self.assertEqual(task["status"], "waiting")
        self.assertEqual(task["result"], "Which project?")
        self.assertEqual(task["events"][-1]["type"], "clarification_required")

    def test_run_prepared_task_uses_existing_id(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict())
        with patch("core.agent_loop.run_agent", return_value="FINAL_SUMMARY: SUCCESS done"):
            self.brain.run_prepared_task(task["id"])
        self.assertEqual(len(self.brain.list_tasks()), 1)
        self.assertEqual(self.brain.get_task(task["id"])["status"], "completed")

    def test_workspace_context_is_injected_into_agent_session(self):
        task = self.brain.tasks.create(
            "inspect project", self.contract.to_dict(), workspace="C:/demo"
        )

        def fake_run_agent(**kwargs):
            self.assertIn("PROJECT SNAPSHOT", kwargs["session_context"])
            return "FINAL_SUMMARY: SUCCESS grounded"

        with (
            patch("core.brain.build_project_context", return_value="PROJECT SNAPSHOT\n"),
            patch("core.agent_loop.run_agent", side_effect=fake_run_agent),
        ):
            self.brain.run_prepared_task(task["id"])

    def test_cancel_is_durable_and_idempotent(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict())
        cancelled = self.brain.cancel_task(task["id"], "No longer needed.")
        again = self.brain.cancel_task(task["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(again["status"], "cancelled")
        self.assertEqual(len(again["events"]), 1)
        self.assertEqual(again["events"][0]["type"], "cancelled")

    def test_agent_result_cannot_overwrite_cancelled_state(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict())

        def fake_run_agent(**kwargs):
            self.brain.cancel_task(task["id"])
            return "FINAL_SUMMARY: CANCELLED Task cancellation was requested."

        with patch("core.agent_loop.run_agent", side_effect=fake_run_agent):
            self.brain.run_prepared_task(task["id"])
        saved = self.brain.get_task(task["id"])
        self.assertEqual(saved["status"], "cancelled")
        self.assertTrue(saved["result"].startswith("FINAL_SUMMARY: CANCELLED"))

    def test_cancelled_task_is_not_resumed(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict())
        self.brain.cancel_task(task["id"])
        with patch("core.agent_loop.run_agent") as run_agent_mock:
            self.brain.resume_task(task["id"])
        run_agent_mock.assert_not_called()

    def test_crash_after_cancel_does_not_overwrite_cancelled_state(self):
        task = self.brain.tasks.create("inspect project", self.contract.to_dict())

        def cancel_then_crash(**kwargs):
            self.brain.cancel_task(task["id"], "Stop now.")
            raise RuntimeError("backend stopped")

        with patch("core.agent_loop.run_agent", side_effect=cancel_then_crash):
            with self.assertRaises(RuntimeError):
                self.brain.run_prepared_task(task["id"])
        saved = self.brain.get_task(task["id"])
        self.assertEqual(saved["status"], "cancelled")
        self.assertEqual(saved["result"], "Stop now.")

    def test_clarification_revises_same_task_for_execution(self):
        initial = TaskIntent(
            intent="act",
            goal="delete project",
            needs_clarification=True,
            clarification_question="Which project?",
        )
        resolved = TaskIntent(
            intent="act",
            goal="delete the demo project",
            success_criteria=["demo project is absent"],
        )
        self.brain.understand_task = MagicMock(side_effect=[initial, resolved])
        task = self.brain.prepare_task("delete it")
        revised = self.brain.clarify_task(task["id"], "The demo project.")
        self.assertEqual(revised["id"], task["id"])
        self.assertEqual(revised["status"], "pending")
        self.assertIn("The demo project.", revised["request"])
        self.assertEqual(revised["contract"]["goal"], "delete the demo project")
        self.assertEqual(revised["events"][-1]["type"], "clarification_received")

    def test_insufficient_clarification_keeps_task_waiting(self):
        initial = TaskIntent(
            intent="act", goal="delete project", needs_clarification=True,
            clarification_question="Which project?",
        )
        still_unclear = TaskIntent(
            intent="act", goal="delete project", needs_clarification=True,
            clarification_question="Please provide the project path.",
        )
        self.brain.understand_task = MagicMock(side_effect=[initial, still_unclear])
        task = self.brain.prepare_task("delete it")
        revised = self.brain.clarify_task(task["id"], "That one.")
        self.assertEqual(revised["status"], "waiting")
        self.assertEqual(revised["result"], "Please provide the project path.")
        self.assertEqual(
            revised["contract"]["clarification_question"],
            "Please provide the project path.",
        )
        self.assertIn("That one.", revised["request"])
        self.assertEqual(revised["events"][-1]["type"], "clarification_insufficient")

    def test_nonwaiting_task_rejects_clarification(self):
        task = self.brain.tasks.create("inspect", self.contract.to_dict())
        with self.assertRaises(ValueError):
            self.brain.clarify_task(task["id"], "details")


if __name__ == "__main__":
    unittest.main()
