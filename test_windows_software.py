import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from core.software_platforms.windows import WindowsAdapter, JQ_SHA256
from core.software_workflow import SoftwareEnvironment, select_platform_adapter, run_software_workflow
from core.task_store import TaskStore


class WindowsSoftwareTests(unittest.TestCase):
    def test_adapter_selection(self):
        self.assertIsInstance(select_platform_adapter(SoftwareEnvironment("Windows", "windows", "AMD64")), WindowsAdapter)

    def test_known_alias_and_unknown_block(self):
        adapter = WindowsAdapter()
        self.assertEqual(adapter.canonicalize_program("install rg on Windows").canonical_name, "ripgrep")
        with self.assertRaises(ValueError):
            adapter.canonicalize_program("install something on Windows")

    def test_version_and_user_scope_are_preserved(self):
        adapter = WindowsAdapter()
        request = adapter.canonicalize_program("install git on Windows")
        with patch.object(adapter, "find_executable", return_value=None), patch("core.software_platforms.windows.shutil.which", return_value="winget.exe"), patch("core.software_platforms.windows.run_command", return_value=(0, "Found Git [Git.Git]\nVersion: 2.49.0\n")) as run:
            source = adapter.resolve_source(request)
            plan = adapter.create_install_plan(request, source, Path("work"))
            self.assertIn("--version 2.49.0", plan.commands[0])
            self.assertIn("--scope user", plan.commands[0])
            self.assertNotIn("--ignore-security-hash", plan.commands[0])
            self.assertEqual(run.call_count, 1)

    def test_jq_fallback_pins_windows_binary(self):
        adapter = WindowsAdapter()
        with patch.object(adapter, "find_executable", return_value=None), patch("core.software_platforms.windows.shutil.which", return_value=None), patch("core.software_platforms.windows.platform.machine", return_value="AMD64"):
            source = adapter.resolve_source(adapter.canonicalize_program("install jq"))
        self.assertEqual(source.checksum_sha256, JQ_SHA256)
        self.assertTrue(source.url.endswith("jq-windows-amd64.exe"))

    def test_windows_plan_waits_for_existing_approval_ui(self):
        adapter = WindowsAdapter()
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install git on Windows")["id"], "owner")
            with patch.object(adapter, "detect_environment", return_value=SoftwareEnvironment("Windows", "windows", "AMD64", home=root)), patch.object(adapter, "find_executable", return_value=None), patch("core.software_platforms.windows.shutil.which", return_value="winget.exe"), patch("core.software_platforms.windows.run_command", return_value=(0, "Found Git [Git.Git]\nVersion: 2.49.0\n")) as run:
                result = run_software_workflow(task, store, adapter, owner="owner")
            self.assertIn("WAITING_APPROVAL", result)
            pending = store.get(task["id"])["pending_approval"]
            self.assertIn("--scope user", pending["arguments"]["plan"]["commands"][0])
            self.assertEqual(run.call_count, 1)  # source lookup only

    def test_plain_windows_install_routes_deterministically(self):
        from core.cachyos_workflow import is_software_request
        with patch("core.cachyos_workflow.platform.system", return_value="Windows"):
            self.assertTrue(is_software_request("install jq"))
            self.assertFalse(is_software_request("install dependencies for my project"))
