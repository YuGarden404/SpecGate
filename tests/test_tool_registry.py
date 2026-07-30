import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tool_handlers import (
    FinishHandler,
    ListFilesHandler,
    ReadFileHandler,
    ReplaceFileHandler,
    ToolExecutionContext,
    ToolExecutionError,
    WriteFileHandler,
)
from specgate.tool_registry import (
    DuplicateToolError,
    FinishArgs,
    ListFilesArgs,
    PermissionClass,
    ReadFileArgs,
    SideEffectClass,
    ToolDefinition,
    ToolMetadata,
    ToolRegistry,
    UnknownToolError,
    WriteFileArgs,
    default_tool_registry,
    render_tool_registry_for_context,
)
from specgate.workspace_fs import WorkspacePathError


class ToolRegistryTests(unittest.TestCase):
    def test_default_registry_contains_executable_mvp_tools_in_stable_order(self):
        registry = default_tool_registry()

        self.assertEqual(
            tuple(definition.name for definition in registry.values()),
            ("read_file", "write_file", "replace_file", "list_files", "finish"),
        )
        self.assertIsInstance(registry.resolve("read_file").handler, ReadFileHandler)
        self.assertIsInstance(registry.resolve("write_file").handler, WriteFileHandler)
        self.assertIsInstance(registry.resolve("replace_file").handler, ReplaceFileHandler)
        self.assertIsInstance(registry.resolve("list_files").handler, ListFilesHandler)
        self.assertIsInstance(registry.resolve("finish").handler, FinishHandler)

    def test_default_definitions_have_exact_metadata_and_classes(self):
        registry = default_tool_registry()

        expected = {
            "read_file": (
                "Read allowed UTF-8 workspace text.",
                PermissionClass.READ,
                SideEffectClass.NONE,
            ),
            "write_file": (
                "Write allowed UTF-8 workspace text.",
                PermissionClass.WRITE,
                SideEffectClass.WORKSPACE_WRITE,
            ),
            "replace_file": (
                "Replace allowed UTF-8 workspace text.",
                PermissionClass.WRITE,
                SideEffectClass.WORKSPACE_WRITE,
            ),
            "list_files": (
                "List policy-readable workspace files.",
                PermissionClass.INSPECT,
                SideEffectClass.NONE,
            ),
            "finish": (
                "Request final Gate and completion.",
                PermissionClass.CONTROL,
                SideEffectClass.RUN_CONTROL,
            ),
        }

        for name, (description, permission, side_effect) in expected.items():
            with self.subTest(name=name):
                definition = registry.resolve(name)
                self.assertEqual(definition.metadata.description, description)
                self.assertEqual(definition.permission_class, permission)
                self.assertEqual(definition.side_effect_class, side_effect)

    def test_duplicate_tool_name_fails_closed(self):
        definition = default_tool_registry().resolve("read_file")
        registry = ToolRegistry()
        registry.register(definition)

        with self.assertRaises(DuplicateToolError):
            registry.register(definition)

    def test_unknown_tool_resolution_fails_closed(self):
        with self.assertRaises(UnknownToolError):
            ToolRegistry().resolve("missing")

    def test_registry_values_preserve_registration_order(self):
        defaults = default_tool_registry()
        registry = ToolRegistry()
        registry.register(defaults.resolve("finish"))
        registry.register(defaults.resolve("read_file"))

        self.assertEqual(
            tuple(definition.name for definition in registry.values()),
            ("finish", "read_file"),
        )

    def test_tool_definition_owns_pydantic_argument_validation(self):
        definition = default_tool_registry().resolve("write_file")

        args = definition.args_model.model_validate(
            {"path": "index.html", "content": "<html></html>"}
        )
        self.assertEqual(args, WriteFileArgs(path="index.html", content="<html></html>"))
        with self.assertRaises(ValidationError):
            definition.args_model.model_validate({"path": "index.html"})

    def test_metadata_and_definition_are_immutable(self):
        definition = default_tool_registry().resolve("read_file")

        with self.assertRaises(FrozenInstanceError):
            definition.metadata.name = "changed"
        with self.assertRaises(FrozenInstanceError):
            definition.permission_class = PermissionClass.WRITE

    def test_definition_name_delegates_to_metadata(self):
        definition = ToolDefinition(
            metadata=ToolMetadata("custom", "custom tool"),
            permission_class=PermissionClass.READ,
            side_effect_class=SideEffectClass.NONE,
            args_model=ReadFileArgs,
            result_model=default_tool_registry().resolve("read_file").result_model,
            handler=ReadFileHandler(),
        )

        self.assertEqual(definition.name, "custom")

    def test_render_tool_registry_for_context(self):
        rendered = render_tool_registry_for_context()

        self.assertIn("write_file [write]", rendered)
        self.assertIn("finish [control]", rendered)
        self.assertIn("args: path, content", rendered)


class ToolHandlerTests(unittest.TestCase):
    def test_read_file_handler_returns_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("hello", encoding="utf-8")
            context = ToolExecutionContext(
                WorkspacePolicy(root, {"read_file"}, {"index.html"}, set()),
                snapshot=None,
            )

            result = ReadFileHandler().execute(ReadFileArgs(path="index.html"), context)

            self.assertEqual(result.path, "index.html")
            self.assertEqual(result.content, "hello")

    def test_write_and_replace_handlers_update_the_snapshot_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root,
                {"write_file", "replace_file"},
                {"index.html"},
                {"index.html"},
            )
            snapshot = FileSnapshot.capture(root, {"index.html"})
            context = ToolExecutionContext(policy, snapshot)

            written = WriteFileHandler().execute(
                WriteFileArgs(path="index.html", content="first"), context
            )
            replaced = ReplaceFileHandler().execute(
                WriteFileArgs(path="index.html", content="second"), context
            )

            self.assertEqual(written.path, "index.html")
            self.assertEqual(replaced.path, "index.html")
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "second")
            self.assertTrue(snapshot.check_unchanged("index.html").allowed)

    def test_list_files_handler_only_returns_policy_readable_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("ok", encoding="utf-8")
            (root / "secret.txt").write_text("hidden", encoding="utf-8")
            context = ToolExecutionContext(
                WorkspacePolicy(
                    root,
                    {"list_files"},
                    {"missing.txt", "index.html"},
                    set(),
                ),
                snapshot=None,
            )

            result = ListFilesHandler().execute(ListFilesArgs(), context)

            self.assertEqual(result.files, ["index.html"])

    def test_finish_handler_only_returns_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ToolExecutionContext(
                WorkspacePolicy(Path(tmp), {"finish"}, set(), set()),
                snapshot=None,
            )

            result = FinishHandler().execute(FinishArgs(summary="done"), context)

            self.assertEqual(result.summary, "done")

    def test_handler_preserves_workspace_path_error_rule_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ToolExecutionContext(
                WorkspacePolicy(Path(tmp), {"read_file"}, {"index.html"}, set()),
                snapshot=None,
            )
            error = WorkspacePathError("linked target", "linked_path")

            with mock.patch(
                "specgate.tool_handlers.workspace_fs.read_workspace_text",
                side_effect=error,
            ):
                with self.assertRaises(ToolExecutionError) as raised:
                    ReadFileHandler().execute(ReadFileArgs(path="index.html"), context)

            self.assertEqual(raised.exception.code, "linked_path")
            self.assertEqual(raised.exception.rule_family, "linked_path")
            self.assertTrue(raised.exception.blocked)


if __name__ == "__main__":
    unittest.main()
