import unittest
from datetime import datetime, timedelta, timezone
from core.approval_policy import (
    ActionClass, ActionContext, ApprovalDecision, ApprovalPolicy, AutoApproveMode,
    RiskTier, classify_action,
)

class AutoApprovePolicyTests(unittest.TestCase):
    def test_safe_mode_allows_reads_and_tests_but_off_requires_user(self):
        read = ActionContext("file_reader", {"path": "x"})
        test = ActionContext("shell_exec", {"command": "python -m unittest"})
        self.assertEqual(ApprovalPolicy("OFF").evaluate(read).decision, ApprovalDecision.REQUIRE_USER)
        policy = ApprovalPolicy("SAFE")
        self.assertEqual(policy.evaluate(read).decision, ApprovalDecision.AUTO_APPROVE)
        self.assertEqual(policy.evaluate(test).decision, ApprovalDecision.AUTO_APPROVE)
        self.assertEqual(policy.evaluate(read).risk, RiskTier.LOW)

    def test_trusted_workspace_scope_and_outside_scope(self):
        policy = ApprovalPolicy(AutoApproveMode.TRUSTED_WORKSPACE)
        inside = ActionContext("write_text_file", {"path": r"C:\work\repo\x.txt"}, task_id="t", workspace=r"C:\work\repo")
        outside = ActionContext("write_text_file", {"path": r"C:\other\x.txt"}, task_id="t", workspace=r"C:\work\repo")
        self.assertEqual(policy.evaluate(inside).decision, ApprovalDecision.AUTO_APPROVE)
        self.assertEqual(policy.evaluate(outside).decision, ApprovalDecision.REQUIRE_USER)

    def test_git_and_hard_stops(self):
        policy = ApprovalPolicy("TRUSTED_WORKSPACE")
        self.assertEqual(policy.evaluate(ActionContext("shell_exec", {"command": "git status"})).decision, ApprovalDecision.AUTO_APPROVE)
        self.assertEqual(policy.evaluate(ActionContext("git_push", {"branch": "feature"})).decision, ApprovalDecision.REQUIRE_USER)
        self.assertEqual(policy.evaluate(ActionContext("shell_exec", {"command": "git push origin main"})).risk, RiskTier.CRITICAL)
        self.assertEqual(policy.evaluate(ActionContext("shell_exec", {"command": "git tag v1"})).decision, ApprovalDecision.REQUIRE_USER)
        self.assertEqual(policy.evaluate(ActionContext("shell_exec", {"command": "rm secret.txt"})).decision, ApprovalDecision.REQUIRE_USER)

    def test_scoped_capability_binds_task_session_scope_expiry_and_provenance(self):
        policy = ApprovalPolicy("OFF")
        cap = policy.issue_capability(task_id="t1", session_id="s1", workspace=r"C:\work\repo",
            allowed_classes=[ActionClass.TRUSTED_WORKSPACE_WRITE], lifetime_seconds=60,
            provenance=("event-1",))
        action = ActionContext("write_text_file", {"path": r"C:\work\repo\x.txt"}, task_id="t1", session_id="s1", workspace=r"C:\work\repo")
        result = policy.evaluate(action)
        self.assertEqual(result.decision, ApprovalDecision.AUTO_APPROVE)
        self.assertEqual(result.capability_id, cap.capability_id)
        self.assertEqual(cap.provenance, ("event-1",))
        other = ActionContext("write_text_file", {"path": r"C:\work\repo\x.txt"}, task_id="t2", session_id="s1", workspace=r"C:\work\repo")
        self.assertEqual(policy.evaluate(other).decision, ApprovalDecision.REQUIRE_USER)
        expired = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertEqual(policy.evaluate(action, expired).decision, ApprovalDecision.REQUIRE_USER)

    def test_ambiguous_action_never_calls_a_model(self):
        policy = ApprovalPolicy("SAFE")
        result = policy.evaluate(ActionContext("unknown_tool", {"command": "do something"}))
        self.assertEqual(result.decision, ApprovalDecision.AMBIGUOUS)

if __name__ == "__main__":
    unittest.main()
