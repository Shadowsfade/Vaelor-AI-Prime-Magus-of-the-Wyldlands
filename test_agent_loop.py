import unittest
from unittest.mock import patch

from core.agent_loop import (
    MAX_OBSERVATION_CONTEXT_CHARS,
    MAX_TOOL_RESULT_CHARS,
    _auto_confirm,
    _action_risk,
    _allows_automatic_action,
    _bounded_text,
    _looks_failed,
    _is_mutating_action,
    _recent_observations,
    run_agent,
)


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return next(self.replies)


class AgentLoopTests(unittest.TestCase):
    def test_autonomy_matrix_blocks_high_risk_in_trusted(self):
        self.assertTrue(_allows_automatic_action("trusted", "medium"))
        self.assertFalse(_allows_automatic_action("trusted", "high"))
        self.assertFalse(_allows_automatic_action("supervised", "low"))
        self.assertTrue(_allows_automatic_action("admin", "high"))

    def test_shell_risk_detects_destructive_and_publish_commands(self):
        self.assertEqual(_action_risk("shell_exec", {"command": "git push origin main"}), "high")
        self.assertEqual(_action_risk("shell_exec", {"command": "Remove-Item demo.txt"}), "high")

    def test_read_only_shell_is_not_treated_as_mutation(self):
        kwargs = {"command": "python -m unittest -v test_agent_loop.py"}
        self.assertFalse(_is_mutating_action("shell_exec", kwargs))
        self.assertEqual(_action_risk("shell_exec", kwargs), "read")

    def test_supervised_mode_allows_read_only_shell(self):
        model = ScriptedModel([
            '{"thought":"inspect","actions":[{"tool":"shell_exec",'
            '"arguments":{"command":"git status --short","confirm":"yes"}}],"final":null}',
            '{"thought":"done","actions":[],"final":'
            '{"status":"SUCCESS","summary":"inspected"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop._autonomy_mode", return_value="supervised"),
            patch("core.agent_loop.registry.execute", return_value="[OK]") as execute,
        ):
            result = run_agent("inspect status", model)
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS inspected")
        execute.assert_called_once_with(
            "shell_exec", command="git status --short", confirm="yes"
        )

    def test_supervised_mode_ignores_model_authored_confirmation(self):
        model = ScriptedModel([
            '{"thought":"write","actions":[{"tool":"write_text_file",'
            '"arguments":{"path":"x.txt","content":"x","confirm":"yes"}}],"final":null}',
            '{"thought":"blocked","actions":[],"final":'
            '{"status":"FAILED","summary":"approval required"}}',
        ])
        events = []
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop._autonomy_mode", return_value="supervised"),
            patch("core.agent_loop.registry.execute") as execute,
        ):
            result = run_agent(
                "write x", model, event_callback=lambda event, data: events.append(event)
            )
        self.assertEqual(result, "FINAL_SUMMARY: FAILED approval required")
        execute.assert_not_called()
        self.assertIn("action_blocked", events)

    def test_trusted_mode_blocks_high_risk_tool_before_execution(self):
        model = ScriptedModel([
            '{"thought":"publish","actions":[{"tool":"git_push",'
            '"arguments":{"remote":"origin","confirm":"yes"}}],"final":null}',
            '{"thought":"blocked","actions":[],"final":'
            '{"status":"FAILED","summary":"admin required"}}',
        ])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop._autonomy_mode", return_value="trusted"),
            patch("core.agent_loop.registry.execute") as execute,
        ):
            result = run_agent("push changes", model)
        self.assertEqual(result, "FINAL_SUMMARY: FAILED admin required")
        execute.assert_not_called()

    def test_runtime_deadline_stops_before_model(self):
        model = ScriptedModel(["FINAL_SUMMARY: SUCCESS should not run"])
        events = []
        ticks = iter([0.0, 11.0])
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent(
                "inspect",
                model,
                max_runtime_seconds=10,
                clock=lambda: next(ticks),
                event_callback=lambda event, data: events.append((event, data)),
            )
        self.assertIn("exceeded its 10s runtime limit", result)
        self.assertEqual(model.prompts, [])
        self.assertEqual(events[0][0], "task_timed_out")
    def test_large_tool_result_keeps_head_and_tail_with_bound(self):
        value = "HEAD" + ("x" * 20000) + "TAIL"
        bounded = _bounded_text(value)
        self.assertLessEqual(len(bounded), MAX_TOOL_RESULT_CHARS)
        self.assertTrue(bounded.startswith("HEAD"))
        self.assertTrue(bounded.endswith("TAIL"))
        self.assertIn("truncated", bounded)

    def test_observation_context_prefers_most_recent_with_bound(self):
        observations = ["old-" + ("a" * 20000), "new-" + ("b" * 20000)]
        context = _recent_observations(observations)
        self.assertLessEqual(len(context), MAX_OBSERVATION_CONTEXT_CHARS)
        self.assertIn("new-", context)
        self.assertNotIn("old-", context)

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
            patch("core.agent_loop._autonomy_mode", return_value="admin"),
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
            patch("core.agent_loop._autonomy_mode", return_value="admin"),
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
            patch("core.agent_loop._autonomy_mode", return_value="admin"),
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
        checks = iter([False, False, False, False, True])
        with (
            patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"),
            patch("core.agent_loop.registry.execute", return_value="files") as execute,
        ):
            result = run_agent("inspect", model, should_cancel=lambda: next(checks))
        self.assertTrue(result.startswith("FINAL_SUMMARY: CANCELLED"))
        execute.assert_called_once()

    def test_transient_model_failure_is_retried(self):
        calls = []

        def model(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise ConnectionError("local backend warming up")
            return "FINAL_SUMMARY: SUCCESS backend recovered"

        events = []
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent(
                "inspect",
                model,
                event_callback=lambda event, data: events.append((event, data)),
            )
        self.assertEqual(result, "FINAL_SUMMARY: SUCCESS backend recovered")
        self.assertEqual(len(calls), 2)
        self.assertEqual(events[0][0], "model_retry")
        self.assertEqual(events[0][1]["retries_remaining"], 2)

    def test_exhausted_model_retries_raise_clear_error(self):
        def model(prompt):
            raise ConnectionError("backend offline")

        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            with self.assertRaisesRegex(RuntimeError, "failed after 2 attempt"):
                run_agent("inspect", model, model_retries=1)

    def test_cancellation_is_checked_between_model_retries(self):
        model_calls = 0
        checks = iter([False, False, True])

        def model(prompt):
            nonlocal model_calls
            model_calls += 1
            raise ConnectionError("backend offline")

        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"):
            result = run_agent("inspect", model, should_cancel=lambda: next(checks))
        self.assertTrue(result.startswith("FINAL_SUMMARY: CANCELLED"))
        self.assertEqual(model_calls, 1)


if __name__ == "__main__":
    unittest.main()
