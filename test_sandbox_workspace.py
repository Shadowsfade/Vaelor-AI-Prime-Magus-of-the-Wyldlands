import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.sandbox_workspace import (
    create_validation_sandbox, discard_validation_sandbox,
    list_validation_sandboxes, review_validation_sandbox,
    record_sandbox_validation, promote_validation_sandbox,
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

    def test_reviews_sandbox_by_managed_id(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        target = Path(sandbox["path"]) / "baseline.txt"
        target.write_text("review this\n", encoding="utf-8")
        review = review_validation_sandbox(sandbox["id"])
        self.assertIn(f"Validation sandbox {sandbox['id']}", review)
        self.assertIn("baseline.txt", review)
        self.assertIn("review this", review)

    def commit_sandbox_change(self, sandbox, value="validated"):
        isolated = Path(sandbox["path"])
        (isolated / "baseline.txt").write_text(value + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "baseline.txt"], cwd=isolated, check=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "sandbox change",
        ], cwd=isolated, check=True)
        return isolated

    def passing_checks(self):
        return [{"name": "tests", "status": "passed", "evidence": "exit 0"}]

    def test_promotes_only_exact_committed_validated_head(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        self.commit_sandbox_change(sandbox)
        record_sandbox_validation(sandbox["id"], self.passing_checks())
        result = promote_validation_sandbox(sandbox["id"], confirm="yes")
        self.assertEqual(result["state"], "promoted")
        self.assertEqual((self.repo / "baseline.txt").read_text(encoding="utf-8"), "validated\n")

    def test_rejects_stale_validation_after_new_commit(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        isolated = self.commit_sandbox_change(sandbox, "first")
        record_sandbox_validation(sandbox["id"], self.passing_checks())
        (isolated / "later.txt").write_text("later\n", encoding="utf-8")
        subprocess.run(["git", "add", "later.txt"], cwd=isolated, check=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "later",
        ], cwd=isolated, check=True)
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            promote_validation_sandbox(sandbox["id"], confirm="yes")

    def test_rejects_failed_evidence(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        self.commit_sandbox_change(sandbox)
        record_sandbox_validation(sandbox["id"], [
            {"name": "tests", "status": "failed", "evidence": "exit 1"}
        ])
        with self.assertRaisesRegex(PermissionError, "evidence gate"):
            promote_validation_sandbox(sandbox["id"], confirm="yes")

    def test_rejects_source_drift_after_sandbox_creation(self):
        sandbox = create_validation_sandbox(str(self.repo), confirm="yes")
        self.commit_sandbox_change(sandbox)
        record_sandbox_validation(sandbox["id"], self.passing_checks())
        (self.repo / "source-only.txt").write_text("source drift\n", encoding="utf-8")
        subprocess.run(["git", "add", "source-only.txt"], cwd=self.repo, check=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "source drift",
        ], cwd=self.repo, check=True)
        with self.assertRaisesRegex(ValueError, "source repository changed"):
            promote_validation_sandbox(sandbox["id"], confirm="yes")


if __name__ == "__main__":
    unittest.main()
