from pathlib import Path
import json
import tempfile
import unittest

from core.conversation_memory import MAX_SUMMARY_CHARS, VaelorConversationMemory


class ConversationCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = VaelorConversationMemory(
            Path(self.temp.name), compact_after=4, keep_recent=2
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_automatically_compacts_old_session_turns(self):
        for index in range(5):
            self.memory.remember_turn(f"prompt {index}", f"response {index}", "s1")
        recent = self.memory.recall_recent(20, "s1")
        self.assertEqual(len(recent), 2)
        self.assertIn("prompt 0", self.memory.get_summary("s1"))
        self.assertIn("response 2", self.memory.get_summary("s1"))

    def test_compaction_does_not_remove_other_sessions(self):
        self.memory.remember_turn("other", "safe", "s2")
        for index in range(5):
            self.memory.remember_turn(str(index), str(index), "s1")
        self.assertEqual(self.memory.recall_recent(10, "s2")[0]["prompt"], "other")

    def test_summary_is_bounded_and_valid_json_is_persisted(self):
        for index in range(5):
            self.memory.remember_turn("p" * 1000, "r" * 2000, "s1")
        self.assertLessEqual(len(self.memory.get_summary("s1")), MAX_SUMMARY_CHARS)
        for name in ("conversations.json", "sessions.json", "conversation_summaries.json"):
            self.assertIsInstance(json.loads((Path(self.temp.name) / name).read_text()), list)

    def test_clear_session_removes_turns_session_and_summary(self):
        for index in range(5):
            self.memory.remember_turn(str(index), str(index), "s1")
        self.memory.clear_session("s1")
        self.assertEqual(self.memory.recall_recent(10, "s1"), [])
        self.assertEqual(self.memory.get_summary("s1"), "")
        self.assertFalse(any(item["id"] == "s1" for item in self.memory.list_sessions()))


if __name__ == "__main__":
    unittest.main()
