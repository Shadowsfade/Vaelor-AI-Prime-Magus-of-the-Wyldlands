import tempfile
import unittest
from pathlib import Path
import sys
import subprocess
from unittest.mock import patch, Mock
from core.approval_policy import ApprovalPolicy, AutoApproveMode, ActionClass

from core.software_workflow import (
    SoftwareEnvironment, SoftwarePlan, SoftwareRequest, SoftwareSource,
    run_software_workflow, select_platform_adapter, verify_executable,
)
from core.task_store import TaskStore


class FakePlatformAdapter:
    def __init__(self, home):
        self.home = home

    def detect_environment(self):
        return SoftwareEnvironment("FakeOS", "fake", "x86_64", home=self.home)

    def canonicalize_program(self, request):
        return SoftwareRequest(request, "fake-tool", "fake-tool")

    def resolve_source(self, request):
        return SoftwareSource("fake_repository", package=request.canonical_name, repository="fake")

    def create_install_plan(self, request, source, work_dir):
        return SoftwarePlan(["install"], ["fake setup fake-tool"], "create fake executable", "none", ["--version"])

    def execute_install(self, request, source, plan, work_dir):
        target = work_dir / "fake-tool"
        target.write_text("fake")
        return {"returncode": 0, "output": "installed", "commands": [{"command": plan.commands[0], "returncode": 0, "output": "installed"}]}

    def find_executable(self, request, source):
        return sys.executable

    def verification_candidates(self, request):
        return ["--version"]

    def usage_instructions(self, request, executable):
        return "Launch: fake-tool"

    def update_instructions(self, source): return "update fake"
    def removal_instructions(self, source): return "remove fake"


class SoftwareWorkflowArchitectureTests(unittest.TestCase):
    def test_unsupported_platform_is_not_selected(self):
        env = SoftwareEnvironment("UnsupportedOS", "unsupported", "AMD64")
        self.assertIsNone(select_platform_adapter(env))

    def test_fake_adapter_completes_without_cachyos_import(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.create("Install fake tool")
            task = store.claim(task["id"], "test-owner")
            result = run_software_workflow(task, store, FakePlatformAdapter(root), policy=ApprovalPolicy(AutoApproveMode.TRUSTED_WORKSPACE), owner="test-owner")
            saved = store.get(task["id"])
            self.assertIn("SUCCESS", result)
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["workflow"]["source"]["repository"], "fake")

    def test_verification_is_bounded(self):
        calls = []
        def runner(command, timeout):
            calls.append(command)
            return 1, "no"
        result, attempts = verify_executable(sys.executable, ["--version", "-V", "version", "--help", "-h", "extra"], runner)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(attempts), 6)
        self.assertTrue(all(len(c) == 2 for c in calls))

    def test_missing_policy_waits_without_creating_work_directory(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install fake tool")["id"], "owner")
            adapter = FakePlatformAdapter(root)
            adapter.execute_install = Mock(side_effect=AssertionError("must not mutate"))
            result = run_software_workflow(task, store, adapter, owner="owner")
            self.assertIn("WAITING_APPROVAL", result)
            self.assertFalse((Path(root) / ".local").exists())

    def test_resume_preserves_plan_and_skips_successful_install(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install fake tool")["id"], "owner")
            adapter = FakePlatformAdapter(root)
            run_software_workflow(task, store, adapter, owner="owner")
            original = store.get(task["id"])["workflow"]
            store.resume_waiting(task["id"])
            task = store.claim(task["id"], "owner")
            step = store.begin_step(task["id"], "owner", "software_workflow", "install")
            store.finish_step(task["id"], "owner", step["id"], "succeeded")
            adapter.resolve_source = Mock(side_effect=AssertionError("must preserve source"))
            adapter.create_install_plan = Mock(side_effect=AssertionError("must preserve plan"))
            adapter.execute_install = Mock(side_effect=AssertionError("must not reinstall"))
            result = run_software_workflow(task, store, adapter, owner="owner")
            self.assertIn("SUCCESS", result)
            current = store.get(task["id"])["workflow"]
            self.assertEqual(current["source"], original["source"])
            self.assertEqual(current["plan"], original["plan"])

    def test_failed_mutation_does_not_retry_on_resume(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install fake tool")["id"], "owner")
            adapter = FakePlatformAdapter(root)
            adapter.execute_install = Mock(side_effect=subprocess.TimeoutExpired("install", 120))
            policy = ApprovalPolicy(AutoApproveMode.TRUSTED_WORKSPACE)
            self.assertIn("BLOCKED", run_software_workflow(task, store, adapter, policy, "owner"))
            store.resume_waiting(task["id"])
            task = store.claim(task["id"], "owner")
            self.assertIn("BLOCKED", run_software_workflow(task, store, adapter, policy, "owner"))
            self.assertEqual(adapter.execute_install.call_count, 1)

    def test_probe_timeout_is_recorded_and_next_probe_runs(self):
        runner = Mock(side_effect=[subprocess.TimeoutExpired("probe", 10), (0, "version 1")])
        verification, attempts = verify_executable(sys.executable, ["--version", "-V"], runner)
        self.assertEqual(verification.status, "passed")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["returncode"], -1)

    def test_cachyos_sudo_preflight_waits(self):
        from core.software_platforms.cachyos import CachyOSAdapter
        with patch("core.software_platforms.cachyos.run_command", return_value=(1, "password required")) as run:
            reason = CachyOSAdapter().preflight(SoftwarePlan(required_privilege="sudo"))
        self.assertIn("sudo authentication", reason)
        run.assert_called_once_with(["sudo", "-n", "-v"], 5)

    def test_slice8_waiting_plan_is_migrated_without_rediscovery(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install tree on CachyOS")["id"], "owner")
            command = "sudo -n pacman -S --needed --noconfirm tree"
            old = {"name": "cachyos_application_setup", "program": "tree", "package": "tree",
                   "method": "pacman", "source": "official repository", "source_reason": "saved reason",
                   "work_dir": str(Path(root) / "managed"), "plan": {"commands": [command]},
                   "environment": {"os": "CachyOS", "distribution": "cachyos", "architecture": "x86_64", "home": root}}
            store.update_workflow(task["id"], old, "saved")
            adapter = FakePlatformAdapter(root)
            adapter.resolve_source = Mock(side_effect=AssertionError("must not rediscover"))
            result = run_software_workflow(task, store, adapter, owner="owner")
            self.assertIn("WAITING_APPROVAL", result)
            saved = store.get(task["id"])["workflow"]
            self.assertEqual(saved["plan"]["commands"], [command])
            self.assertEqual(saved["legacy_plan"], old["plan"])
            self.assertEqual(saved["source"]["reason"], "saved reason")

    def test_download_verifies_recorded_artifact_not_path_lookup(self):
        with tempfile.TemporaryDirectory() as root:
            store = TaskStore(Path(root) / "tasks.json")
            task = store.claim(store.create("Install fake tool")["id"], "owner")
            adapter = FakePlatformAdapter(root)
            run_software_workflow(task, store, adapter, owner="owner")
            workflow = store.get(task["id"])["workflow"]
            workflow["artifacts"] = [{"destination": sys.executable}]
            store.update_workflow(task["id"], workflow, "artifact_saved")
            store.resume_waiting(task["id"])
            task = store.claim(task["id"], "owner")
            step = store.begin_step(task["id"], "owner", "software_workflow", "download")
            store.finish_step(task["id"], "owner", step["id"], "succeeded")
            adapter.find_executable = Mock(return_value="missing-executable")
            self.assertIn("SUCCESS", run_software_workflow(task, store, adapter, owner="owner"))
            self.assertEqual(store.get(task["id"])["workflow"]["verification"][-1]["executable"], sys.executable)

    def test_ripgrep_uses_package_name_separate_from_executable(self):
        from core.software_platforms.cachyos import CachyOSAdapter
        adapter = CachyOSAdapter()
        request = adapter.canonicalize_program("Install ripgrep on CachyOS")
        with patch("core.software_platforms.cachyos.shutil.which", side_effect=lambda name: "/usr/bin/pacman" if name == "pacman" else None), patch.object(adapter, "_package_query", return_value=(0, "ripgrep")) as query:
            source = adapter.resolve_source(request)
        query.assert_called_once_with("pacman", "ripgrep")
        self.assertEqual(source.package, "ripgrep")
        self.assertEqual(request.canonical_name, "rg")


if __name__ == "__main__": unittest.main()
