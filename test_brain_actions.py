import unittest
from unittest.mock import MagicMock

from core.brain import VaelorBrain


class BrainActionTests(unittest.TestCase):
    def test_agent_failure_is_reported_instead_of_becoming_chat(self):
        brain = VaelorBrain.__new__(VaelorBrain)
        brain.conversations = MagicMock()
        brain.wants_action = MagicMock(return_value=True)
        brain.act = MagicMock(side_effect=RuntimeError("model unavailable"))

        result = brain.think("fix the project", session_id="session-1")

        self.assertIn("agent loop failed", result)
        self.assertIn("model unavailable", result)
        brain.conversations.remember_turn.assert_called_once_with(
            "fix the project", result, session_id="session-1"
        )


if __name__ == "__main__":
    unittest.main()
