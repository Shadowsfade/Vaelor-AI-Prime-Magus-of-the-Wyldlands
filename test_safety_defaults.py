import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.tools import fs_ops, shell_exec
from core.tools.registry import registry


class SafetyDefaultTests(unittest.TestCase):
    def test_missing_autonomy_policy_fails_closed(self):
        with patch.object(shell_exec, "CONFIG_PATH", "definitely-missing-autonomy.json"):
            cfg = shell_exec.load_autonomy()
        self.assertEqual(cfg["mode"], "supervised")
        self.assertFalse(cfg["auto_confirm_mutations"])
        self.assertFalse(cfg["allow_installs"])

    def test_invalid_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "autonomy.json"
            path.write_text(json.dumps({"mode": "anything", "auto_confirm_mutations": True}))
            with patch.object(shell_exec, "CONFIG_PATH", str(path)):
                cfg = shell_exec.load_autonomy()
        self.assertEqual(cfg["mode"], "supervised")
        self.assertFalse(cfg["auto_confirm_mutations"])

    def test_shell_mutation_requires_confirmation_by_default(self):
        with (
            patch.object(shell_exec, "CONFIG_PATH", "definitely-missing-autonomy.json"),
            patch("core.tools.shell_exec.subprocess.run") as run,
        ):
            result = shell_exec.shell_exec("Set-Content sample.txt hello")
        self.assertIn("needs confirm=yes", result)
        run.assert_not_called()

    def test_file_mutations_require_confirmation_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "sample.txt"
            with patch.object(fs_ops, "PROJECT_ROOT", temp):
                result = fs_ops.write_text_file(str(target), "hello")
        self.assertIn("needs confirm=yes", result)
        self.assertFalse(target.exists())

    def test_proposal_approval_requires_confirmation(self):
        tool = registry.get("approve_change")
        self.assertIsNotNone(tool)
        self.assertIn("needs confirm=yes", tool.run(proposal_id="abc"))


if __name__ == "__main__":
    unittest.main()
