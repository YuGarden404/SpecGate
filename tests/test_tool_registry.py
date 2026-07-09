import unittest

from specgate.tool_registry import default_tool_registry, render_tool_registry_for_context


class ToolRegistryTests(unittest.TestCase):
    def test_default_registry_contains_mvp_tools(self):
        registry = default_tool_registry()

        self.assertEqual(
            set(registry),
            {"read_file", "write_file", "replace_file", "list_files", "finish"},
        )

    def test_write_tools_have_write_permission(self):
        registry = default_tool_registry()

        self.assertEqual(registry["write_file"].permission, "write")
        self.assertEqual(registry["replace_file"].permission, "write")
        self.assertIn("content", registry["write_file"].args_schema)

    def test_render_tool_registry_for_context(self):
        rendered = render_tool_registry_for_context()

        self.assertIn("write_file [write]", rendered)
        self.assertIn("finish [control]", rendered)
        self.assertIn("args: path, content", rendered)


if __name__ == "__main__":
    unittest.main()
