import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run, get_run, resume_run_once
from specgate.web_approvals import (
    approve_web_approval,
    deny_web_approval,
    list_web_approvals,
)


class WebApprovalsTests(unittest.TestCase):
    def make_context(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        db_path = base / "web.sqlite3"
        data_root = base / "data"
        init_db(db_path)
        alice = create_user(db_path, "alice", "correct-password")
        bob = create_user(db_path, "bob", "correct-password")
        alice_project = create_manual_project(
            db_path,
            data_root,
            alice["id"],
            name="Alice Site",
            spec_text="# Spec\nBuild Alice's page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        bob_project = create_manual_project(
            db_path,
            data_root,
            bob["id"],
            name="Bob Site",
            spec_text="# Spec\nBuild Bob's page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        return db_path, data_root, alice, bob, alice_project, bob_project

    def add_web_approval(
        self,
        db_path,
        data_root,
        user,
        project,
        *,
        approval_id="approval-step-1",
        run_status="needs_approval",
        approval_status="pending",
    ):
        run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Build the result",
            data_root=data_root,
        )
        approval = PendingApproval(
            id=approval_id,
            step=1,
            action="write_file",
            path="index.html",
            risk_level="review",
            reason="write_file requires human review",
            profile="review",
            status=approval_status,
            action_payload={
                "schema_version": "1",
                "action": "write_file",
                "args": {"path": "index.html", "content": "<!doctype html><title>Approved</title>"},
            },
        )
        paths = project_paths(data_root, user["id"], project["id"])
        ApprovalQueue([approval]).write(approval_queue_path(paths.workspace))
        with closing(connect_db(db_path)) as conn:
            conn.execute("update runs set status = ? where id = ?", (run_status, run["id"]))
            cursor = conn.execute(
                """
                insert into approvals (
                    run_id,
                    project_id,
                    approval_id,
                    status,
                    action_name,
                    target_path,
                    reason,
                    preview_json,
                    created_at,
                    decided_at
                )
                values (?, ?, ?, ?, ?, ?, ?, '{}', '2026-07-11T10:00:00Z', null)
                """,
                (
                    run["id"],
                    project["id"],
                    approval_id,
                    approval_status,
                    approval.action,
                    approval.path,
                    approval.reason,
                ),
            )
            conn.commit()
            web_approval = conn.execute(
                "select * from approvals where id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return run, web_approval

    def test_list_web_approvals_only_lists_current_user(self):
        db_path, data_root, alice, bob, alice_project, bob_project = self.make_context()
        _alice_run, alice_approval = self.add_web_approval(
            db_path,
            data_root,
            alice,
            alice_project,
            approval_id="alice-approval",
        )
        self.add_web_approval(
            db_path,
            data_root,
            bob,
            bob_project,
            approval_id="bob-approval",
        )

        approvals = list_web_approvals(db_path, alice["id"])

        self.assertEqual([row["id"] for row in approvals], [alice_approval["id"]])
        self.assertEqual([row["approval_id"] for row in approvals], ["alice-approval"])

    def test_approve_web_approval_updates_queue_and_db(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        _run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        row = approve_web_approval(db_path, data_root, alice["id"], web_approval["id"])

        self.assertIsInstance(row, sqlite3.Row)
        self.assertEqual(row["status"], "approved")
        self.assertIsNotNone(row["decided_at"])
        queue = ApprovalQueue.read(approval_queue_path(project_paths(data_root, alice["id"], alice_project["id"]).workspace))
        self.assertEqual(queue.approvals[0].status, "approved")
        self.assertEqual(queue.approvals[0].decided_at, row["decided_at"])
        self.assertIsNone(queue.approvals[0].decision_reason)

    def test_approve_web_approval_rejects_duplicate_decisions_without_diverging(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        _run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        approved = approve_web_approval(db_path, data_root, alice["id"], web_approval["id"])

        with self.assertRaises(ValueError):
            deny_web_approval(db_path, data_root, alice["id"], web_approval["id"], "too broad")
        with self.assertRaises(ValueError):
            approve_web_approval(db_path, data_root, alice["id"], web_approval["id"])

        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
        with closing(connect_db(db_path)) as conn:
            db_row = conn.execute(
                "select status, decided_at from approvals where id = ?",
                (web_approval["id"],),
            ).fetchone()
        self.assertEqual(queue.approvals[0].status, "approved")
        self.assertEqual(queue.approvals[0].decided_at, approved["decided_at"])
        self.assertEqual(db_row["status"], "approved")
        self.assertEqual(db_row["decided_at"], approved["decided_at"])

    def test_approve_web_approval_rejects_non_pending_db_row_before_writing_queue(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        _run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update approvals set status = 'approved', decided_at = '2026-07-11T10:01:00Z' where id = ?",
                (web_approval["id"],),
            )
            conn.commit()

        with self.assertRaises(ValueError):
            approve_web_approval(db_path, data_root, alice["id"], web_approval["id"])

        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
        with closing(connect_db(db_path)) as conn:
            db_row = conn.execute(
                "select status, decided_at from approvals where id = ?",
                (web_approval["id"],),
            ).fetchone()
        self.assertEqual(queue.approvals[0].status, "pending")
        self.assertEqual(db_row["status"], "approved")
        self.assertEqual(db_row["decided_at"], "2026-07-11T10:01:00Z")

    def test_deny_web_approval_updates_queue_and_db(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        _run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        row = deny_web_approval(db_path, data_root, alice["id"], web_approval["id"], "too broad")

        self.assertEqual(row["status"], "denied")
        self.assertIsNotNone(row["decided_at"])
        queue = ApprovalQueue.read(approval_queue_path(project_paths(data_root, alice["id"], alice_project["id"]).workspace))
        self.assertEqual(queue.approvals[0].status, "denied")
        self.assertEqual(queue.approvals[0].decided_at, row["decided_at"])
        self.assertEqual(queue.approvals[0].decision_reason, "too broad")

    def test_approve_web_approval_rejects_project_mismatch(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        other_project = create_manual_project(
            db_path,
            data_root,
            alice["id"],
            name="Other Alice Site",
            spec_text="# Spec\nBuild another page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        _run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        other_paths = project_paths(data_root, alice["id"], other_project["id"])
        ApprovalQueue(
            [
                PendingApproval(
                    id=web_approval["approval_id"],
                    step=1,
                    action="write_file",
                    path="index.html",
                    risk_level="review",
                    reason="write_file requires human review",
                    profile="review",
                )
            ]
        ).write(approval_queue_path(other_paths.workspace))
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update approvals set project_id = ? where id = ?",
                (other_project["id"], web_approval["id"]),
            )
            conn.commit()

        with self.assertRaises(ValueError):
            approve_web_approval(db_path, data_root, alice["id"], web_approval["id"])

        queue = ApprovalQueue.read(approval_queue_path(other_paths.workspace))
        self.assertEqual(queue.approvals[0].status, "pending")

    def test_resume_run_once_only_resumes_needs_approval_runs(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        completed_project = create_manual_project(
            db_path,
            data_root,
            alice["id"],
            name="Completed Site",
            spec_text="# Spec\nBuild a completed page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        queued_project = create_manual_project(
            db_path,
            data_root,
            alice["id"],
            name="Queued Site",
            spec_text="# Spec\nBuild a queued page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        needs_run, _approval = self.add_web_approval(
            db_path,
            data_root,
            alice,
            alice_project,
            approval_status="approved",
        )
        completed_run = create_run(
            db_path,
            completed_project["id"],
            alice["id"],
            "Completed run",
            data_root=data_root,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute("update runs set status = 'completed' where id = ?", (completed_run["id"],))
            conn.commit()
        queued_run = create_run(
            db_path,
            queued_project["id"],
            alice["id"],
            "Queued run",
            data_root=data_root,
        )

        def fake_resume(paths, settings):
            self.assertEqual(settings["governance_profile"], "review")
            self.assertEqual(settings["context_strategy"], "injection-safe")
            queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
            queue.resolve(queue.next_resume_candidate().id, "applied", "2026-07-11T10:02:00Z").write(
                approval_queue_path(paths.workspace)
            )
            (paths.workspace / "index.html").write_text(
                "<!doctype html><html><head><title>Fresh</title></head><body>Fresh</body></html>",
                encoding="utf-8",
            )
            return SimpleNamespace(passed=True, trust=None)

        with patch("specgate.web_runs._run_resume_agent", side_effect=fake_resume) as runner:
            updated = resume_run_once(db_path, data_root, alice["id"], needs_run["id"])
            completed_result = resume_run_once(db_path, data_root, alice["id"], completed_run["id"])
            queued_result = resume_run_once(db_path, data_root, alice["id"], queued_run["id"])

        self.assertEqual(runner.call_count, 1)
        self.assertEqual(updated["status"], "completed")
        self.assertIsNone(completed_result)
        self.assertIsNone(queued_result)
        self.assertEqual(get_run(db_path, alice["id"], completed_run["id"])["status"], "completed")
        self.assertEqual(get_run(db_path, alice["id"], queued_run["id"])["status"], "queued")

    def test_resume_run_once_rejects_other_users_run(self):
        db_path, data_root, alice, bob, alice_project, _bob_project = self.make_context()
        needs_run, _approval = self.add_web_approval(
            db_path,
            data_root,
            alice,
            alice_project,
            approval_status="approved",
        )

        with patch("specgate.web_runs._run_resume_agent") as runner:
            with self.assertRaises(ValueError):
                resume_run_once(db_path, data_root, bob["id"], needs_run["id"])

        runner.assert_not_called()
        self.assertEqual(get_run(db_path, alice["id"], needs_run["id"])["status"], "needs_approval")

    def test_resume_run_once_rejects_pending_approval_without_marking_failed(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        needs_run, _approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        with patch("specgate.web_runs._run_resume_agent") as runner:
            with self.assertRaises(ValueError):
                resume_run_once(db_path, data_root, alice["id"], needs_run["id"])

        runner.assert_not_called()
        self.assertEqual(get_run(db_path, alice["id"], needs_run["id"])["status"], "needs_approval")


if __name__ == "__main__":
    unittest.main()
