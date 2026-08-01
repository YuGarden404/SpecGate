import unittest
from unittest import mock

from specgate.actions import Action
from specgate.tool_handlers import ToolExecutionContext, ToolExecutionError
from specgate.tool_registry import (
    PermissionClass,
    SideEffectClass,
    ToolDefinition,
    ToolMetadata,
    ToolRegistry,
    WriteFileArgs,
    WriteFileResult,
)
from specgate.tool_runtime import ToolRuntime


class ToolRuntimeTests(unittest.TestCase):
    def _runtime(self, handler: mock.Mock) -> ToolRuntime:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                metadata=ToolMetadata("write_file", "write a file"),
                permission_class=PermissionClass.WRITE,
                side_effect_class=SideEffectClass.WORKSPACE_WRITE,
                args_model=WriteFileArgs,
                result_model=WriteFileResult,
                handler=handler,
            )
        )
        return ToolRuntime(registry)

    def test_prepare_validates_args_before_handler(self):
        handler = mock.Mock()

        preparation = self._runtime(handler).prepare(
            Action("1", "write_file", {"path": "index.html"})
        )

        self.assertIsNone(preparation.call)
        self.assertEqual(preparation.failure.code, "tool_validation_failed")
        self.assertTrue(preparation.failure.blocked)
        handler.execute.assert_not_called()

    def test_validation_message_contains_only_field_locations(self):
        handler = mock.Mock()
        secret = "sk-secret-validation-value"

        preparation = self._runtime(handler).prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": {"token": secret}},
            )
        )

        self.assertEqual(
            preparation.failure.message,
            "invalid tool arguments: content",
        )
        self.assertNotIn(secret, preparation.failure.message)

    def test_prepare_returns_stable_unknown_tool_failure(self):
        preparation = ToolRuntime(ToolRegistry()).prepare(
            Action("1", "missing", {})
        )

        self.assertIsNone(preparation.call)
        self.assertEqual(preparation.failure.code, "unknown_tool")
        self.assertTrue(preparation.failure.blocked)

    def test_execute_prepared_validates_and_returns_handler_result(self):
        handler = mock.Mock()
        handler.execute.return_value = {"path": "index.html"}
        runtime = self._runtime(handler)
        preparation = runtime.prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "page"},
            )
        )
        context = mock.create_autospec(ToolExecutionContext, instance=True)

        result = runtime.execute_prepared(preparation.call, context)

        self.assertTrue(result.ok)
        self.assertEqual(result.code, "ok")
        self.assertEqual(result.data, {"path": "index.html"})
        handler.execute.assert_called_once_with(
            WriteFileArgs(path="index.html", content="page"),
            context,
        )

    def test_execute_prepared_maps_domain_error_and_rule_family(self):
        handler = mock.Mock()
        handler.execute.side_effect = ToolExecutionError(
            "linked_path",
            "linked_path: linked target",
            blocked=True,
            rule_family="linked_path",
        )
        runtime = self._runtime(handler)
        preparation = runtime.prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "page"},
            )
        )

        result = runtime.execute_prepared(
            preparation.call,
            mock.create_autospec(ToolExecutionContext, instance=True),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "linked_path")
        self.assertEqual(result.rule_family, "linked_path")
        self.assertEqual(result.data["path"], "index.html")
        self.assertEqual(result.data["rule_family"], "linked_path")


if __name__ == "__main__":
    unittest.main()
