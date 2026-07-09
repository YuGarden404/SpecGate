import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.policy import GuardrailDecision, WorkspacePolicy, check_action


class PolicyTests(unittest.TestCase):
    def test_allows_registered_write_inside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file"},
                allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                allowed_write_paths={"index.html"},
            )
            action = Action("1", "write_file", {"path": "index.html", "content": "ok"})

            decision = check_action(action, policy)

            self.assertEqual(decision, GuardrailDecision(True, "allowed"))

    def test_blocks_unknown_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "run_command", {"command": "dir"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("unknown action", decision.reason)

    def test_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "write_file", {"path": "../outside.txt", "content": "bad"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("path escapes workspace", decision.reason)

    def test_blocks_write_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "write_file", {"path": "secret.txt", "content": "bad"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("write path not allowed", decision.reason)

    def test_blocks_file_action_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"read_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "read_file", {})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("missing required path", decision.reason)

    def test_blocks_file_action_with_non_string_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "write_file", {"path": 123, "content": "bad"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("path must be a non-empty string", decision.reason)


if __name__ == "__main__":
    unittest.main()
