import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from specgate.approvals import ApprovalQueue, PendingApproval
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths, web_run_paths
from specgate.web_runs import create_run, execute_run_once, get_run, resume_run_once
from specgate.trace import TraceStore
from specgate.web_approvals import (
    ApprovalConsistencyError,
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
                "args": {
                    "path": "index.html",
                    "content": (
                        '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                        '<title>Approved Result</title></head><body><main><h1>Approved Result</h1>'
                        '<input type="search" aria-label="Filter results"></main></body></html>'
                    ),
                },
            },
        )
        paths = project_paths(data_root, user["id"], project["id"])
        ApprovalQueue([approval]).write(web_run_paths(paths, run["id"]).approval_queue)
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

        approvals = list_web_approvals(db_path, data_root, alice["id"])

        self.assertEqual([row["id"] for row in approvals], [alice_approval["id"]])
        self.assertEqual([row["approval_id"] for row in approvals], ["alice-approval"])
        self.assertEqual([row["queue_revision"] for row in approvals], [0])

    def test_approve_web_approval_updates_queue_and_db(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        row = approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            web_approval["id"],
            expected_revision=0,
        )

        self.assertIsInstance(row, dict)
        self.assertEqual(row["status"], "approved")
        self.assertIsNotNone(row["decided_at"])
        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(web_run_paths(paths, run["id"]).approval_queue)
        self.assertEqual(queue.approvals[0].status, "approved")
        self.assertEqual(queue.approvals[0].decided_at, row["decided_at"])
        self.assertIsNone(queue.approvals[0].decision_reason)

    def test_database_update_failure_preserves_cas_decision_and_reports_consistency_error(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_approval_update before update of status on approvals
                begin
                    select raise(abort, 'database update rejected');
                end
                """
            )
            conn.commit()

        with self.assertRaises(ApprovalConsistencyError) as raised:
            approve_web_approval(
                db_path,
                data_root,
                alice["id"],
                web_approval["id"],
                expected_revision=0,
            )

        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(web_run_paths(paths, run["id"]).approval_queue)
        with closing(connect_db(db_path)) as conn:
            db_status = conn.execute(
                "select status from approvals where id = ?",
                (web_approval["id"],),
            ).fetchone()["status"]
        self.assertEqual(raised.exception.code, "approval_consistency_error")
        self.assertEqual(queue.approvals[0].status, "approved")
        self.assertEqual(queue.revision, 1)
        self.assertEqual(db_status, "pending")

    def test_approve_web_approval_rejects_duplicate_decisions_without_diverging(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        approved = approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            web_approval["id"],
            expected_revision=0,
        )

        with self.assertRaises(ValueError):
            deny_web_approval(
                db_path,
                data_root,
                alice["id"],
                web_approval["id"],
                "too broad",
                expected_revision=1,
            )
        with self.assertRaises(ValueError):
            approve_web_approval(
                db_path,
                data_root,
                alice["id"],
                web_approval["id"],
                expected_revision=1,
            )

        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(web_run_paths(paths, run["id"]).approval_queue)
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
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update approvals set status = 'approved', decided_at = '2026-07-11T10:01:00Z' where id = ?",
                (web_approval["id"],),
            )
            conn.commit()

        with self.assertRaises(ValueError):
            approve_web_approval(
                db_path,
                data_root,
                alice["id"],
                web_approval["id"],
                expected_revision=0,
            )

        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(web_run_paths(paths, run["id"]).approval_queue)
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
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        row = deny_web_approval(
            db_path,
            data_root,
            alice["id"],
            web_approval["id"],
            "too broad",
            expected_revision=0,
        )

        self.assertEqual(row["status"], "denied")
        self.assertIsNotNone(row["decided_at"])
        paths = project_paths(data_root, alice["id"], alice_project["id"])
        queue = ApprovalQueue.read(web_run_paths(paths, run["id"]).approval_queue)
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
        other_run = create_run(
            db_path,
            other_project["id"],
            alice["id"],
            "Build other result",
            data_root=data_root,
        )
        other_paths = web_run_paths(
            project_paths(data_root, alice["id"], other_project["id"]),
            other_run["id"],
        )
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
        ).write(other_paths.approval_queue)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update approvals set project_id = ? where id = ?",
                (other_project["id"], web_approval["id"]),
            )
            conn.commit()

        with self.assertRaises(ValueError):
            approve_web_approval(
                db_path,
                data_root,
                alice["id"],
                web_approval["id"],
                expected_revision=0,
            )

        queue = ApprovalQueue.read(other_paths.approval_queue)
        self.assertEqual(queue.approvals[0].status, "pending")

    def test_same_approval_id_is_isolated_between_projects(self):
        db_path, data_root, alice, bob, alice_project, bob_project = self.make_context()
        alice_run, alice_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        bob_run, _bob_approval = self.add_web_approval(db_path, data_root, bob, bob_project)

        approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            alice_approval["id"],
            expected_revision=0,
        )

        alice_paths = web_run_paths(
            project_paths(data_root, alice["id"], alice_project["id"]),
            alice_run["id"],
        )
        bob_paths = web_run_paths(
            project_paths(data_root, bob["id"], bob_project["id"]),
            bob_run["id"],
        )
        self.assertEqual(ApprovalQueue.read(alice_paths.approval_queue).approvals[0].status, "approved")
        self.assertEqual(ApprovalQueue.read(bob_paths.approval_queue).approvals[0].status, "pending")

    def test_same_approval_id_is_isolated_from_terminal_run_in_same_project(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        old_run, old_approval = self.add_web_approval(
            db_path,
            data_root,
            alice,
            alice_project,
            run_status="completed",
        )
        new_run, _new_approval = self.add_web_approval(db_path, data_root, alice, alice_project)

        approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            old_approval["id"],
            expected_revision=0,
        )

        project_storage = project_paths(data_root, alice["id"], alice_project["id"])
        old_queue = ApprovalQueue.read(web_run_paths(project_storage, old_run["id"]).approval_queue)
        new_queue = ApprovalQueue.read(web_run_paths(project_storage, new_run["id"]).approval_queue)
        self.assertEqual(old_queue.approvals[0].status, "approved")
        self.assertEqual(new_queue.approvals[0].status, "pending")

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
            queue = ApprovalQueue.read(paths.approval_queue)
            queue.resolve(queue.next_resume_candidate().id, "applied", "2026-07-11T10:02:00Z").write(
                paths.approval_queue
            )
            content = "<!doctype html><html><head><title>Fresh</title></head><body>Fresh</body></html>"
            (paths.workspace / "index.html").write_text(content, encoding="utf-8")
            return SimpleNamespace(
                passed=True,
                trust=None,
                outcome="completed",
                final_gate=SimpleNamespace(
                    artifact_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest()
                ),
            )

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

    def test_resume_preserves_initial_approval_trace_and_promotes_workspace(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        run, web_approval = self.add_web_approval(db_path, data_root, alice, alice_project)
        project_storage = project_paths(data_root, alice["id"], alice_project["id"])
        run_paths = web_run_paths(project_storage, run["id"])
        TraceStore(run_paths.audit / "trace.jsonl", reset=True).append(
            "approval_requested",
            {"approval_id": web_approval["approval_id"]},
        )
        approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            web_approval["id"],
            expected_revision=0,
        )

        updated = resume_run_once(db_path, data_root, alice["id"], run["id"])

        self.assertEqual(updated["status"], "completed")
        trace_events = [
            json.loads(line)["event_type"]
            for line in (run_paths.audit / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("approval_requested", trace_events)
        self.assertIn("resume_started", trace_events)
        self.assertIn("approval_applied", trace_events)
        self.assertIn("resume_finished", trace_events)
        self.assertEqual(
            (project_storage.workspace / "index.html").read_bytes(),
            run_paths.index_artifact.read_bytes(),
        )

    def test_existing_web_target_approve_revision_resume_completes(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        project_storage = project_paths(data_root, alice["id"], alice_project["id"])
        original = (
            '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
            '<title>Original</title></head><body><main>Original</main></body></html>'
        )
        (project_storage.workspace / "index.html").write_text(original, encoding="utf-8")
        run = create_run(
            db_path,
            alice_project["id"],
            alice["id"],
            "Overwrite the existing page",
            data_root=data_root,
        )

        execute_run_once(db_path, data_root, run["id"])

        paused = get_run(db_path, alice["id"], run["id"])
        approvals = list_web_approvals(db_path, data_root, alice["id"])
        self.assertEqual(paused["status"], "needs_approval")
        self.assertEqual(approvals[0]["queue_revision"], 1)
        approve_web_approval(
            db_path,
            data_root,
            alice["id"],
            approvals[0]["id"],
            expected_revision=approvals[0]["queue_revision"],
        )

        completed = resume_run_once(db_path, data_root, alice["id"], run["id"])

        run_paths = web_run_paths(project_storage, run["id"])
        queue = ApprovalQueue.read(run_paths.approval_queue)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(queue.approvals[0].status, "applied")
        self.assertNotEqual((project_storage.workspace / "index.html").read_text(encoding="utf-8"), original)

    def test_existing_web_target_deny_revision_resume_keeps_original(self):
        db_path, data_root, alice, _bob, alice_project, _bob_project = self.make_context()
        project_storage = project_paths(data_root, alice["id"], alice_project["id"])
        original = (
            '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
            '<title>Original</title></head><body><main>Original</main></body></html>'
        )
        (project_storage.workspace / "index.html").write_text(original, encoding="utf-8")
        run = create_run(
            db_path,
            alice_project["id"],
            alice["id"],
            "Overwrite the existing page",
            data_root=data_root,
        )
        execute_run_once(db_path, data_root, run["id"])
        approvals = list_web_approvals(db_path, data_root, alice["id"])
        deny_web_approval(
            db_path,
            data_root,
            alice["id"],
            approvals[0]["id"],
            "保留现有页面",
            expected_revision=approvals[0]["queue_revision"],
        )

        completed = resume_run_once(db_path, data_root, alice["id"], run["id"])

        run_paths = web_run_paths(project_storage, run["id"])
        queue = ApprovalQueue.read(run_paths.approval_queue)
        trace = (run_paths.audit / "trace.jsonl").read_text(encoding="utf-8")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(queue.approvals[0].status, "rejected")
        self.assertEqual((project_storage.workspace / "index.html").read_text(encoding="utf-8"), original)
        self.assertIn("approval_denied", trace)


if __name__ == "__main__":
    unittest.main()
