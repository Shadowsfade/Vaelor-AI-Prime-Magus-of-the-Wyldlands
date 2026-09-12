import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.verified_download import download_verified, verify_file


class Response(io.BytesIO):
    def geturl(self):
        return "https://example.com/release"


class VerifiedDownloadTests(unittest.TestCase):
    def test_verified_bytes_publish_with_recorded_digest(self):
        data = b"official artifact"
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "tool"
            with patch("core.verified_download.urllib.request.urlopen", return_value=Response(data)):
                self.assertEqual(download_verified("https://example.com/release", target, digest), (len(data), digest))
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(list(Path(root).iterdir()), [target])

    def test_mismatch_preserves_previous_target_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "tool"
            target.write_bytes(b"previous")
            with patch("core.verified_download.urllib.request.urlopen", return_value=Response(b"tampered")):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    download_verified("https://example.com/release", target, "0" * 64)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertEqual(list(Path(root).iterdir()), [target])

    def test_missing_pin_rejected_before_network(self):
        with patch("core.verified_download.urllib.request.urlopen") as fetch:
            with self.assertRaises(ValueError):
                download_verified("https://example.com/release", Path("unused"), "")
        fetch.assert_not_called()

    def test_size_limit_removes_partial(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("core.verified_download.MAX_BYTES", 3), patch("core.verified_download.urllib.request.urlopen", return_value=Response(b"too big")):
                with self.assertRaisesRegex(ValueError, "limit"):
                    download_verified("https://example.com/release", Path(root) / "tool", "0" * 64)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_revalidation_detects_changed_file(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "tool"
            target.write_bytes(b"original")
            digest = hashlib.sha256(b"original").hexdigest()
            verify_file(target, digest)
            target.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_file(target, digest)

    def test_network_error_cleans_partial(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("core.verified_download.urllib.request.urlopen", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    download_verified("https://example.com/release", Path(root) / "tool", "0" * 64)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_resumed_tampered_artifact_never_reaches_execution_probe(self):
        from core.task_store import TaskStore
        from core.software_workflow import SoftwareSource, run_software_workflow
        from test_software_workflow import FakePlatformAdapter
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install tool")["id"], "owner")
            adapter = FakePlatformAdapter(root)
            source = SoftwareSource("official_upstream_artifact", package="tool",
                checksum_sha256=hashlib.sha256(b"original").hexdigest())
            with patch.object(adapter, "resolve_source", return_value=source):
                run_software_workflow(task, store, adapter, owner="owner")
            target = Path(root) / "tool"
            target.write_bytes(b"tampered")
            saved = store.get(task["id"])["workflow"]
            saved["artifacts"] = [{"destination": str(target)}]
            store.update_workflow(task["id"], saved)
            store.resume_waiting(task["id"])
            task = store.claim(task["id"], "owner")
            step = store.begin_step(task["id"], "owner", "software_workflow", "download")
            store.finish_step(task["id"], "owner", step["id"], "succeeded")
            with patch("core.software_workflow.verify_executable", side_effect=AssertionError("must not execute")) as probe:
                result = run_software_workflow(task, store, adapter, owner="owner")
            self.assertIn("SHA-256 mismatch", result)
            self.assertEqual(store.get(task["id"])["status"], "failed")
            probe.assert_not_called()
