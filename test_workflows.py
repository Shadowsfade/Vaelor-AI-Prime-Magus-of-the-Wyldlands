import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.workflows import list_project_workflows, read_project_workflow


class ProjectWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "apps" / "tome"
        self.workspace.mkdir(parents=True)
        self.patches = [
            patch("core.workflows.resolve_workspace", side_effect=lambda path: Path(path).resolve()),
            patch("core.workflows._git_root", return_value=self.root),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def write_workflow(self, directory, name, steps, **extra):
        target = Path(directory) / ".vaelor" / "workflows"
        target.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "description": extra.pop("description", "demo"), "steps": steps, **extra}
        (target / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_lists_and_reads_valid_registered_tool_steps(self):
        self.write_workflow(self.root, "inspect", [
            {"tool": "git_status", "arguments": {"path": "${workspace}"}}
        ], inputs={"target": "Path to inspect"})
        listed = json.loads(list_project_workflows(str(self.workspace)))
        self.assertEqual(listed["workflows"][0]["name"], "inspect")
        workflow = json.loads(read_project_workflow(str(self.workspace), "inspect"))
        self.assertEqual(workflow["steps"][0]["risk"], "read")
        self.assertIn("normal agent action", workflow["policy"])
        self.assertIn("recalculated", workflow["policy"])

    def test_deeper_workflow_overrides_root_by_name(self):
        self.write_workflow(self.root, "check", [{"tool": "git_branch", "arguments": {"path": str(self.root)}}])
        self.write_workflow(self.workspace, "check", [{"tool": "git_log", "arguments": {"path": str(self.root)}}])
        workflow = json.loads(read_project_workflow(str(self.workspace), "check"))
        self.assertEqual(workflow["steps"][0]["tool"], "git_log")
        self.assertTrue(workflow["source"].startswith("apps/tome/"))

    def test_rejects_unknown_tools_and_bad_arguments(self):
        self.write_workflow(self.root, "bad-tool", [{"tool": "not_registered", "arguments": {}}])
        with self.assertRaisesRegex(ValueError, "unknown or recursive"):
            read_project_workflow(str(self.workspace), "bad-tool")
        self.write_workflow(self.root, "bad-args", [{"tool": "git_status", "arguments": {"surprise": True}}])
        with self.assertRaisesRegex(ValueError, "unexpected argument"):
            read_project_workflow(str(self.workspace), "bad-args")

    def test_mutating_steps_expose_highest_risk_without_executing(self):
        self.write_workflow(self.root, "publish", [{"tool": "git_push", "arguments": {"repo": str(self.root)}}])
        workflow = json.loads(read_project_workflow(str(self.workspace), "publish"))
        self.assertEqual(workflow["highest_risk"], "high")
        self.assertEqual(workflow["steps"][0]["risk"], "high")

    def test_rejects_undeclared_placeholders(self):
        self.write_workflow(self.root, "unknown-input", [
            {"tool": "git_status", "arguments": {"path": "${missing}"}}
        ])
        with self.assertRaisesRegex(ValueError, "undeclared input.*missing"):
            read_project_workflow(str(self.workspace), "unknown-input")

    def test_discovery_is_globally_bounded(self):
        for index in range(55):
            self.write_workflow(self.root, f"flow-{index}", [
                {"tool": "git_status", "arguments": {"path": "${workspace}"}}
            ])
        listed = json.loads(list_project_workflows(str(self.workspace)))
        self.assertEqual(len(listed["workflows"]), 50)


if __name__ == "__main__":
    unittest.main()
