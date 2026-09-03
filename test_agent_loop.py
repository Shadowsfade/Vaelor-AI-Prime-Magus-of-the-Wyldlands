import unittest
from unittest.mock import patch

from core.agent_loop import _auto_confirm, _looks_failed, run_agent


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return next(self.replies)


class AgentLoopTests(unittest.TestCase):
    def test_missing_policy_does_not_auto_confirm(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.assertFalse(_auto_confirm())

    def test_read_only_task_can_finish_without_verification(self):
        model = ScriptedModel(["FINAL_SUMMARY: SUCCESS inspected safely"])
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent("inspect status", model)
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS inspected safely")

    def test_success_after_mutation_requires_verification(self):
        model = ScriptedModel([
            'ACTION: apply_patch path=x.py old="a" new="b"',
            "FINAL_SUMMARY: SUCCESS changed x.py",
            'ACTION: shell_exec command="python -m py_compile x.py"',
            "FINAL_SUMMARY: SUCCESS changed and checked x.py",
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="[OK]"),
        ):
            result = run_agent("change x.py", model, max_steps=6)
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS changed and checked x.py")
        self.assertIn("not been verified", model.prompts[2].lower())

    def test_unknown_tool_is_a_failure(self):
        self.assertTrue(_looks_failed("Unknown tool: missing_tool"))

    def test_mutation_after_verification_invalidates_the_check(self):
        model = ScriptedModel([
            'ACTION: apply_patch path=x.py old="a" new="b"',
            'ACTION: shell_exec command="python -m py_compile x.py"',
            'ACTION: apply_patch path=x.py old="b" new="c"',
            "FINAL_SUMMARY: SUCCESS finished",
            "FINAL_SUMMARY: FAILED verification still required",
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="[OK]"),
        ):
            result = run_agent("change x.py twice", model, max_steps=6)
        self.assertEqual(result, "FINAL_SUMMARY: FAILED verification still required")


if __name__ == "__main__":
    unittest.main()
