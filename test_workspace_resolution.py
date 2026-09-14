import unittest
from pathlib import Path
from unittest.mock import patch

from core.project_context import resolve_execution_workspace


class WorkspaceResolutionTests(unittest.TestCase):
    def test_valid_requested_workspace_is_used(self):
        with patch("core.project_context.resolve_workspace", return_value=Path("C:/Vaelor")):
            self.assertEqual(resolve_execution_workspace(r"C:\Vaelor", r"C:\Active"), Path("C:/Vaelor"))

    def test_missing_requested_workspace_falls_back_to_active(self):
        active = Path("C:/Active")
        def resolve(value):
            if str(value) == "missing":
                raise FileNotFoundError(value)
            return active
        with patch("core.project_context.resolve_workspace", side_effect=resolve):
            self.assertEqual(resolve_execution_workspace("missing", str(active)), active)

    def test_stale_linux_path_on_windows_is_not_translated(self):
        active = Path("C:/Vaelor")
        with patch("core.project_context.os.name", "nt"), patch(
            "core.project_context.resolve_workspace", return_value=active
        ):
            self.assertEqual(resolve_execution_workspace("/home/lane/MythosMystics", str(active)), active)

    def test_foreign_windows_path_on_posix_is_not_translated(self):
        active = Path("/workspace/vaelor")
        with patch("core.project_context.os.name", "posix"), patch(
            "core.project_context.resolve_workspace", return_value=active
        ):
            self.assertEqual(resolve_execution_workspace(r"C:\Users\old\project", str(active)), active)


if __name__ == "__main__":
    unittest.main()
