from pathlib import Path
import unittest


HTML = (Path(__file__).resolve().parent / "web" / "index.html").read_text(
    encoding="utf-8-sig"
)


class WebTaskCenterRegressionTests(unittest.TestCase):
    def test_task_center_can_submit_durable_tasks(self):
        self.assertIn('id="taskInput"', HTML)
        self.assertIn('id="taskCreateBtn"', HTML)
        self.assertIn("fetch('/tasks',{method:'POST'", HTML)
        self.assertIn("JSON.stringify({message,session_id:sessionId})", HTML)

    def test_task_cards_expose_lifecycle_controls(self):
        for action in ('data-act="view"', 'data-act="cancel"', 'data-act="resume"', 'data-act="clarify"'):
            self.assertIn(action, HTML)
        self.assertIn("task.waiting_reason!=='approval'", HTML)

    def test_task_center_polls_with_approvals(self):
        self.assertIn("loadTasks();loadApprovals()", HTML)
        self.assertIn("if(tomeOpened){loadTasks();loadApprovals()}", HTML)

    def test_task_output_is_rendered_as_text_not_raw_html(self):
        self.assertIn("addMessage(`Task ${id} — ${task.status}", HTML)
        self.assertNotIn("innerHTML=task.result", HTML)


if __name__ == "__main__":
    unittest.main()
