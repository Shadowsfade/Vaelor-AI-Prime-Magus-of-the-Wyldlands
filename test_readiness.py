from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from core.readiness import assess_readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        task_path = Path(self.temp.name) / "tasks.json"
        task_path.write_text("[]", encoding="utf-8")
        self.brain = MagicMock()
        self.brain.tasks.path = task_path
        self.tools = MagicMock()
        self.tools.list_tools.return_value = [{"name": "list_dir"}]

    def tearDown(self):
        self.temp.cleanup()

    def test_ready_requires_tools_storage_backend_and_model(self):
        report = assess_readiness(
            self.brain,
            self.tools,
            lambda: {"ollama": {"running": True, "models": ["qwen"]}},
        )
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")

    def test_running_backend_without_model_is_not_ready(self):
        report = assess_readiness(
            self.brain,
            self.tools,
            lambda: {"ollama": {"running": True, "models": []}},
        )
        self.assertFalse(report["ready"])
        self.assertIn("no model", " ".join(report["issues"]).lower())

    def test_backend_probe_failure_is_reported_not_raised(self):
        def fail():
            raise ConnectionError("probe failed")

        report = assess_readiness(self.brain, self.tools, fail)
        self.assertFalse(report["ready"])
        self.assertIn("probe failed", report["checks"]["model_backend"]["error"])


if __name__ == "__main__":
    unittest.main()
