from pathlib import Path
import tempfile
import unittest

from core.memory import VaelorMemory
from core.memory_manager import VaelorMemoryManager


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "archive.json"
        self.manager = VaelorMemoryManager(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_normalized_duplicates_are_not_added(self):
        self.manager.remember("technical", "Use  Python   3.12")
        self.manager.remember("technical", "use python 3.12")
        self.assertEqual(len(self.manager.recall()), 1)

    def test_relevant_memory_ranks_above_unrelated_memory(self):
        relevant = self.manager.remember("technical", "The API health endpoint uses port 8765")
        self.manager.remember("world", "The western forest contains silver trees")
        ranked = sorted(
            self.manager.recall(),
            key=lambda item: self.manager.score_memory(item, "which port does the API health endpoint use"),
            reverse=True,
        )
        self.assertEqual(ranked[0]["id"], relevant["id"])

    def test_low_confidence_unrelated_rule_is_not_global_context(self):
        self.manager.remember(
            "rule", "Always use purple headings", importance=2,
            source="inferred", confidence=0.4,
        )
        self.assertNotIn("purple headings", self.manager.build_context("check API status"))

    def test_high_authority_rule_is_global_context(self):
        self.manager.remember(
            "rule", "Never erase user projects", importance=10,
            source="user_explicit", confidence=1.0,
        )
        self.assertIn("Never erase user projects", self.manager.build_context("check status"))

    def test_corrupt_archive_fails_empty_instead_of_crashing(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(VaelorMemory(self.path).recall(), [])

    def test_memory_records_provenance(self):
        item = self.manager.remember(
            "project", "Use FastAPI", source="task_feedback", confidence=0.6, tags=["backend"]
        )
        self.assertEqual(item["source"], "task_feedback")
        self.assertEqual(item["confidence"], 0.6)
        self.assertEqual(item["tags"], ["backend"])


if __name__ == "__main__":
    unittest.main()
