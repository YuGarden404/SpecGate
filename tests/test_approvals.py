import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    classify_action_risk,
)
from specgate.policy import WorkspacePolicy


class ApprovalTests(unittest.TestCase):
    def test_allowed_write_to_normal_artifact_is_safe(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {"index.html"})
        config = GovernanceConfig(profile="review")
        action = Action("1", "write_file", {"path": "index.html", "content": "ok"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "safe")
        self.assertEqual(risk.reason, "safe action")

    def test_protected_replace_requires_review(self):
        policy = WorkspacePolicy(Path("."), {"replace_file"}, set(), {"README.md"})
        config = GovernanceConfig(
            profile="review",
            review_actions={"replace_file"},
            review_paths={"README.md"},
        )
        action = Action("1", "replace_file", {"path": "README.md", "content": "new"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "review")
        self.assertIn("requires human review", risk.reason)

    def test_env_write_is_blocked_even_if_policy_mentions_it(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {".env"})
        config = GovernanceConfig(profile="review", blocked_paths={".env"})
        action = Action("1", "write_file", {"path": ".env", "content": "SECRET=1"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "blocked")
        self.assertIn("blocked path", risk.reason)

    def test_path_escape_is_blocked(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {"index.html"})
        config = GovernanceConfig(profile="review")
        action = Action("1", "write_file", {"path": "../outside.txt", "content": "x"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "blocked")
        self.assertIn("path escapes workspace", risk.reason)

    def test_queue_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            approval = PendingApproval(
                id="approval-step-2",
                step=2,
                action="replace_file",
                path="README.md",
                risk_level="review",
                reason="replace_file on protected path requires human review",
                profile="review",
                arguments_preview={"path": "README.md"},
            )

            queue = ApprovalQueue([approval])
            queue.write(queue_path)
            loaded = ApprovalQueue.read(queue_path)

            self.assertEqual(len(loaded.approvals), 1)
            self.assertEqual(loaded.approvals[0].id, "approval-step-2")
            self.assertEqual(loaded.approvals[0].status, "pending")

    def test_queue_append_returns_new_queue_without_mutating_original(self):
        approval = PendingApproval(
            id="approval-step-3",
            step=3,
            action="replace_file",
            path="README.md",
            risk_level="review",
            reason="replace_file on protected path requires human review",
            profile="review",
            arguments_preview={"path": "README.md"},
        )
        empty = ApprovalQueue()

        updated = empty.append(approval)

        self.assertIsNot(updated, empty)
        self.assertEqual(len(empty.approvals), 0)
        self.assertEqual(len(updated.approvals), 1)
        self.assertIs(updated.approvals[0], approval)


if __name__ == "__main__":
    unittest.main()
