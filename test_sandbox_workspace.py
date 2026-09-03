import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.sandbox_workspace import (
    create_validation_sandbox, discard_validation_sandbox,
    list_validation_sandboxes,
)


class SandboxWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "baseline.txt").write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "add", "baseline.txt"], cwd=self.repo, check=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "baseline",
        ], cwd=self.repo, check=True)
        self.root_patch = patch("core.sandbox_workspace.SANDBOX_ROOT", self.root / "managed")
        self.resolve_patch = patch("core.sandbox_workspace._resolve_path", side_effect=lambda value, must_exist=False: str(Path(value).resolve()))
        self.mode_patch = patch("core.sandbox_workspace._auto_ok", return_value=True)
        self.root_patch.start(); self.resolve_patch.start(); self.mode_patch.start()

    def tearDown(self):
        for item in list_validation_sandboxes():
            if item.get("exists"):
                discard_validation_sandbox(item["id"], confirm="yes")
        self.mode_patch.stop(); self.resolve_patch.stop(); self.root_patch.stop()
        self.temp.cleanup()

    def test_creates_isolated_committed_worktree(self):
        (self.repo / "uncommitted.txt").write_text("private draft", encoding="utf-8")
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        isolated = Path(sandbox["path"])
        self.assertEqual((isolated / "baseline.txt").read_text(encoding="utf-8"), "committed\n")
        self.assertFalse((isolated / "uncommitted.txt").exists())
        (isolated / "baseline.txt").write_text("sandbox only\n", encoding="utf-8")
        self.assertEqual((self.repo / "baseline.txt").read_text(encoding="utf-8"), "committed\n")

    def test_lists_and_discards_only_managed_id(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        self.assertEqual(list_validation_sandboxes()[0]["id"], sandbox["id"])
        result = discard_validation_sandbox(sandbox["id"], confirm="yes")
        self.assertEqual(result["state"], "discarded")
        self.assertFalse(Path(sandbox["path"]).exists())
        self.assertEqual(list_validation_sandboxes(), [])

    def test_rejects_arbitrary_identifier(self):
        with self.assertRaises(ValueError):
            discard_validation_sandbox("../../repo", confirm="yes")


if __name__ == "__main__":
    unittest.main()
