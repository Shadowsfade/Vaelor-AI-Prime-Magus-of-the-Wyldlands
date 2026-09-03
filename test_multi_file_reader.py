from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.tools.multi_file_reader import (
    MAX_FILES,
    MAX_TOTAL_CHARS,
    read_many_text_files,
)


class MultiFileReaderTests(unittest.TestCase):
    def test_reads_multiple_files_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "a.py"
            second = root / "b.py"
            first.write_text("alpha", encoding="utf-8")
            second.write_text("beta", encoding="utf-8")
            with patch(
                "core.tools.multi_file_reader._resolve_path",
                side_effect=lambda path, must_exist=False: str(Path(path)),
            ):
                result = read_many_text_files([str(first), str(second)])
        self.assertLess(result.index("alpha"), result.index("beta"))

    def test_rejects_too_many_files(self):
        result = read_many_text_files(["x"] * (MAX_FILES + 1))
        self.assertIn(f"at most {MAX_FILES}", result)

    def test_requires_json_array(self):
        self.assertIn("JSON array", read_many_text_files("a.py"))

    def test_total_output_content_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for index in range(5):
                path = root / f"{index}.txt"
                path.write_text("x" * 20000, encoding="utf-8")
                paths.append(str(path))
            with patch(
                "core.tools.multi_file_reader._resolve_path",
                side_effect=lambda path, must_exist=False: str(Path(path)),
            ):
                result = read_many_text_files(paths, max_total_chars=5000)
        self.assertLess(len(result), 7000)
        self.assertIn("total budget reached", result)

    def test_path_failure_does_not_abort_other_files(self):
        with tempfile.TemporaryDirectory() as temp:
            good = Path(temp) / "good.txt"
            good.write_text("usable", encoding="utf-8")

            def resolve(path, must_exist=False):
                if path == "blocked":
                    raise PermissionError("outside allowed roots")
                return str(good)

            with patch("core.tools.multi_file_reader._resolve_path", side_effect=resolve):
                result = read_many_text_files(["blocked", str(good)])
        self.assertIn("outside allowed roots", result)
        self.assertIn("usable", result)


if __name__ == "__main__":
    unittest.main()
