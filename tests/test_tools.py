import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specgate.actions import Action
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tools import ToolDispatcher
from specgate.workspace_fs import WorkspacePathError


class ToolDispatcherTests(unittest.TestCase):
    def _symlink_or_skip(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def test_write_then_read_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file", "read_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            dispatcher = ToolDispatcher(policy)

            write_result = dispatcher.dispatch(
                Action("1", "write_file", {"path": "index.html", "content": "<!doctype html>"})
            )
            read_result = dispatcher.dispatch(Action("1", "read_file", {"path": "index.html"}))

            self.assertTrue(write_result.ok)
            self.assertEqual(read_result.data["content"], "<!doctype html>")

    def test_blocked_action_returns_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            dispatcher = ToolDispatcher(policy)

            result = dispatcher.dispatch(Action("1", "run_command", {"command": "dir"}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("unknown action", result.message)
            self.assertEqual(result.action, "run_command")

    def test_file_action_without_path_returns_blocked_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(
                Path(tmp),
                {"read_file", "write_file", "replace_file"},
                {"index.html"},
                {"index.html"},
            )
            dispatcher = ToolDispatcher(policy)

            for action_name in ("read_file", "write_file", "replace_file"):
                with self.subTest(action_name=action_name):
                    result = dispatcher.dispatch(Action("1", action_name, {}))

                    self.assertFalse(result.ok)
                    self.assertTrue(result.blocked)
                    self.assertIn("missing required path", result.message)

    def test_custom_registry_blocks_tools_not_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(root, {"write_file"}, {"index.html"}, {"index.html"})
            dispatcher = ToolDispatcher(policy, registry={})

            result = dispatcher.dispatch(Action("1", "write_file", {"path": "index.html", "content": "x"}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("unknown action", result.message)

    def test_list_files_only_returns_allowed_read_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("ok", encoding="utf-8")
            (root / "secret_notes.md").write_text("hidden", encoding="utf-8")
            policy = WorkspacePolicy(
                root,
                {"list_files"},
                {"index.html"},
                {"index.html"},
            )
            dispatcher = ToolDispatcher(policy)

            result = dispatcher.dispatch(Action("1", "list_files", {}))

            self.assertTrue(result.ok)
            self.assertEqual(result.data["files"], ["index.html"])

    def test_read_file_blocks_external_link_without_returning_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            sentinel = "EXTERNAL_READ_SENTINEL"
            external = Path(outside) / "outside.txt"
            external.write_text(sentinel, encoding="utf-8")
            self._symlink_or_skip(root / "linked.txt", external)
            policy = WorkspacePolicy(
                root,
                {"read_file"},
                {"linked.txt"},
                set(),
            )

            result = ToolDispatcher(policy).dispatch(
                Action("1", "read_file", {"path": "linked.txt"})
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "linked_path")
            self.assertNotIn(sentinel, str(result.data))

    def test_write_file_blocks_external_linked_parent_without_changing_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external_root = Path(outside)
            external = external_root / "outside.txt"
            external.write_text("EXTERNAL_WRITE_SENTINEL", encoding="utf-8")
            self._symlink_or_skip(root / "linked", external_root, directory=True)
            policy = WorkspacePolicy(
                root,
                {"write_file"},
                set(),
                {"linked/outside.txt"},
            )

            result = ToolDispatcher(policy).dispatch(
                Action(
                    "1",
                    "write_file",
                    {"path": "linked/outside.txt", "content": "overwritten"},
                )
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "linked_path")
            self.assertEqual(external.read_text(encoding="utf-8"), "EXTERNAL_WRITE_SENTINEL")

    def test_list_files_blocks_allowed_external_link(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "outside.txt"
            external.write_text("EXTERNAL_LIST_SENTINEL", encoding="utf-8")
            self._symlink_or_skip(root / "linked.txt", external)
            policy = WorkspacePolicy(root, {"list_files"}, {"linked.txt"}, set())

            result = ToolDispatcher(policy).dispatch(Action("1", "list_files", {}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "linked_path")
            self.assertNotIn("linked.txt", result.data.get("files", []))

    def test_safe_io_path_race_is_a_blocked_tool_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("safe", encoding="utf-8")
            policy = WorkspacePolicy(root, {"read_file"}, {"index.html"}, set())

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                result = ToolDispatcher(policy).dispatch(
                    Action("1", "read_file", {"path": "index.html"})
                )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "path_race")
            self.assertEqual(getattr(result, "rule_family", None), "path_race")

    def test_safe_write_link_rejection_is_a_blocked_tool_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(root, {"write_file"}, set(), {"index.html"})

            with mock.patch(
                "specgate.workspace_fs.write_workspace_text",
                side_effect=WorkspacePathError("linked target", "linked_path"),
            ):
                result = ToolDispatcher(policy).dispatch(
                    Action("1", "write_file", {"path": "index.html", "content": "unsafe"})
                )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "linked_path")
            self.assertEqual(getattr(result, "rule_family", None), "linked_path")

    def test_safe_list_link_rejection_is_a_blocked_tool_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("safe", encoding="utf-8")
            policy = WorkspacePolicy(root, {"list_files"}, {"index.html"}, set())

            with mock.patch(
                "specgate.workspace_fs.iter_workspace_files",
                side_effect=WorkspacePathError("linked entry", "linked_path"),
            ):
                result = ToolDispatcher(policy).dispatch(Action("1", "list_files", {}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(result.data["rule_family"], "linked_path")
            self.assertEqual(getattr(result, "rule_family", None), "linked_path")

    def test_guardrail_rule_family_is_directly_exposed_on_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(
                Path(tmp),
                {"read_file"},
                {"docs/index.html"},
                set(),
            )

            result = ToolDispatcher(policy).dispatch(
                Action("1", "read_file", {"path": r"docs\index.html"})
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertEqual(getattr(result, "rule_family", None), "invalid_path")

    def test_snapshot_blocks_write_after_external_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            snapshot = FileSnapshot.capture(root, {"index.html"})
            dispatcher = ToolDispatcher(policy, snapshot)

            (root / "index.html").write_text("external edit", encoding="utf-8")
            result = dispatcher.dispatch(
                Action("1", "write_file", {"path": "index.html", "content": "agent edit"})
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("file changed since run started", result.message)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "external edit")

    def test_snapshot_updates_after_successful_tool_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file", "replace_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            snapshot = FileSnapshot.capture(root, {"index.html"})
            dispatcher = ToolDispatcher(policy, snapshot)

            first = dispatcher.dispatch(Action("1", "write_file", {"path": "index.html", "content": "first"}))
            second = dispatcher.dispatch(Action("1", "replace_file", {"path": "index.html", "content": "second"}))

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "second")


if __name__ == "__main__":
    unittest.main()
