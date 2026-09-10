from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.task_intent import TaskIntent


class _Memory:
    def __init__(self, context=""):
        self.context = context

    def build_context(self, prompt, limit=8):
        return self.context


class _Conversations:
    def recall_recent(self, limit=8, session_id=None):
        return []

    def get_summary(self, session_id):
        return ""

    def recall_session_messages(self, session_id, limit=8):
        return []

    def remember_turn(self, prompt, response, session_id=None):
        return None


class _Preferences:
    def learn_explicit(self, prompt):
        return None

    def context(self):
        return ""

    def experience_context(self):
        return ""


def _runtime():
    return SimpleNamespace(
        identity={"name": "Vaelor", "title": "Prime Magus"},
        personality={"personality": {"tone": "calm"}},
        settings={}, capabilities={}, lore={}, vaelor={}, world_authority={}, roadmap={}, models={},
    )


class BrainTests(unittest.TestCase):
    def test_runtime_exposes_a_brain_without_live_provider(self):
        # Importing the runtime module is safe here because the provider and
        # persistence boundaries are patched before constructing the runtime.
        with (
            patch("core.brain.VaelorMemoryManager", return_value=_Memory()),
            patch("core.brain.VaelorConversationMemory", return_value=_Conversations()),
            patch("core.brain.PreferenceStore", return_value=_Preferences()),
            patch("core.brain.cast_spell", return_value="mocked answer"),
        ):
            from core.runtime import VaelorRuntime
            runtime = VaelorRuntime()
        self.assertIsNotNone(runtime.brain)
        self.assertEqual(runtime.brain.runtime, runtime)

    def test_brain_answers_through_mocked_provider(self):
        from core.brain import VaelorBrain
        with (
            patch("core.brain.VaelorMemoryManager", return_value=_Memory()),
            patch("core.brain.VaelorConversationMemory", return_value=_Conversations()),
            patch("core.brain.PreferenceStore", return_value=_Preferences()),
            patch("core.brain.classify_task", return_value=TaskIntent("chat", "question", source="test")),
            patch("core.brain.cast_spell", return_value="mocked answer") as provider,
        ):
            brain = VaelorBrain(_runtime())
            answer = brain.think("What is the Wyldlands?", use_web=False)
        self.assertEqual(answer, "mocked answer")
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[0], "core_reasoning")


if __name__ == "__main__":
    unittest.main()
