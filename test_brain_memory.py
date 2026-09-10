import unittest
from unittest.mock import patch

from core.brain import VaelorBrain
from core.task_intent import TaskIntent

from test_brain import _Conversations, _Memory, _Preferences, _runtime


class BrainMemoryTests(unittest.TestCase):
    def test_remembered_context_is_supplied_to_reasoning(self):
        remembered = "The Architect prefers careful incremental development."
        with (
            patch("core.brain.VaelorMemoryManager", return_value=_Memory(remembered)),
            patch("core.brain.VaelorConversationMemory", return_value=_Conversations()),
            patch("core.brain.PreferenceStore", return_value=_Preferences()),
            patch("core.brain.classify_task", return_value=TaskIntent("chat", "question", source="test")),
            patch("core.brain.cast_spell", return_value="context-aware answer") as provider,
        ):
            brain = VaelorBrain(_runtime())
            answer = brain.think("Who is the Architect?", use_web=False)
        self.assertEqual(answer, "context-aware answer")
        prompt = provider.call_args.args[1]
        self.assertIn(remembered, prompt)


if __name__ == "__main__":
    unittest.main()
