import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import api.server as server


class TaskApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.brain = MagicMock()
        self.brain.prepare_task.return_value = {
            "id": "task-1", "status": "pending", "events": [], "result": None,
        }
        self.patcher = patch.object(server, "brain", self.brain)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.client.close()

    def test_create_forwards_workspace_and_runs_background_task(self):
        response = self.client.post("/tasks", json={
            "message": "inspect this project",
            "workspace": "C:/demo",
            "max_steps": 8,
        })
        self.assertEqual(response.status_code, 200)
        self.brain.prepare_task.assert_called_once_with(
            "inspect this project", None, "C:/demo"
        )
        self.brain.run_prepared_task.assert_called_once_with("task-1", 8)

    def test_waiting_task_does_not_start_without_clarification(self):
        self.brain.prepare_task.return_value = {
            "id": "task-2", "status": "waiting", "result": "Which project?",
        }
        response = self.client.post("/tasks", json={"message": "delete it"})
        self.assertEqual(response.status_code, 200)
        self.brain.run_prepared_task.assert_not_called()

    def test_clarification_continues_pending_task(self):
        self.brain.clarify_task.return_value = {
            "id": "task-2", "status": "pending", "events": [], "result": None,
        }
        response = self.client.post(
            "/tasks/task-2/clarify", json={"answer": "C:/demo", "max_steps": 9}
        )
        self.assertEqual(response.status_code, 200)
        self.brain.clarify_task.assert_called_once_with("task-2", "C:/demo")
        self.brain.run_prepared_task.assert_called_once_with("task-2", 9)

    def test_cancel_conflict_is_reported(self):
        self.brain.cancel_task.side_effect = ValueError("Completed tasks cannot be cancelled.")
        response = self.client.post("/tasks/task-1/cancel", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("cannot be cancelled", response.json()["detail"])

    def test_unknown_task_is_404(self):
        self.brain.get_task.return_value = None
        response = self.client.get("/tasks/missing")
        self.assertEqual(response.status_code, 404)

    def test_invalid_step_budget_is_rejected_at_boundary(self):
        response = self.client.post(
            "/tasks", json={"message": "inspect", "max_steps": 1000}
        )
        self.assertEqual(response.status_code, 422)
        self.brain.prepare_task.assert_not_called()

    def test_terminal_event_stream_includes_result(self):
        self.brain.get_task.return_value = {
            "id": "task-1",
            "status": "completed",
            "attempts": 1,
            "events": [{"type": "started", "data": {}}],
            "result": "FINAL_SUMMARY: SUCCESS done",
        }
        response = self.client.get("/tasks/task-1/events")
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: progress", response.text)
        self.assertIn("event: result", response.text)
        self.assertIn("FINAL_SUMMARY: SUCCESS done", response.text)

    def test_readiness_uses_service_status_code(self):
        with patch("api.server.assess_readiness", return_value={
            "ready": False, "status": "not_ready", "checks": {}, "issues": ["offline"],
        }):
            response = self.client.get("/readiness")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ready"])


if __name__ == "__main__":
    unittest.main()
