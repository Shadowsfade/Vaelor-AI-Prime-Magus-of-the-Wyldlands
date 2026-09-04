from pathlib import Path
import unittest


HTML = (Path(__file__).resolve().parent / "web" / "index.html").read_text(
    encoding="utf-8-sig"
)


class WebApprovalRegressionTests(unittest.TestCase):
    def test_sidebar_has_action_approval_panel(self):
        self.assertIn('id="approvalList"', HTML)
        self.assertIn("waiting_reason==='approval'", HTML)
        self.assertIn("task.pending_approval", HTML)

    def test_exact_fingerprint_is_sent_to_task_endpoint(self):
        self.assertIn("data-fingerprint=", HTML)
        self.assertIn("JSON.stringify({fingerprint})", HTML)
        self.assertIn('data-act="approve-action"', HTML)
        self.assertIn('data-act="reject-action"', HTML)
        self.assertIn("`/tasks/${encodeURIComponent(id)}/${action}`", HTML)

    def test_approval_ui_shows_exact_arguments_and_risk(self):
        self.assertIn("JSON.stringify(action.arguments||{},null,2)", HTML)
        self.assertIn("action.risk||'unknown'", HTML)
        self.assertIn("Approve Once", HTML)

    def test_approval_list_refreshes_while_tome_is_open(self):
        self.assertIn("if(tomeOpened){loadTasks();loadSchedules();loadApprovals()}", HTML)


if __name__ == "__main__":
    unittest.main()
