import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.policy import WorkspacePolicy
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


if __name__ == "__main__":
    unittest.main()
