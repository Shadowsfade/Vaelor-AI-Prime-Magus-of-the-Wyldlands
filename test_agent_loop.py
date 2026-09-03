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

    def test_invalid_json_protocol_is_returned_for_correction(self):
        model = ScriptedModel([
            '{"thought":"inspect","actions":"wrong","final":null}',
            '{"thought":"done","actions":[],"final":'
            '{"status":"SUCCESS","summary":"corrected protocol"}}',
        ])
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent("inspect", model)
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS corrected protocol")
        self.assertIn("invalid action protocol", model.prompts[1].lower())

    def test_structured_action_preserves_argument_types(self):
        model = ScriptedModel([
            '{"thought":"inspect","actions":[{"tool":"list_dir","arguments":'
            '{"path":".","recursive":true}}],"final":null}',
            '{"thought":"done","actions":[],"final":'
            '{"status":"SUCCESS","summary":"inspected"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="files") as execute,
        ):
            result = run_agent("inspect", model)
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS inspected")
        execute.assert_called_once_with("list_dir", path=".", recursive=True)

    def test_invalid_tool_arguments_are_not_executed(self):
        model = ScriptedModel([
            '{"thought":"inspect","actions":[{"tool":"list_dir","arguments":'
            '{"path":".","not_a_real_argument":true}}],"final":null}',
            '{"thought":"cannot continue","actions":[],"final":'
            '{"status":"FAILED","summary":"invalid arguments"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute") as execute,
        ):
            result = run_agent("inspect", model)
        self.assertEqual(result, "FINAL_SUMMARY: FAILED invalid arguments")
        execute.assert_not_called()

    def test_confirm_is_not_injected_when_tool_does_not_accept_it(self):
        model = ScriptedModel([
            '{"thought":"set mode","actions":[{"tool":"set_autonomy_mode",'
            '"arguments":{"mode":"supervised"}}],"final":null}',
            '{"thought":"done","actions":[],"final":'
            '{"status":"SUCCESS","summary":"mode set"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="[OK]") as execute,
        ):
            run_agent("set supervised mode", model, require_verification=False)
        execute.assert_called_once_with("set_autonomy_mode", mode="supervised")

    def test_action_batch_validates_before_any_tool_runs(self):
        model = ScriptedModel([
            '{"thought":"inspect twice","actions":['
            '{"tool":"list_dir","arguments":{"path":"."}},'
            '{"tool":"list_dir","arguments":{"invalid":true}}],"final":null}',
            '{"thought":"stop","actions":[],"final":'
            '{"status":"FAILED","summary":"corrected nothing"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute") as execute,
        ):
            result = run_agent("inspect twice", model)
        self.assertEqual(result, "FINAL_SUMMARY: FAILED corrected nothing")
        execute.assert_not_called()

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

    def test_cancellation_stops_before_model_call(self):
        model = ScriptedModel(["FINAL_SUMMARY: SUCCESS should not run"])
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent("inspect", model, should_cancel=lambda: True)
        self.assertEqual(result, "FINAL_SUMMARY: CANCELLED Task cancellation was requested.")
        self.assertEqual(model.prompts, [])

    def test_cancellation_stops_between_tools(self):
        model = ScriptedModel([
            '{"thought":"inspect","actions":['
            '{"tool":"list_dir","arguments":{"path":"."}},'
            '{"tool":"list_dir","arguments":{"path":"other"}}],"final":null}',
        ])
        checks = iter([False, False, False, True])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="files") as execute,
        ):
            result = run_agent("inspect", model, should_cancel=lambda: next(checks))
        self.assertTrue(result.startswith("FINAL_SUMMARY: CANCELLED"))
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
