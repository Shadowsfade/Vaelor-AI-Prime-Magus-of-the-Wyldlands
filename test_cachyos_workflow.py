import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.approval_policy import ApprovalPolicy, AutoApproveMode
from core.brain import VaelorBrain
from core.cachyos_workflow import extract_program, resolve_source, run_cachyos_workflow
from core.task_store import TaskStore

class CachyOSWorkflowTests(unittest.TestCase):
    def _task(self, store, request): return store.claim(store.create(request)["id"], "test-owner")
    def _env(self, root): return {"os":"CachyOS","distribution":"cachyos","architecture":"x86_64","shell":"/bin/bash","package_managers":["pacman"],"user":"test","home":root}
    def test_program_extraction_is_generic_and_safe(self):
        self.assertEqual(extract_program("Install ripgrep on CachyOS."), "rg"); self.assertEqual(extract_program("set up btop on Linux"), "btop")
        with self.assertRaises(ValueError): extract_program("make the computer faster")
    def test_resolution_order_installed_then_pacman_then_aur_then_upstream(self):
        with patch("core.cachyos_workflow.shutil.which", side_effect=lambda n:"/usr/bin/"+n if n=="btop" else None), patch("core.cachyos_workflow._run", return_value=(0,"btop 1")): self.assertEqual(resolve_source("btop")["method"],"already_installed")
        with patch("core.cachyos_workflow.shutil.which", side_effect=lambda n:"/usr/bin/pacman" if n=="pacman" else None), patch("core.cachyos_workflow._package_query", return_value=(0,"Name : tree")): self.assertEqual(resolve_source("tree")["method"],"pacman")
        with patch("core.cachyos_workflow.shutil.which", side_effect=lambda n:"/usr/bin/paru" if n=="paru" else None), patch("core.cachyos_workflow._package_query", return_value=(0,"Name : aurpkg")): self.assertEqual(resolve_source("aurpkg")["method"],"aur")
        with patch("core.cachyos_workflow.shutil.which", return_value=None): self.assertEqual(resolve_source("jq")["method"],"official_binary")
    def test_installed_program_verifies_without_reinstall(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Download btop and tell me how to use it on CachyOS."); executable=Path(root)/"btop"; executable.write_text("test")
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value={"method":"already_installed","source":"local","executable":str(executable)}),patch("core.cachyos_workflow._run",return_value=(0,"btop 1.0")): result=run_cachyos_workflow(task,store,ApprovalPolicy(AutoApproveMode.TRUSTED_WORKSPACE),"test-owner")
            self.assertTrue(result.startswith("FINAL_SUMMARY: SUCCESS")); self.assertEqual(store.get(task["id"])["status"],"completed"); self.assertEqual(store.get(task["id"])["workflow"]["method"],"already_installed")
    def test_pacman_path_waits_for_sudo_without_hanging(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Install tree on CachyOS and show me how to use it.")
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value={"method":"pacman","source":"official repository","package":"tree"}),patch("core.cachyos_workflow._run",return_value=(1,"sudo: a password is required")),patch("core.cachyos_workflow._authorize",return_value=(True,"")): result=run_cachyos_workflow(task,store,None,"test-owner")
            self.assertIn("WAITING_USER",result); self.assertEqual(store.get(task["id"])["status"],"waiting")
    def test_waiting_package_task_resumes_same_task_and_plan(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Install tree on CachyOS and show me how to use it.")
            source={"method":"pacman","source":"official repository","package":"tree"}
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value=source),patch("core.cachyos_workflow._authorize",return_value=(False,"REQUIRE_USER: install approval")):
                result=run_cachyos_workflow(task,store,None,"test-owner")
            waiting=store.get(task["id"]); self.assertIn("WAITING_APPROVAL",result); self.assertEqual(waiting["workflow"]["method"],"pacman"); self.assertTrue(waiting["workflow"]["plan"]["commands"])
            task=store.resume_waiting(task["id"]); task=store.claim(task["id"],"test-owner") or store.get(task["id"])
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value=source),patch("core.cachyos_workflow._run",side_effect=[(0,"sudo ok"),(0,"installed"),(0,"tree 1")]),patch("core.cachyos_workflow.shutil.which",return_value="/usr/bin/tree"),patch("core.cachyos_workflow._authorize",return_value=(True,"")):
                result=run_cachyos_workflow(task,store,None,"test-owner")
            resumed=store.get(task["id"]); self.assertTrue(result.startswith("FINAL_SUMMARY: SUCCESS")); self.assertEqual(resumed["id"],task["id"]); self.assertEqual(resumed["status"],"completed"); self.assertEqual(resumed["workflow"]["method"],"pacman")
    def test_verification_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Install btop on CachyOS."); executable=Path(root)/"btop"; executable.write_text("x")
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value={"method":"already_installed","source":"local","executable":str(executable)}),patch("core.cachyos_workflow._run",return_value=(1,"failed")): result=run_cachyos_workflow(task,store,None,"test-owner")
            self.assertIn("FAILED",result); self.assertEqual(store.get(task["id"])["status"],"failed")
    def test_unsupported_program_is_blocked_without_guessing(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Install mystery-tool on CachyOS.")
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",side_effect=ValueError("No trusted source")): result=run_cachyos_workflow(task,store,None,"test-owner")
            self.assertIn("BLOCKED",result); self.assertEqual(store.get(task["id"])["status"],"waiting")
    def test_off_policy_stops_before_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            store=TaskStore(Path(root)/"tasks.json"); task=self._task(store,"Download jq and set it up on CachyOS.")
            with patch("core.cachyos_workflow.detect_environment",return_value=self._env(root)),patch("core.cachyos_workflow.resolve_source",return_value={"method":"official_binary","url":"https://example.invalid/jq"}): result=run_cachyos_workflow(task,store,ApprovalPolicy(AutoApproveMode.OFF),"test-owner")
            self.assertTrue(result.startswith("FINAL_SUMMARY: WAITING_APPROVAL")); self.assertEqual(store.get(task["id"])["recovery"]["decision"],"WAIT_FOR_APPROVAL")
    def test_brain_prepare_uses_deterministic_contract(self):
        with tempfile.TemporaryDirectory() as root:
            brain=object.__new__(VaelorBrain); brain.tasks=TaskStore(Path(root)/"tasks.json")
            with patch.object(brain,"understand_task",side_effect=AssertionError("model should not classify routine workflow")): task=brain.prepare_task("Download btop, open it, and tell me how to use it on CachyOS.")
            self.assertEqual(task["contract"]["source"],"deterministic_cachyos_workflow")
if __name__=="__main__": unittest.main()
