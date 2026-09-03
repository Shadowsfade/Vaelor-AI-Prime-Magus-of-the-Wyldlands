import unittest

from core.task_intent import classify_task, parse_task_intent


class TaskIntentTests(unittest.TestCase):
    def test_parses_fenced_structured_contract(self):
        raw = '''```json
{"intent":"act","goal":"repair startup","success_criteria":["health returns 200"],
 "constraints":["preserve configuration"],"needs_clarification":false,
 "clarification_question":""}
```'''
        task = parse_task_intent(raw, "fix it")
        self.assertTrue(task.should_act)
        self.assertEqual(task.goal, "repair startup")
        self.assertEqual(task.success_criteria, ["health returns 200"])

    def test_malformed_classifier_uses_action_fallback(self):
        task = classify_task("fix startup", lambda _: "not json", True)
        self.assertTrue(task.should_act)
        self.assertEqual(task.source, "fallback")

    def test_classifier_failure_defaults_to_chat_when_not_action_like(self):
        def unavailable(_):
            raise RuntimeError("offline")

        task = classify_task("hello", unavailable, False)
        self.assertFalse(task.should_act)
        self.assertEqual(task.intent, "chat")

    def test_agent_goal_contains_contract(self):
        task = classify_task(
            "repair startup without changing ports",
            lambda _: '{"intent":"act","goal":"repair startup",'
                      '"success_criteria":["health returns 200"],'
                      '"constraints":["do not change ports"],'
                      '"needs_clarification":false,"clarification_question":""}',
        )
        goal = task.as_agent_goal("repair startup without changing ports")
        self.assertIn("NORMALIZED GOAL", goal)
        self.assertIn("health returns 200", goal)
        self.assertIn("do not change ports", goal)

    def test_string_false_does_not_trigger_clarification(self):
        task = parse_task_intent(
            '{"intent":"act","goal":"inspect files","needs_clarification":"false"}',
            "inspect files",
        )
        self.assertFalse(task.needs_clarification)

    def test_chat_never_requests_action_clarification(self):
        task = parse_task_intent(
            '{"intent":"chat","goal":"discuss options","needs_clarification":true, '
            '"clarification_question":"Which file?"}',
            "what are my options?",
        )
        self.assertFalse(task.needs_clarification)

    def test_model_can_mark_reusable_capability_request(self):
        task = parse_task_intent(
            '{"intent":"act","goal":"add adapters","reusable_capability":true,'
            '"capability_reason":"support future project tools"}',
            "gain this ability",
        )
        self.assertTrue(task.reusable_capability)
        self.assertIn("REUSABLE CAPABILITY REQUEST", task.as_agent_goal("gain this ability"))
        self.assertIn("general, modular capability", task.as_agent_goal("gain this ability"))

    def test_fallback_recognizes_self_extension_wording(self):
        task = classify_task(
            "Vaelor should be able to build himself when the user requests a new ability",
            lambda _: "malformed",
            True,
        )
        self.assertTrue(task.reusable_capability)

    def test_one_off_example_is_not_automatically_a_core_extension(self):
        task = classify_task("make this game menu", lambda _: "malformed", True)
        self.assertFalse(task.reusable_capability)


if __name__ == "__main__":
    unittest.main()
