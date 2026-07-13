import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specgate import approvals as approvals_module
from specgate.actions import Action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    capture_target_state,
    classify_action_risk,
    preview_args,
    target_state_matches,
)
from specgate.policy import WorkspacePolicy
from specgate.workspace_fs import WorkspacePathError


class ApprovalTests(unittest.TestCase):
    def _symlink_or_skip(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def test_read_existing_queue_fails_when_final_file_is_missing(self):
        self.assertTrue(hasattr(approvals_module, "read_existing_approval_queue"))
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"

            with self.assertRaises(WorkspacePathError):
                approvals_module.read_existing_approval_queue(queue_path)

    def test_read_queue_if_present_handles_explicitly_missing_queue(self):
        self.assertTrue(hasattr(approvals_module, "read_approval_queue_if_present"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch(
                    "specgate.workspace_fs.read_optional_workspace_text",
                    return_value=None,
                    create=True,
                ) as read,
                mock.patch("specgate.workspace_fs.scan_workspace_files") as scan,
            ):
                queue = approvals_module.read_approval_queue_if_present(
                    root,
                    root / "runs" / "latest" / "pending_approvals.json",
                )

            self.assertIsNone(queue)
            read.assert_called_once_with(
                root,
                "runs/latest/pending_approvals.json",
                encoding="utf-8-sig",
            )
            scan.assert_not_called()

    def test_read_queue_if_present_parses_optional_read_content_without_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch(
                    "specgate.workspace_fs.read_optional_workspace_text",
                    return_value='{"approvals": []}',
                    create=True,
                ) as read,
                mock.patch("specgate.workspace_fs.scan_workspace_files") as scan,
            ):
                queue = approvals_module.read_approval_queue_if_present(
                    root,
                    root / "runs" / "latest" / "pending_approvals.json",
                )

            self.assertEqual(queue, ApprovalQueue())
            read.assert_called_once_with(
                root,
                "runs/latest/pending_approvals.json",
                encoding="utf-8-sig",
            )
            scan.assert_not_called()

    def test_read_queue_if_present_propagates_target_path_race(self):
        relative_path = "runs/latest/pending_approvals.json"
        errors = (
            WorkspacePathError("ancestor missing", "path_race"),
            WorkspacePathError("target changed", "path_race", missing_path=relative_path),
        )
        for error in errors:
            with self.subTest(missing_path=error.missing_path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with mock.patch(
                    "specgate.workspace_fs.read_optional_workspace_text",
                    side_effect=error,
                    create=True,
                ) as read:
                    with self.assertRaises(WorkspacePathError) as raised:
                        approvals_module.read_approval_queue_if_present(
                            root,
                            root / relative_path,
                        )

                self.assertIs(raised.exception, error)
                read.assert_called_once()

    def test_read_queue_if_present_propagates_target_link_rejections(self):
        relative_path = "runs/latest/pending_approvals.json"
        for family in ("linked_path", "reparse_point"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                error = WorkspacePathError("unsafe queue path", family)
                with mock.patch(
                    "specgate.workspace_fs.read_optional_workspace_text",
                    side_effect=error,
                    create=True,
                ):
                    with self.assertRaises(WorkspacePathError) as raised:
                        approvals_module.read_approval_queue_if_present(
                            root,
                            root / relative_path,
                        )

                self.assertIs(raised.exception, error)

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
        self.assertEqual(getattr(risk, "rule_family", None), "path_escape")
        self.assertEqual(risk.to_dict().get("rule_family"), "path_escape")

    def test_invalid_path_rule_family_survives_risk_classification(self):
        policy = WorkspacePolicy(
            Path("."),
            {"read_file"},
            {"docs/index.html"},
            set(),
        )
        action = Action("1", "read_file", {"path": r"docs\index.html"})

        risk = classify_action_risk(action, policy, GovernanceConfig(profile="review"))

        self.assertEqual(risk.level, "blocked")
        self.assertEqual(getattr(risk, "rule_family", None), "invalid_path")

    def test_target_state_capture_rejects_external_link(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "outside.txt"
            external.write_text("EXTERNAL_APPROVAL_SENTINEL", encoding="utf-8")
            self._symlink_or_skip(root / "README.md", external)

            with self.assertRaises(WorkspacePathError) as raised:
                capture_target_state(root, "README.md")

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_target_state_capture_propagates_safe_state_link_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "specgate.workspace_fs.workspace_file_state",
                side_effect=WorkspacePathError("linked target", "linked_path"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    capture_target_state(Path(tmp), "README.md")

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_target_state_path_race_is_a_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("safe", encoding="utf-8")
            target_state = capture_target_state(root, "README.md")

            with mock.patch(
                "specgate.workspace_fs.workspace_file_state",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                matches = target_state_matches(root, target_state)

            self.assertFalse(matches)

    def test_target_state_mismatch_on_ancestor_replacement(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (nested / "README.md").write_text("same bytes", encoding="utf-8")
            target_state = capture_target_state(root, "nested/README.md")
            external = Path(outside)
            (external / "README.md").write_text("same bytes", encoding="utf-8")
            nested.rename(root / "original-nested")
            self._symlink_or_skip(root / "nested", external, directory=True)

            self.assertFalse(target_state_matches(root, target_state))

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

    def test_queue_write_propagates_reparse_rejection_without_overwriting_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            sentinel = "EXTERNAL_QUEUE_WRITE_SENTINEL"
            queue_path.write_text(sentinel, encoding="utf-8")

            with mock.patch(
                "specgate.workspace_fs.write_workspace_text",
                side_effect=WorkspacePathError("reparse queue", "reparse_point"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue().write(queue_path)

            self.assertEqual(raised.exception.rule_family, "reparse_point")
            self.assertEqual(queue_path.read_text(encoding="utf-8"), sentinel)

    def test_queue_read_propagates_link_rejection_without_reading_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            sentinel = "EXTERNAL_QUEUE_READ_SENTINEL"
            queue_path.write_text(
                json.dumps({"approvals": [], "sentinel": sentinel}),
                encoding="utf-8",
            )

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=WorkspacePathError("linked queue", "linked_path"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue.read(queue_path)

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_queue_write_propagates_ancestor_path_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "runs" / "latest" / "pending_approvals.json"

            with mock.patch(
                "specgate.workspace_fs.write_workspace_text",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue().write(queue_path)

            self.assertEqual(raised.exception.rule_family, "path_race")

    def test_queue_read_propagates_ancestor_path_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            queue_path.write_text('{"approvals": []}', encoding="utf-8")

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue.read(queue_path)

            self.assertEqual(raised.exception.rule_family, "path_race")

    def test_queue_read_does_not_treat_chained_missing_path_race_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            try:
                raise FileNotFoundError("ancestor disappeared")
            except FileNotFoundError as missing:
                error = WorkspacePathError("ancestor replaced", "path_race")
                error.__cause__ = missing

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=error,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue.read(queue_path)

            self.assertIs(raised.exception, error)

    def test_queue_read_returns_empty_only_when_final_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"

            queue = ApprovalQueue.read(queue_path)

            self.assertEqual(queue, ApprovalQueue())

    def test_queue_read_returns_empty_when_trusted_parent_matches_queue_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "pending_approvals.json"
            parent.mkdir()
            queue_path = parent / "pending_approvals.json"

            queue = ApprovalQueue.read(queue_path)

            self.assertEqual(queue, ApprovalQueue())

    def test_queue_read_fails_closed_when_parent_is_missing_before_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "missing" / "pending_approvals.json"

            with self.assertRaises(WorkspacePathError) as raised:
                ApprovalQueue.read(queue_path)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(queue_path.parent.exists())

    def test_queue_read_fails_closed_when_parent_disappears_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "missing" / "pending_approvals.json"
            missing = FileNotFoundError(
                2,
                "parent disappeared",
                str(queue_path.parent),
            )
            error = WorkspacePathError("ancestor replaced", "path_race")
            error.__cause__ = missing

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=error,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    ApprovalQueue.read(queue_path)

            self.assertIs(raised.exception, error)

    def test_queue_file_link_does_not_overwrite_external_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "pending_approvals.json"
            sentinel = "EXTERNAL_QUEUE_FILE_SENTINEL"
            external.write_text(sentinel, encoding="utf-8")
            self._symlink_or_skip(root / "pending_approvals.json", external)

            with self.assertRaises(WorkspacePathError):
                ApprovalQueue().write(root / "pending_approvals.json")

            self.assertEqual(external.read_text(encoding="utf-8"), sentinel)

    def test_queue_ancestor_link_does_not_create_external_queue(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside)
            self._symlink_or_skip(root / "runs", external, directory=True)
            queue_path = root / "runs" / "latest" / "pending_approvals.json"

            with self.assertRaises(WorkspacePathError):
                ApprovalQueue().write(queue_path)

            self.assertFalse((external / "latest" / "pending_approvals.json").exists())

    def test_queue_file_link_does_not_read_external_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "pending_approvals.json"
            sentinel = "EXTERNAL_QUEUE_READ_SENTINEL"
            external.write_text(sentinel, encoding="utf-8")
            self._symlink_or_skip(root / "pending_approvals.json", external)

            with self.assertRaises(WorkspacePathError):
                ApprovalQueue.read(root / "pending_approvals.json")

    def test_queue_round_trip_preserves_action_payload_and_decision_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            approval = PendingApproval(
                id="approval-step-2",
                step=2,
                action="replace_file",
                path="README.md",
                risk_level="review",
                reason="requires human review",
                profile="review",
                arguments_preview={"path": "README.md"},
                action_payload={
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {"path": "README.md", "content": "full content"},
                },
                status="pending",
                created_at="2026-07-11T10:00:00Z",
                decided_at=None,
                decision_reason=None,
                resolved_at=None,
            )

            ApprovalQueue([approval]).write(queue_path)
            loaded = ApprovalQueue.read(queue_path)

            loaded_approval = loaded.approvals[0]
            self.assertEqual(loaded_approval.action_payload["action"], "replace_file")
            self.assertEqual(loaded_approval.action_payload["args"]["content"], "full content")
            self.assertIsNone(loaded_approval.decided_at)
            self.assertIsNone(loaded_approval.decision_reason)
            self.assertIsNone(loaded_approval.resolved_at)

    def test_queue_round_trip_preserves_target_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            approval = PendingApproval(
                id="approval-step-2",
                step=2,
                action="replace_file",
                path="README.md",
                risk_level="review",
                reason="requires human review",
                profile="review",
                target_state={
                    "path": "README.md",
                    "exists": True,
                    "sha256": "a" * 64,
                },
            )

            ApprovalQueue([approval]).write(queue_path)
            loaded = ApprovalQueue.read(queue_path)

            self.assertEqual(
                loaded.approvals[0].target_state,
                {"path": "README.md", "exists": True, "sha256": "a" * 64},
            )

    def test_approve_pending_approval_updates_status_and_timestamp(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="pending",
                    action_payload={"schema_version": "1", "action": "replace_file", "args": {"path": "README.md"}},
                )
            ]
        )

        updated = queue.approve("approval-step-1", decided_at="2026-07-11T10:01:00Z")

        self.assertEqual(updated.approvals[0].status, "approved")
        self.assertEqual(updated.approvals[0].decided_at, "2026-07-11T10:01:00Z")
        self.assertIsNone(updated.approvals[0].decision_reason)

    def test_deny_pending_approval_updates_reason_and_timestamp(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="pending",
                    action_payload={"schema_version": "1", "action": "replace_file", "args": {"path": "README.md"}},
                )
            ]
        )

        updated = queue.deny(
            "approval-step-1",
            reason="too broad",
            decided_at="2026-07-11T10:01:00Z",
        )

        self.assertEqual(updated.approvals[0].status, "denied")
        self.assertEqual(updated.approvals[0].decision_reason, "too broad")
        self.assertEqual(updated.approvals[0].decided_at, "2026-07-11T10:01:00Z")

    def test_cannot_approve_non_pending_approval(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="applied",
                )
            ]
        )

        with self.assertRaises(ValueError) as error:
            queue.approve("approval-step-1", decided_at="2026-07-11T10:01:00Z")

        self.assertIn("approval is not pending", str(error.exception))

    def test_next_resume_candidate_returns_approved_or_denied_only(self):
        queue = ApprovalQueue(
            [
                PendingApproval("approval-step-1", 1, "replace_file", "a.md", "review", "review", "review", status="pending"),
                PendingApproval("approval-step-2", 2, "replace_file", "b.md", "review", "review", "review", status="approved"),
                PendingApproval("approval-step-3", 3, "replace_file", "c.md", "review", "review", "review", status="denied"),
            ]
        )

        candidate = queue.next_resume_candidate()

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.id, "approval-step-2")

    def test_resolve_applies_approved_approval(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="approved",
                )
            ]
        )

        updated = queue.resolve("approval-step-1", "applied", resolved_at="2026-07-11T10:02:00Z")

        self.assertEqual(updated.approvals[0].status, "applied")
        self.assertEqual(updated.approvals[0].resolved_at, "2026-07-11T10:02:00Z")

    def test_resolve_rejects_denied_approval(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="denied",
                    decision_reason="too broad",
                )
            ]
        )

        updated = queue.resolve("approval-step-1", "rejected", resolved_at="2026-07-11T10:02:00Z")

        self.assertEqual(updated.approvals[0].status, "rejected")
        self.assertEqual(updated.approvals[0].decision_reason, "too broad")

    def test_resolve_fails_approved_approval_with_reason(self):
        queue = ApprovalQueue(
            [
                PendingApproval(
                    id="approval-step-1",
                    step=1,
                    action="replace_file",
                    path="README.md",
                    risk_level="review",
                    reason="requires human review",
                    profile="review",
                    status="approved",
                )
            ]
        )

        updated = queue.resolve(
            "approval-step-1",
            "failed",
            resolved_at="2026-07-11T10:02:00Z",
            reason="snapshot changed",
        )

        self.assertEqual(updated.approvals[0].status, "failed")
        self.assertEqual(updated.approvals[0].decision_reason, "snapshot changed")

    def test_resolve_rejects_pending_and_terminal_approvals(self):
        for status in ("pending", "applied", "rejected", "failed"):
            with self.subTest(status=status):
                queue = ApprovalQueue(
                    [
                        PendingApproval(
                            id="approval-step-1",
                            step=1,
                            action="replace_file",
                            path="README.md",
                            risk_level="review",
                            reason="requires human review",
                            profile="review",
                            status=status,
                        )
                    ]
                )

                with self.assertRaises(ValueError) as error:
                    queue.resolve("approval-step-1", "applied", resolved_at="2026-07-11T10:02:00Z")

                self.assertIn("approval is not resumable", str(error.exception))

    def test_resolve_enforces_approved_and_denied_target_statuses(self):
        invalid_transitions = [
            ("approved", "rejected"),
            ("denied", "applied"),
            ("denied", "failed"),
        ]
        for source_status, target_status in invalid_transitions:
            with self.subTest(source_status=source_status, target_status=target_status):
                queue = ApprovalQueue(
                    [
                        PendingApproval(
                            id="approval-step-1",
                            step=1,
                            action="replace_file",
                            path="README.md",
                            risk_level="review",
                            reason="requires human review",
                            profile="review",
                            status=source_status,
                        )
                    ]
                )

                with self.assertRaises(ValueError) as error:
                    queue.resolve("approval-step-1", target_status, resolved_at="2026-07-11T10:02:00Z")

                self.assertIn("invalid approval transition", str(error.exception))

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
