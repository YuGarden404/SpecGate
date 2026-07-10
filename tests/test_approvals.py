import json
import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    classify_action_risk,
    preview_args,
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

    def test_env_write_is_blocked_even_when_custom_blocked_paths_omit_env(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {".env"})
        config = GovernanceConfig(profile="review", blocked_paths={"custom.txt"})
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

    def test_preview_args_redacts_secret_like_strings_in_json_output(self):
        preview = preview_args(
            {
                "openai": "sk-1234567890abcdef",
                "query": "api_key=abcdef123456",
                "pem": "-----BEGIN PRIVATE KEY-----",
            }
        )

        preview_json = json.dumps(preview)

        self.assertNotIn("sk-1234567890abcdef", preview_json)
        self.assertNotIn("api_key=abcdef123456", preview_json)
        self.assertIn("api_key=[REDACTED]", preview_json)
        self.assertNotIn("-----BEGIN PRIVATE KEY-----", preview_json)

    def test_preview_args_recurses_and_queue_write_accepts_json_unsafe_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            preview = preview_args(
                {
                    "nested": {
                        "items": [
                            Path("secret.txt"),
                            {"tokens": {"sk-1234567890abcdef"}},
                        ]
                    },
                    "long": "x" * 300 + "sk-1234567890abcdef",
                }
            )
            approval = PendingApproval(
                id="approval-step-4",
                step=4,
                action="write_file",
                path="secret.txt",
                risk_level="review",
                reason="manual review",
                profile="review",
                arguments_preview=preview,
            )

            ApprovalQueue([approval]).write(queue_path)
            payload = json.loads(queue_path.read_text(encoding="utf-8"))

            preview_json = json.dumps(payload["approvals"][0]["arguments_preview"])
            self.assertNotIn("sk-1234567890abcdef", preview_json)
            self.assertIsInstance(
                payload["approvals"][0]["arguments_preview"]["nested"]["items"][0],
                str,
            )

    def test_malformed_queue_json_raises_decode_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            queue_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                ApprovalQueue.read(queue_path)

    def test_default_blocked_paths_block_nested_env_even_when_policy_allows_it(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {"subdir/.env"})
        config = GovernanceConfig(profile="review")
        action = Action("1", "write_file", {"path": "subdir/.env", "content": "x"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "blocked")
        self.assertIn("blocked path", risk.reason)

    def test_single_star_review_path_does_not_match_nested_file(self):
        policy = WorkspacePolicy(
            Path("."),
            {"write_file"},
            set(),
            {"src/nested/file.txt"},
        )
        config = GovernanceConfig(profile="review", review_paths={"src/*"})
        action = Action(
            "1",
            "write_file",
            {"path": "src/nested/file.txt", "content": "x"},
        )

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "safe")

    def test_double_star_review_path_matches_nested_file(self):
        policy = WorkspacePolicy(
            Path("."),
            {"write_file"},
            set(),
            {"src/nested/file.txt"},
        )
        config = GovernanceConfig(profile="review", review_paths={"src/**"})
        action = Action(
            "1",
            "write_file",
            {"path": "src/nested/file.txt", "content": "x"},
        )

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "review")


if __name__ == "__main__":
    unittest.main()
