import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core.project_context import resolve_execution_workspace

_IS_NT = os.name == "nt"

# Same logical directories spelled for each OS. These two tests exercise the
# *current* OS's within-OS resolution rules (requested wins; a missing
# requested workspace falls back to active). Cross-OS rejection of stale
# paths is asserted separately by test_stale_linux_path_on_windows_* and
# test_foreign_windows_path_on_posix_* below, which is why the inputs here
# must belong to the running OS.
_REQ_WIN, _REQ_POSIX = r"C:\Vaelor", "/home/lane/Vaelor"
_ACT_WIN, _ACT_POSIX = r"C:\Active", "/home/lane/Active"


def _requested() -> str:
    return _REQ_WIN if _IS_NT else _REQ_POSIX


def _active() -> str:
    return _ACT_WIN if _IS_NT else _ACT_POSIX


class WorkspaceResolutionTests(unittest.TestCase):
    def test_valid_requested_workspace_is_used(self):
        expected = Path(_requested())
        with patch("core.project_context.resolve_workspace",
                   return_value=expected):
            self.assertEqual(
                resolve_execution_workspace(_requested(), _active()),
                expected)

    def test_missing_requested_workspace_falls_back_to_active(self):
        active = Path(_active())

        def resolve(value):
            if str(value) == "missing":
                raise FileNotFoundError(value)
            return active

        with patch("core.project_context.resolve_workspace",
                   side_effect=resolve):
            self.assertEqual(
                resolve_execution_workspace("missing", str(active)), active)

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
