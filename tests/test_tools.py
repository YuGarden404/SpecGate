import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tools import ToolDispatcher


class ToolDispatcherTests(unittest.TestCase):
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
