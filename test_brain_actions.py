import unittest
from unittest.mock import MagicMock, patch

from core.brain import VaelorBrain
from core.task_intent import TaskIntent


class BrainActionTests(unittest.TestCase):
    def test_agent_code_prompt_cannot_launch_nested_aider(self):
        with patch("spellbook.llm_client.chat", return_value="FINAL: done") as chat, patch("spellbook.spell_router.cast_aider_spell", side_effect=AssertionError("nested agent")):
            response = VaelorBrain._agent_reply("modify file app.py", "code_forge")
        self.assertEqual(response, "FINAL: done")
        chat.assert_called_once_with("modify file app.py", spell="code_forge")

    def test_agent_failure_is_reported_instead_of_becoming_chat(self):
        brain = VaelorBrain.__new__(VaelorBrain)
        brain.conversations = MagicMock()
        brain.wants_action = MagicMock(return_value=True)
        brain.act = MagicMock(side_effect=RuntimeError("model unavailable"))

        contract = TaskIntent(intent="act", goal="fix the project")
        with patch.object(brain, "understand_task", return_value=contract):
            result = brain.think("fix the project", session_id="session-1")

        self.assertIn("agent loop failed", result)
        self.assertIn("model unavailable", result)
        brain.conversations.remember_turn.assert_called_once_with(
            "fix the project", result, session_id="session-1"
        )

    def test_clarification_stops_before_action(self):
        brain = VaelorBrain.__new__(VaelorBrain)
        brain.conversations = MagicMock()
        brain.act = MagicMock()
        contract = TaskIntent(
            intent="act",
            goal="delete a project",
            needs_clarification=True,
            clarification_question="Which project should I delete?",
        )
        with patch.object(brain, "understand_task", return_value=contract):
            result = brain.think("delete the project", session_id="session-2")
        self.assertEqual(result, "Which project should I delete?")
        brain.act.assert_not_called()


if __name__ == "__main__":
    unittest.main()
