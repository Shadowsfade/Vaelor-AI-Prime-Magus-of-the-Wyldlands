import unittest

from core.tools.registry import ToolRegistry


class ToolRegistrySchemaTests(unittest.TestCase):
    def test_persistent_terminal_tools_are_registered(self):
        from core.tools.registry import registry
        for name in ("terminal_start", "terminal_list", "terminal_run", "terminal_interrupt", "terminal_close"):
            self.assertIsNotNone(registry.get(name), name)

    def test_codebase_search_is_registered_read_only(self):
        from core.tools.registry import registry
        tool = registry.get("search_codebase")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.read_only)

    def setUp(self):
        self.registry = ToolRegistry()

        def sample(path, depth: int = 1):
            return path, depth

        self.registry.register("sample", "sample tool", True, sample)

    def test_schema_marks_required_and_optional_arguments(self):
        schema = self.registry.list_tools()[0]["arguments"]["parameters"]
        self.assertTrue(schema["path"]["required"])
        self.assertFalse(schema["depth"]["required"])
        self.assertEqual(schema["depth"]["type"], "int")

    def test_validation_rejects_unknown_arguments(self):
        error = self.registry.validate_call("sample", {"path": ".", "surprise": True})
        self.assertIn("unexpected argument", error)

    def test_validation_rejects_missing_required_arguments(self):
        error = self.registry.validate_call("sample", {"depth": 2})
        self.assertIn("missing required argument", error)

    def test_accepts_argument_uses_callable_signature(self):
        self.assertTrue(self.registry.accepts_argument("sample", "depth"))
        self.assertFalse(self.registry.accepts_argument("sample", "confirm"))

    def test_risk_is_exposed_and_inferred(self):
        listed = self.registry.list_tools()[0]
        self.assertEqual(listed["risk"], "read")
        self.registry.register("danger", "danger", False, lambda: None, risk="high")
        self.assertEqual(self.registry.get("danger").risk, "high")
        self.assertIn("risk=high", self.registry.specs_for_prompt())


if __name__ == "__main__":
    unittest.main()
