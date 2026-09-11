import json
import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core.governance import (
    _reset_runtime_authorizations_for_tests, claim_runtime_authorization,
    issue_authorization,
)
from core.verification import VerificationStatus, build_requirement, verify_requirement


class GovernedVerificationTests(unittest.TestCase):
    def setUp(self):
        _reset_runtime_authorizations_for_tests()

    def tearDown(self):
        _reset_runtime_authorizations_for_tests()

    def _auth(self, expires=None):
        now = datetime.now(timezone.utc)
        return issue_authorization("fp", "test", now.isoformat(), expires or (now + timedelta(minutes=2)).isoformat())

    def _init_git(self, tmp):
        subprocess.run(["git", "init", "-q", tmp], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
        Path(tmp, "a").write_text("a")
        subprocess.run(["git", "-C", tmp, "add", "a"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", "initial"], check=True)

    def test_capability_expires_and_cannot_dispatch(self):
        now = datetime.now(timezone.utc)
        auth = issue_authorization("fp", "test", (now - timedelta(minutes=2)).isoformat(), (now - timedelta(seconds=1)).isoformat())
        self.assertFalse(claim_runtime_authorization(auth, "fp"))

    def test_malformed_expiration_fails_closed(self):
        with self.assertRaises(ValueError):
            issue_authorization("fp", "test", "opaque", "not-a-timestamp")

    def test_expiration_without_timezone_fails_closed(self):
        with self.assertRaises(ValueError):
            issue_authorization("fp", "test", "opaque", "2030-01-01T00:00:00")

    def test_expired_entries_pruned_individually_and_live_entries_remain(self):
        now = datetime.now(timezone.utc)
        expired = issue_authorization("old", "test", "opaque", (now - timedelta(seconds=1)).isoformat())
        live = issue_authorization("live", "test", "opaque", (now + timedelta(minutes=2)).isoformat())
        fresh = issue_authorization("fresh", "test", "opaque", (now + timedelta(minutes=2)).isoformat())
        self.assertFalse(claim_runtime_authorization(expired, "old"))
        self.assertTrue(claim_runtime_authorization(live, "live"))
        self.assertTrue(claim_runtime_authorization(fresh, "fresh"))

    def test_capacity_exhaustion_fails_closed(self):
        import core.governance as governance
        with patch.object(governance, "_MAX_ISSUED", 1):
            self._auth()
            with self.assertRaises(RuntimeError):
                self._auth()

    def test_concurrent_capability_claim_dispatches_once(self):
        auth = self._auth()
        results = []
        threads = [threading.Thread(target=lambda: results.append(claim_runtime_authorization(auth, "fp"))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(results.count(True), 1)

    def test_executor_exception_cannot_permit_replay(self):
        auth = self._auth()
        self.assertTrue(claim_runtime_authorization(auth, "fp"))
        self.assertFalse(claim_runtime_authorization(auth, "fp"))

    def test_file_write_verification_passes_and_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "a.txt")
            req = build_requirement("write_text_file", {"path": path, "content": "hello"}, "fp", "t", "1")
            Path(path).write_text("hello")
            self.assertEqual(verify_requirement(req, "t", "1", "fp").status, VerificationStatus.PASSED)
            Path(path).write_text("wrong")
            self.assertEqual(verify_requirement(req, "t", "1", "fp").status, VerificationStatus.FAILED)

    def test_different_target_change_does_not_satisfy_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "a.txt")
            other = str(Path(tmp) / "b.txt")
            req = build_requirement("write_text_file", {"path": path, "content": "hello"}, "fp", "t", "1")
            Path(other).write_text("hello")
            record = verify_requirement(req, "t", "1", "fp")
            self.assertEqual(record.status, VerificationStatus.FAILED)

    def test_delete_directory_and_symlink_type_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            deleted = Path(tmp) / "gone"
            deleted.write_text("x")
            req = build_requirement("delete_path", {"path": str(deleted)}, "fp", "t", "1")
            deleted.unlink()
            self.assertEqual(verify_requirement(req, "t", "1", "fp").status, VerificationStatus.PASSED)
            target = Path(tmp) / "dir"
            req = build_requirement("make_dir", {"path": str(target)}, "fp2", "t", "2")
            target.mkdir()
            self.assertEqual(verify_requirement(req, "t", "2", "fp2").status, VerificationStatus.PASSED)

    def test_symlink_does_not_satisfy_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dir"
            target.mkdir()
            link = Path(tmp) / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows account lacks symlink creation privilege")
                raise
            req = build_requirement("make_dir", {"path": str(link)}, "fp3", "t", "3")
            self.assertEqual(verify_requirement(req, "t", "3", "fp3").status, VerificationStatus.FAILED)

    def test_git_add_requires_intended_staged_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
            Path(tmp, "a.txt").write_text("a")
            subprocess.run(["git", "-C", tmp, "add", "a.txt"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "initial"], check=True)
            req = build_requirement("git_add", {"repo": tmp, "path": "a.txt"}, "fp", "t", "1")
            Path(tmp, "b.txt").write_text("b")
            record = verify_requirement(req, "t", "1", "fp")
            self.assertEqual(record.status, VerificationStatus.FAILED)
            Path(tmp, "a.txt").write_text("changed")
            subprocess.run(["git", "-C", tmp, "add", "a.txt"], check=True)
            self.assertEqual(verify_requirement(req, "t", "1", "fp").status, VerificationStatus.PASSED)
            subprocess.run(["git", "-C", tmp, "checkout", "-qb", "other"], check=True)
            self.assertEqual(verify_requirement(req, "t", "1", "fp").status, VerificationStatus.FAILED)

    def test_unsupported_mutation_is_unavailable(self):
        self.assertIsNone(build_requirement("set_autonomy_mode", {"mode": "admin"}, "fp", "t", "1"))

    def test_record_binds_task_step_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "x")
            req = build_requirement("write_text_file", {"path": path, "content": "x"}, "bound", "task", "step")
            Path(path).write_text("x")
            record = verify_requirement(req, "task", "step", "bound").to_dict()
            self.assertEqual((record["task_id"], record["step_id"], record["governed_fingerprint"]), ("task", "step", "bound"))
            self.assertIn("evidence_id", record)

    def test_requirement_survives_task_store_reload(self):
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            task = store.create("write")
            requirement = build_requirement("write_text_file", {"path": str(Path(tmp) / "x"), "content": "x"}, "f", task["id"], "1")
            action = {"fingerprint": "f", "tool": "write_text_file", "arguments": {},
                      "verification_requirement": requirement.to_dict()}
            store.request_approval(task["id"], action)
            reopened = TaskStore(Path(tmp) / "tasks.json").get(task["id"])
            self.assertEqual(reopened["pending_approval"]["verification_requirement"]["requirement_id"], requirement.requirement_id)

    def test_verification_record_survives_task_store_reload(self):
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            store = TaskStore(path)
            task = store.create("verified mutation")
            record = {"task_id": task["id"], "step_id": "1", "governed_fingerprint": "f",
                      "evidence_id": "e", "verifier_identity": "local.file", "status": "passed",
                      "reason": "bounded", "fresh_observed_evidence": {"path": "/tmp/x"}}
            store.record_verification(task["id"], record)
            reopened = TaskStore(path).get(task["id"])
            events = [event for event in reopened["events"] if event["type"] == "verification_recorded"]
            self.assertEqual(events[-1]["data"]["governed_fingerprint"], "f")

    def test_protected_fields_cannot_be_model_authored(self):
        from core.agent_loop import RESERVED_GOVERNANCE_FIELDS
        self.assertIn("verifier_adapter", RESERVED_GOVERNANCE_FIELDS)

    def test_read_only_actions_need_no_verification(self):
        from core.agent_loop import run_agent
        events = []
        result = run_agent("read", lambda _: 'FINAL_SUMMARY: SUCCESS read', event_callback=lambda e, d: events.append(e))
        self.assertIn("SUCCESS", result)
        self.assertNotIn("verification_passed", events)

    def test_successful_callable_alone_emits_no_verification_passed(self):
        from core.agent_loop import run_agent
        events = []
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"), patch("core.agent_loop.registry.execute", return_value="ok"):
            run_agent("unsupported mutation", lambda _: 'ACTION: set_autonomy_mode mode=admin', require_verification=True, event_callback=lambda e, d: events.append(e))
        self.assertNotIn("verification_passed", events)

    def test_failed_verification_blocks_verified_completion(self):
        from core.agent_loop import run_agent
        replies = iter(['ACTION: write_text_file path="/tmp/vaelor-test-nope" content="x"', 'FINAL_SUMMARY: SUCCESS done', 'FINAL_SUMMARY: FAILED verification did not pass'])
        with patch("core.agent_loop.registry.specs_for_prompt", return_value="tools"), patch("core.agent_loop._autonomy_mode", return_value="admin"), patch("core.agent_loop.registry.execute", return_value="[OK]"):
            result = run_agent("write", lambda _: next(replies), max_steps=3)
        self.assertNotIn("FINAL_SUMMARY: SUCCESS", result)

    def test_requirement_has_no_model_verifier_authority(self):
        req = build_requirement("write_text_file", {"path": "/tmp/x", "content": "x", "verifier_adapter": "fake"}, "fp", "t", "s")
        self.assertNotEqual(req.verifier_adapter, "fake")

    def test_requirement_serialization_is_bounded_and_json_safe(self):
        req = build_requirement("write_text_file", {"path": "/tmp/x", "content": "x"}, "fp", "t", "s")
        encoded = json.dumps(req.to_dict())
        self.assertLess(len(encoded), 4000)

    def test_git_commit_verifies_expected_parent_and_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "Test"], check=True)
            Path(tmp, "a").write_text("a")
            subprocess.run(["git", "-C", tmp, "add", "a"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "one"], check=True)
            Path(tmp, "a").write_text("b")
            subprocess.run(["git", "-C", tmp, "add", "a"], check=True)
            req = build_requirement("git_commit", {"repo": tmp}, "fp", "t", "s")
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "two"], check=True)
            record = verify_requirement(req, "t", "s", "fp")
            self.assertEqual(record.status, VerificationStatus.PASSED)

    def test_binding_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "x")
            req = build_requirement("write_text_file", {"path": path, "content": "x"}, "bound", "task", "step")
            Path(path).write_text("x")
            for task, step, fingerprint in (("other", "step", "bound"), ("task", "other", "bound"), ("task", "step", "wrong")):
                record = verify_requirement(req, task, step, fingerprint)
                self.assertEqual(record.status, VerificationStatus.FAILED)

    def test_malformed_persisted_requirement_fails_closed(self):
        from core.verification import VerificationRequirement
        with self.assertRaises(ValueError):
            VerificationRequirement.from_dict({"requirement_id": "r", "verifier_adapter": "local.file"})

    def test_git_commit_worktree_only_change_does_not_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_git(tmp)
            Path(tmp, "a").write_text("b")
            req = build_requirement("git_commit", {"repo": tmp}, "fp", "t", "s")
            self.assertEqual(verify_requirement(req, "t", "s", "fp").status, VerificationStatus.FAILED)

    def test_checkout_requires_exact_requested_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_git(tmp)
            subprocess.run(["git", "-C", tmp, "checkout", "-qb", "other"], check=True)
            req = build_requirement("git_checkout", {"repo": tmp, "branch": "other"}, "fp", "t", "s")
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "master"], check=True)
            self.assertEqual(verify_requirement(req, "t", "s", "fp").status, VerificationStatus.FAILED)
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "other"], check=True)
            self.assertEqual(verify_requirement(req, "t", "s", "fp").status, VerificationStatus.PASSED)

    def test_push_without_observable_remote_is_unavailable_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._init_git(tmp)
            req = build_requirement("git_push", {"repo": tmp, "remote": "missing", "branch": "master"}, "fp", "t", "s")
            record = verify_requirement(req, "t", "s", "fp")
            self.assertIn(record.status, (VerificationStatus.UNAVAILABLE, VerificationStatus.FAILED))
            self.assertNotIn("password", json.dumps(record.to_dict()).lower())

    def test_approval_requirement_is_exactly_bound(self):
        from core.task_store import TaskStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            task = store.create("edit")
            requirement = build_requirement("write_text_file", {"path": "x", "content": "x"}, "a", task["id"], "1")
            action = {"fingerprint": "a", "governed_fingerprint": "a", "tool": "write_text_file", "arguments": {"path": "x", "content": "x"},
                      "task_id": task["id"], "step_id": "1", "target": "x", "scope": "", "effects": "low", "provenance_ids": [],
                      "verification_requirement": requirement.to_dict()}
            store.request_approval(task["id"], action)
            store.approve_action(task["id"], "a")
            self.assertFalse(store.consume_action_approval(task["id"], "a", invocation={"tool": "write_text_file", "arguments": {"path": "y"}}))

    def test_protected_memory_fixture_is_not_touched_by_verifier(self):
        protected = Path("memory") / "core.json"
        before = protected.read_bytes() if protected.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "x")
            req = build_requirement("write_text_file", {"path": path, "content": "x"}, "fp", "t", "s")
            Path(path).write_text("x")
            verify_requirement(req, "t", "s", "fp")
        after = protected.read_bytes() if protected.exists() else None
        self.assertEqual(before, after)

    def test_unavailable_record_is_explicit_not_passed(self):
        from core.verification import VerificationRequirement
        req = VerificationRequirement("r", "fp", "unknown", "unknown", {"x": "y"}, {}, "missing.adapter", "t", "s", {})
        record = verify_requirement(req, "t", "s", "fp")
        self.assertEqual(record.status, VerificationStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
