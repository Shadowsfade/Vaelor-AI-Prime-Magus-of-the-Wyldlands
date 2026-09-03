from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.project_context import build_project_context, resolve_workspace


class ProjectContextTests(unittest.TestCase):
    def test_snapshot_includes_structure_and_guidance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("Build with care.", encoding="utf-8")
            (root / "src").mkdir()
            with (
                patch("core.project_context._resolve_path", return_value=str(root)),
                patch("core.project_context._git_root", return_value=root),
            ):
                context = build_project_context(str(root))
        self.assertIn("project_root:", context)
        self.assertIn("README.md", context)
        self.assertIn("src/", context)
        self.assertIn("Build with care.", context)

    def test_package_context_only_keeps_task_relevant_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text(
                '{"name":"demo","scripts":{"test":"vitest"},"secret":"omit"}',
                encoding="utf-8",
            )
            with (
                patch("core.project_context._resolve_path", return_value=str(root)),
                patch("core.project_context._git_root", return_value=root),
            ):
                context = build_project_context(str(root))
        self.assertIn('"test": "vitest"', context)
        self.assertNotIn("secret", context)

    def test_workspace_must_be_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = Path(temp) / "file.txt"
            file_path.write_text("x", encoding="utf-8")
            with patch("core.project_context._resolve_path", return_value=str(file_path)):
                with self.assertRaisesRegex(ValueError, "not a directory"):
                    resolve_workspace(str(file_path))

    def test_unapproved_git_root_falls_back_to_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            outside = Path(temp) / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "README.md").write_text("inside", encoding="utf-8")
            (outside / "README.md").write_text("outside", encoding="utf-8")

            def resolve(path, must_exist=False):
                if Path(path) == outside:
                    raise PermissionError("outside allowed roots")
                return str(workspace)

            with (
                patch("core.project_context._resolve_path", side_effect=resolve),
                patch("core.project_context._git_root", return_value=outside),
            ):
                context = build_project_context(str(workspace))
        self.assertIn("inside", context)
        self.assertNotIn("outside\n", context)


if __name__ == "__main__":
    unittest.main()
