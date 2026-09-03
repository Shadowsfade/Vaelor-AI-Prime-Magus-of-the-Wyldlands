from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from core.brain import VaelorBrain
from core.preference_store import PreferenceStore
from core.task_store import TaskStore


class PreferenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.brain = VaelorBrain.__new__(VaelorBrain)
        self.brain.preferences = PreferenceStore(root / "preferences.json")
        self.brain.tasks = TaskStore(root / "tasks.json")
        self.brain.memory = MagicMock()
        self.brain.memory.build_context.return_value = ""
        self.brain._identity_block = MagicMock(return_value="identity")
        self.brain.needs_web = MagicMock(return_value=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_confirmed_preferences_enter_reasoning_context(self):
        self.brain.add_preference("Use concise progress updates")
        context = self.brain._context_prefix("status")
        self.assertIn("User-confirmed preferences", context)
        self.assertIn("concise progress updates", context)

    def test_feedback_is_linked_to_existing_task(self):
        task = self.brain.tasks.create("inspect")
        feedback = self.brain.record_task_feedback(task["id"], "positive", "Worked well")
        self.assertEqual(feedback["task_id"], task["id"])
        saved = self.brain.tasks.get(task["id"])
        self.assertEqual(saved["events"][-1]["type"], "user_feedback")

    def test_feedback_rejects_unknown_task(self):
        with self.assertRaises(KeyError):
            self.brain.record_task_feedback("missing", "positive")


if __name__ == "__main__":
    unittest.main()
