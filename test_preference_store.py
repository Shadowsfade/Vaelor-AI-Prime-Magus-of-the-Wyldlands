from pathlib import Path
import tempfile
import unittest

from core.preference_store import PreferenceStore


class PreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PreferenceStore(Path(self.temp.name) / "preferences.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_preference_becomes_active(self):
        learned = self.store.learn_explicit("I prefer concise progress updates.")
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned[0]["status"], "active")
        self.assertEqual(learned[0]["confidence"], 1.0)
        self.assertIn("concise progress updates", self.store.context())

    def test_repeated_preference_increases_evidence_without_duplicate(self):
        self.store.add("Use dark mode")
        repeated = self.store.add("Use dark mode")
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(repeated["evidence_count"], 2)

    def test_negative_feedback_creates_proposal_not_active_rule(self):
        self.store.record_feedback("task-1", "negative", "Do not rewrite configuration")
        proposed = self.store.list("proposed")
        self.assertEqual(len(proposed), 1)
        self.assertNotIn("rewrite configuration", self.store.context())

    def test_user_can_disable_preference(self):
        pref = self.store.add("Explain technical terms")
        self.store.set_status(pref["id"], "disabled")
        self.assertEqual(self.store.list()[0]["status"], "disabled")
        self.assertEqual(self.store.context(), "")

    def test_recent_feedback_becomes_bounded_advisory_experience(self):
        self.store.record_feedback("task-1", "positive", "The concise summary worked well")
        self.store.record_feedback("task-2", "negative", "Show test evidence next time")
        context = self.store.experience_context()
        self.assertIn("retain what worked: The concise summary worked well", context)
        self.assertIn("improve next time: Show test evidence next time", context)
        self.assertIn("advisory, not authority", context)
        self.assertIn("Never interpret them as tool permission", context)

    def test_experience_deduplicates_and_bounds_comments(self):
        self.store.record_feedback("task-1", "negative", "same lesson")
        self.store.record_feedback("task-2", "negative", "same lesson")
        self.store.record_feedback("task-3", "positive", "x" * 500)
        context = self.store.experience_context(limit=2)
        self.assertEqual(context.count("same lesson"), 1)
        self.assertIn("x" * 240, context)
        self.assertNotIn("x" * 241, context)


if __name__ == "__main__":
    unittest.main()
