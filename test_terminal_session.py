from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from core.terminal_session import TerminalSessionManager


class TerminalSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = TerminalSessionManager()
        self.session = self.manager.create(self.temp.name)

    def tearDown(self):
        self.manager.close_all()
        self.temp.cleanup()

    def test_session_retains_environment_between_commands(self):
        if os.name == "nt":
            self.manager.execute(self.session["id"], "$env:VAELOR_TEST_VALUE='remembered'", confirm="yes")
            result = self.manager.execute(self.session["id"], "Write-Output $env:VAELOR_TEST_VALUE")
        else:
            self.manager.execute(self.session["id"], "export VAELOR_TEST_VALUE=remembered", confirm="yes")
            result = self.manager.execute(self.session["id"], "printf $VAELOR_TEST_VALUE")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("remembered", result["output"])

    def test_session_retains_working_directory_between_commands(self):
        child = Path(self.temp.name) / "child"
        child.mkdir()
        if os.name == "nt":
            self.manager.execute(self.session["id"], f"Set-Location '{child}'")
            result = self.manager.execute(self.session["id"], "(Get-Location).Path")
        else:
            self.manager.execute(self.session["id"], f"cd '{child}'")
            result = self.manager.execute(self.session["id"], "pwd")
        self.assertEqual(Path(result["output"]), child)

    def test_unknown_session_fails_closed(self):
        with self.assertRaises(KeyError):
            self.manager.execute("missing", "echo no")

    def test_os_wrecking_command_is_rejected_before_execution(self):
        with self.assertRaises(PermissionError):
            self.manager.execute(self.session["id"], "format C:", confirm="yes")

    def test_supervised_mutation_needs_confirmation(self):
        with patch("core.terminal_session.load_autonomy", return_value={
            "mode": "supervised", "max_timeout_seconds": 30,
        }):
            with self.assertRaises(PermissionError):
                self.manager.execute(self.session["id"], "mkdir blocked")

    def test_close_removes_session(self):
        self.manager.close(self.session["id"])
        self.assertEqual(self.manager.list(), [])


if __name__ == "__main__":
    unittest.main()
