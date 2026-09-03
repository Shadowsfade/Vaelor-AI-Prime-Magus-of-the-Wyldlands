import tempfile
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from core.tools.git_ops import _redact_sensitive_diff, review_git_changes


class GitReviewTests(unittest.TestCase):
    def test_redacts_likely_secret_values_and_warns(self):
        safe, warnings = _redact_sensitive_diff("+API_KEY=super-secret\n+normal = True")
        self.assertNotIn("super-secret", safe)
        self.assertIn("[REDACTED POSSIBLE SECRET]", safe)
        self.assertIn("possible credential material was redacted", warnings)

    def test_warns_about_added_conflict_markers(self):
        _, warnings = _redact_sensitive_diff("+<<<<<<< HEAD\n+=======\n+>>>>>>> branch")
        self.assertIn("added merge-conflict marker detected", warnings)

    def test_reviews_real_repository_changes_without_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            target = root / "demo.py"
            target.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "demo.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"],
                cwd=root, check=True,
            )
            target.write_text("value = 2\n", encoding="utf-8")
            with patch("core.tools.git_ops._resolve_path", return_value=str(root)):
                result = review_git_changes(str(root))
            status = subprocess.run(["git", "status", "--short"], cwd=root, capture_output=True, text=True, check=True).stdout
        self.assertIn("demo.py", result)
        self.assertIn("value = 2", result)
        self.assertEqual(status.strip(), "M demo.py")


if __name__ == "__main__":
    unittest.main()
