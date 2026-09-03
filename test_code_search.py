from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.tools.code_search import search_codebase


class CodeSearchTests(unittest.TestCase):
    def search(self, root, query, **kwargs):
        with patch("core.tools.code_search._resolve_path", return_value=str(root)):
            return search_codebase(query, str(root), **kwargs)

    def test_ranks_filename_and_content_matches_with_line_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "terminal_agent.py").write_text(
                "def terminal_output():\n    return 'stream'\n", encoding="utf-8"
            )
            (root / "other.py").write_text("terminal once\n", encoding="utf-8")
            result = self.search(root, "terminal output")
        self.assertLess(result.index("terminal_agent.py"), result.index("other.py"))
        self.assertIn("1: def terminal_output", result)

    def test_excludes_dependency_and_binary_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "node_modules").mkdir()
            (root / "node_modules" / "hidden.js").write_text("secretterm", encoding="utf-8")
            (root / "image.png").write_bytes(b"secretterm")
            result = self.search(root, "secretterm")
        self.assertIn("No matching source text", result)

    def test_result_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(5):
                (root / f"file{index}.py").write_text("needle\n", encoding="utf-8")
            result = self.search(root, "needle", limit=2)
        self.assertEqual(result.count("--- file"), 2)

    def test_empty_query_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                self.search(Path(temp), "!!!")

    def test_total_scan_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "first.py").write_text("needle", encoding="utf-8")
            (root / "second.py").write_text("needle", encoding="utf-8")
            with patch("core.tools.code_search.MAX_TOTAL_BYTES", 7):
                result = self.search(root, "needle")
        self.assertEqual(result.count("--- "), 1)


if __name__ == "__main__":
    unittest.main()
