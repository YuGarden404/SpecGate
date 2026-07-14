import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import specgate.web_runs as web_runs
import specgate.run_storage as run_storage
import specgate.workspace_fs as workspace_fs
from specgate.run_storage import (
    initialize_run_storage as initialize_run_storage_real,
    promote_run_workspace as promote_run_workspace_real,
)
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths, web_run_paths
from specgate.web_runs import ActiveRunConflict, create_run, execute_run_once, get_run
from specgate.web_settings import update_settings
from specgate.workspace_fs import WorkspacePathError


class WebRunsTests(unittest.TestCase):
    ownership_marker = ".specgate-run-owner.json"

    def make_context(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        db_path = base / "web.sqlite3"
        data_root = base / "data"
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Manual Site",
            spec_text="# Spec\nBuild a small static result page.",
            checklist_text="- Ship a complete offline HTML page.",
            index_html=None,
        )
        return db_path, data_root, user, project

    def test_recover_interrupted_initializations_removes_partial_and_complete_storage(self):
        db_path, data_root, user, partial_project = self.make_context()
        complete_project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Complete Site",
            spec_text="# Spec\nBuild another page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        with closing(connect_db(db_path)) as conn:
            partial_run_id = conn.execute(
                """
                insert into runs (project_id, user_id, status, prompt, created_at)
                values (?, ?, 'initializing', 'Partial run', '2026-07-13T00:00:00Z')
                """,
                (partial_project["id"], user["id"]),
            ).lastrowid
            complete_run_id = conn.execute(
                """
                insert into runs (project_id, user_id, status, prompt, created_at)
                values (?, ?, 'initializing', 'Complete run', '2026-07-13T00:00:00Z')
                """,
                (complete_project["id"], user["id"]),
            ).lastrowid
            conn.commit()

        partial_paths = project_paths(data_root, user["id"], partial_project["id"])
        partial_storage = web_run_paths(partial_paths, partial_run_id)
        partial_temporary_root = partial_paths.runs / f".{partial_run_id}.tmp-interrupted"
        partial_temporary_root.mkdir(parents=True)
        self.write_ownership_marker(partial_temporary_root, partial_run_id)
        (partial_temporary_root / "partial.tmp").write_text("partial", encoding="utf-8")
        complete_paths = project_paths(data_root, user["id"], complete_project["id"])
        initialize_run_storage_real(complete_paths, complete_run_id)

        web_runs.recover_interrupted_run_initializations(db_path, data_root)

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertFalse(partial_temporary_root.exists())
        self.assertFalse(partial_storage.root.exists())
        self.assertFalse(web_run_paths(complete_paths, complete_run_id).root.exists())
        partial_run = create_run(
            db_path,
            partial_project["id"],
            user["id"],
            "Replacement partial run",
            data_root=data_root,
        )
        complete_run = create_run(
            db_path,
            complete_project["id"],
            user["id"],
            "Replacement complete run",
            data_root=data_root,
        )
        self.assertEqual((partial_run["status"], complete_run["status"]), ("queued", "queued"))

    def test_recover_interrupted_initialization_retains_unowned_storage_as_failed(self):
        db_path, data_root, user, project = self.make_context()
        with closing(connect_db(db_path)) as conn:
            run_id = conn.execute(
                """
                insert into runs (project_id, user_id, status, prompt, created_at)
                values (?, ?, 'initializing', 'Interrupted run', '2026-07-13T00:00:00Z')
                """,
                (project["id"], user["id"]),
            ).lastrowid
            conn.commit()
        paths = project_paths(data_root, user["id"], project["id"])
        run_storage = web_run_paths(paths, run_id)
        run_storage.root.mkdir(parents=True)
        sentinel = run_storage.root / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        web_runs.recover_interrupted_run_initializations(db_path, data_root)

        with closing(connect_db(db_path)) as conn:
            interrupted = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
            self.assertEqual(interrupted["status"], "failed")
            self.assertEqual(interrupted["trust_level"], "failed")
            self.assertEqual(
                interrupted["error_message"],
                "Interrupted run initialization cleanup failed: unowned storage retained",
            )
            self.assertIsNotNone(interrupted["finished_at"])
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        replacement = create_run(
            db_path,
            project["id"],
            user["id"],
            "Replacement run",
            data_root=data_root,
        )
        self.assertEqual(replacement["status"], "queued")

    def test_recover_interrupted_initializations_leaves_other_active_statuses_unchanged(self):
        db_path, data_root, user, queued_project = self.make_context()
        running_project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Running Site",
            spec_text="# Spec\nBuild a running page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        approval_project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Approval Site",
            spec_text="# Spec\nBuild an approval page.",
            checklist_text="- Ship HTML.",
            index_html=None,
        )
        cases = (
            (queued_project, "queued"),
            (running_project, "running"),
            (approval_project, "needs_approval"),
        )
        expected = []
        with closing(connect_db(db_path)) as conn:
            for project, status in cases:
                run_id = conn.execute(
                    """
                    insert into runs (project_id, user_id, status, prompt, created_at)
                    values (?, ?, ?, ?, '2026-07-13T00:00:00Z')
                    """,
                    (project["id"], user["id"], status, f"{status} run"),
                ).lastrowid
                expected.append((run_id, status))
            conn.commit()
        sentinels = []
        for (project, _status), (run_id, _expected_status) in zip(cases, expected):
            run_storage = web_run_paths(project_paths(data_root, user["id"], project["id"]), run_id)
            run_storage.root.mkdir(parents=True)
            sentinel = run_storage.root / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            sentinels.append(sentinel)

        web_runs.recover_interrupted_run_initializations(db_path, data_root)

        with closing(connect_db(db_path)) as conn:
            actual = conn.execute("select id, status from runs order by id").fetchall()
            self.assertEqual([(row["id"], row["status"]) for row in actual], expected)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertTrue(all(path.read_text(encoding="utf-8") == "keep" for path in sentinels))

    def test_recovery_skips_locked_initialization_then_cleans_after_release(self):
        db_path, data_root, user, project = self.make_context()
        with closing(connect_db(db_path)) as conn:
            run_id = conn.execute(
                """
                insert into runs (project_id, user_id, status, prompt, created_at)
                values (?, ?, 'initializing', 'Interrupted run', '2026-07-13T00:00:00Z')
                """,
                (project["id"], user["id"]),
            ).lastrowid
            conn.commit()
        paths = project_paths(data_root, user["id"], project["id"])
        run = initialize_run_storage_real(paths, run_id)
        owner_lock = run_storage.RunInitializationLock(paths, run_id)
        owner_lock.acquire()
        try:
            web_runs.recover_interrupted_run_initializations(db_path, data_root)
            with closing(connect_db(db_path)) as conn:
                self.assertEqual(conn.execute("select status from runs").fetchone()[0], "initializing")
            self.assertTrue(run.root.is_dir())
        finally:
            owner_lock.release()

        web_runs.recover_interrupted_run_initializations(db_path, data_root)

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
        self.assertFalse(run.root.exists())

    def test_recovery_rechecks_initializing_status_after_lock_acquisition(self):
        db_path, data_root, user, project = self.make_context()
        with closing(connect_db(db_path)) as conn:
            run_id = conn.execute(
                """
                insert into runs (project_id, user_id, status, prompt, created_at)
                values (?, ?, 'initializing', 'Racing run', '2026-07-13T00:00:00Z')
                """,
                (project["id"], user["id"]),
            ).lastrowid
            conn.commit()
        paths = project_paths(data_root, user["id"], project["id"])
        run = initialize_run_storage_real(paths, run_id)
        acquisition_started = threading.Event()
        allow_acquisition = threading.Event()
        original_try_acquire = run_storage.RunInitializationLock.try_acquire

        def delayed_try_acquire(lock):
            acquisition_started.set()
            if not allow_acquisition.wait(timeout=5):
                raise TimeoutError("test did not allow lock acquisition")
            return original_try_acquire(lock)

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.object(
                run_storage.RunInitializationLock,
                "try_acquire",
                autospec=True,
                side_effect=delayed_try_acquire,
            ):
                recovery = executor.submit(
                    web_runs.recover_interrupted_run_initializations,
                    db_path,
                    data_root,
                )
                self.assertTrue(acquisition_started.wait(timeout=2))
                with closing(connect_db(db_path)) as conn:
                    conn.execute("update runs set status = 'queued' where id = ?", (run_id,))
                    conn.commit()
                allow_acquisition.set()
                recovery.result(timeout=2)

        with closing(connect_db(db_path)) as conn:
            status = conn.execute("select status from runs where id = ?", (run_id,)).fetchone()[0]
            self.assertEqual(status, "queued")
        self.assertTrue(run.root.is_dir())

    def test_create_run_records_queued_status_and_user_message(self):
        db_path, data_root, user, project = self.make_context()

        run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Build the result",
            data_root=data_root,
        )

        self.assertIsInstance(run, sqlite3.Row)
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["prompt"], "Build the result")
        self.assertEqual(run["project_id"], project["id"])
        self.assertEqual(run["user_id"], user["id"])

        with closing(connect_db(db_path)) as conn:
            message = conn.execute(
                "select project_id, user_id, role, content from messages where project_id = ?",
                (project["id"],),
            ).fetchone()

        self.assertEqual(message["project_id"], project["id"])
        self.assertEqual(message["user_id"], user["id"])
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"], "Build the result")
        run_paths = web_run_paths(project_paths(data_root, user["id"], project["id"]), run["id"])
        self.assertTrue(run_paths.workspace.is_dir())
        self.assertTrue(run_paths.audit.is_dir())
        self.assertTrue(run_paths.artifacts.is_dir())

        with self.assertRaises(ValueError):
            create_run(db_path, project["id"], user["id"], "   ", data_root=data_root)

    def test_create_run_rejects_full_quarantine_parent_before_db_or_storage_creation(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        sentinel = paths.root / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        for index in range(workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT):
            (paths.root / workspace_fs.make_quarantine_name(f"old-{index}")).mkdir()

        with self.assertRaisesRegex(run_storage.RunStorageQuotaError, "quota exceeded"):
            create_run(
                db_path,
                project["id"],
                user["id"],
                "Build the result",
                data_root=data_root,
            )

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(
            [path.name for path in paths.runs.iterdir() if path.name.startswith(".1")],
            [],
        )

    def test_create_run_holds_runs_quota_guard_from_preflight_through_storage_creation(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        for index in range(workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT - 1):
            (paths.runs / workspace_fs.make_quarantine_name(f"old-{index}")).mkdir()
        initialize_run_storage_real(paths, 99)

        initialization_started = threading.Event()
        release_initialization = threading.Event()
        cleanup_finished = threading.Event()

        def controlled_initialize(project_paths_value, run_id):
            initialization_started.set()
            if not release_initialization.wait(timeout=5):
                raise TimeoutError("test did not release run initialization")
            return initialize_run_storage_real(project_paths_value, run_id)

        def consume_last_slot():
            run_storage.remove_run_storage(paths, 99)
            cleanup_finished.set()

        with patch("specgate.web_runs.initialize_run_storage", side_effect=controlled_initialize):
            with ThreadPoolExecutor(max_workers=2) as executor:
                creation = executor.submit(
                    create_run,
                    db_path,
                    project["id"],
                    user["id"],
                    "Build the result",
                    data_root=data_root,
                )
                self.assertTrue(initialization_started.wait(timeout=5))
                cleanup = executor.submit(consume_last_slot)
                self.assertFalse(cleanup_finished.wait(timeout=0.2))
                release_initialization.set()
                created = creation.result(timeout=5)
                cleanup.result(timeout=5)

        self.assertEqual(created["status"], "queued")
        binding = workspace_fs.bind_workspace_tree(paths.runs)
        self.assertIsNotNone(binding)
        self.assertEqual(
            workspace_fs.count_quarantine_entries(binding),
            workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT,
        )

    def test_create_run_requires_data_root(self):
        db_path, _data_root, user, project = self.make_context()

        with self.assertRaises(TypeError):
            create_run(db_path, project["id"], user["id"], "Build the result")

    def test_create_run_rejects_active_statuses_without_side_effects(self):
        for status in ("initializing", "queued", "running", "needs_approval", "publishing"):
            with self.subTest(status=status):
                db_path, data_root, user, project = self.make_context()
                first = create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "First run",
                    data_root=data_root,
                )
                with closing(connect_db(db_path)) as conn:
                    conn.execute("update runs set status = ? where id = ?", (status, first["id"]))
                    conn.commit()

                with self.assertRaises(ActiveRunConflict):
                    create_run(
                        db_path,
                        project["id"],
                        user["id"],
                        "Conflicting run",
                        data_root=data_root,
                    )

                project_run_root = project_paths(data_root, user["id"], project["id"]).runs
                with closing(connect_db(db_path)) as conn:
                    run_count = conn.execute(
                        "select count(*) from runs where project_id = ?",
                        (project["id"],),
                    ).fetchone()[0]
                    message_count = conn.execute(
                        "select count(*) from messages where project_id = ?",
                        (project["id"],),
                    ).fetchone()[0]
                self.assertEqual(run_count, 1)
                self.assertEqual(message_count, 1)
                self.assertEqual(
                    sorted(path.name for path in project_run_root.iterdir() if path.is_dir()),
                    [str(first["id"])],
                )

    def test_create_run_during_publishing_does_not_snapshot_workspace(self):
        db_path, data_root, user, project = self.make_context()
        first = create_run(
            db_path,
            project["id"],
            user["id"],
            "First run",
            data_root=data_root,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute("update runs set status = 'publishing' where id = ?", (first["id"],))
            conn.commit()

        with patch("specgate.web_runs.initialize_run_storage") as initialize_storage:
            with self.assertRaises(ActiveRunConflict):
                create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Conflicting run",
                    data_root=data_root,
                )

        initialize_storage.assert_not_called()

    def test_create_run_allows_different_projects_concurrently(self):
        db_path, data_root, user, first_project = self.make_context()
        second_project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Second Site",
            spec_text="# Spec\nBuild another page.",
            checklist_text="- Ship another HTML page.",
            index_html=None,
        )
        barrier = threading.Barrier(2)

        def create_for(project, prompt):
            barrier.wait()
            return create_run(
                db_path,
                project["id"],
                user["id"],
                prompt,
                data_root=data_root,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(create_for, first_project, "First project run"),
                executor.submit(create_for, second_project, "Second project run"),
            ]
            runs = [future.result() for future in futures]

        self.assertEqual({run["project_id"] for run in runs}, {first_project["id"], second_project["id"]})
        for run in runs:
            paths = project_paths(data_root, user["id"], run["project_id"])
            self.assertTrue(web_run_paths(paths, run["id"]).workspace.is_dir())

    def test_create_run_serializes_same_project_competitors(self):
        db_path, data_root, user, project = self.make_context()
        barrier = threading.Barrier(2)

        def compete(prompt):
            barrier.wait()
            try:
                return create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    prompt,
                    data_root=data_root,
                )
            except ActiveRunConflict as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(compete, ("First competitor", "Second competitor")))

        successful_runs = [result for result in results if isinstance(result, sqlite3.Row)]
        conflicts = [result for result in results if isinstance(result, ActiveRunConflict)]
        self.assertEqual(len(successful_runs), 1)
        self.assertEqual(len(conflicts), 1)

        paths = project_paths(data_root, user["id"], project["id"])
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 1)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 1)
        self.assertEqual(
            sorted(path.name for path in paths.runs.iterdir() if path.is_dir()),
            [str(successful_runs[0]["id"])],
        )

    def test_create_run_preserves_preexisting_run_storage_on_initialization_conflict(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        existing_run = web_run_paths(paths, 1)
        existing_run.root.mkdir(parents=True)
        sentinel = existing_run.root / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            create_run(
                db_path,
                project["id"],
                user["id"],
                "Build the result",
                data_root=data_root,
            )

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        contender = run_storage.RunInitializationLock(paths, 1)
        self.assertTrue(contender.try_acquire())
        contender.release()

    def test_create_run_does_not_claim_preexisting_formal_storage_with_matching_marker(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        existing_run = web_run_paths(paths, 1)
        existing_run.root.mkdir(parents=True)
        self.write_ownership_marker(existing_run.root, 1)
        sentinel = existing_run.root / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            create_run(
                db_path,
                project["id"],
                user["id"],
                "Build the result",
                data_root=data_root,
            )

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_create_run_cleans_owned_storage_when_queue_transaction_fails(self):
        db_path, data_root, user, project = self.make_context()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_run_message before insert on messages
                begin
                    select raise(abort, 'message insert failed');
                end
                """
            )
            conn.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "message insert failed"):
            create_run(
                db_path,
                project["id"],
                user["id"],
                "Build the result",
                data_root=data_root,
            )

        paths = project_paths(data_root, user["id"], project["id"])
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)
        self.assertFalse(web_run_paths(paths, 1).root.exists())
        quarantines = list(paths.runs.glob(".1.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertTrue((quarantines[0] / self.ownership_marker).is_file())

    def test_create_run_preserves_diagnostic_row_when_owned_storage_cleanup_fails(self):
        db_path, data_root, user, project = self.make_context()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_run_message before insert on messages
                begin
                    select raise(abort, 'message insert failed');
                end
                """
            )
            conn.commit()

        with patch("specgate.web_runs.remove_run_storage", side_effect=OSError("cleanup failed")):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "message insert failed") as raised:
                create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Build the result",
                    data_root=data_root,
                )

        self.assertTrue(any("cleanup failed" in note for note in raised.exception.__notes__))
        with closing(connect_db(db_path)) as conn:
            run = conn.execute("select * from runs").fetchone()
            self.assertIsNotNone(run)
            self.assertIn(run["status"], {"initializing", "failed"})
            self.assertIn("cleanup failed", run["error_message"])
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)

    def test_create_run_keeps_owned_partial_storage_recoverable_when_initial_cleanup_fails(self):
        db_path, data_root, user, project = self.make_context()

        with (
            patch(
                "specgate.workspace_fs._rename_staging_noreplace",
                side_effect=OSError("copy failed"),
            ),
            patch(
                "specgate.run_storage.rename_workspace_tree_noreplace",
                side_effect=OSError("cleanup failed"),
            ),
        ):
            with self.assertRaises(WorkspacePathError) as raised:
                create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Build the result",
                    data_root=data_root,
                )
        self.assertEqual(raised.exception.rule_family, "path_race")

        paths = project_paths(data_root, user["id"], project["id"])
        temporary_roots = list(paths.runs.glob(".1.specgate-copy-*"))
        self.assertEqual(len(temporary_roots), 1)
        self.assertTrue((temporary_roots[0] / self.ownership_marker).is_file())
        with closing(connect_db(db_path)) as conn:
            interrupted = conn.execute("select * from runs").fetchone()
            self.assertEqual(interrupted["status"], "initializing")
            self.assertIn("cleanup failed", interrupted["error_message"])
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 0)

        web_runs.recover_interrupted_run_initializations(db_path, data_root)

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)
        self.assertEqual(
            [
                path
                for path in paths.runs.glob(".1.specgate-copy-*")
                if workspace_fs.QUARANTINE_NAME_MARKER not in path.name
            ],
            [],
        )

    def test_slow_initialization_does_not_hold_write_lock_across_projects(self):
        db_path, data_root, user, first_project = self.make_context()
        second_project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Second Site",
            spec_text="# Spec\nBuild another page.",
            checklist_text="- Ship another HTML page.",
            index_html=None,
        )
        first_paths = project_paths(data_root, user["id"], first_project["id"])
        initialization_started = threading.Event()
        release_initialization = threading.Event()

        def controlled_initialize(paths, run_id):
            if paths.root == first_paths.root:
                initialization_started.set()
                if not release_initialization.wait(timeout=5):
                    raise TimeoutError("test did not release initialization")
            return initialize_run_storage_real(paths, run_id)

        executor = ThreadPoolExecutor(max_workers=2)
        try:
            with patch("specgate.web_runs.initialize_run_storage", side_effect=controlled_initialize):
                first_future = executor.submit(
                    create_run,
                    db_path,
                    first_project["id"],
                    user["id"],
                    "First project run",
                    data_root=data_root,
                )
                self.assertTrue(initialization_started.wait(timeout=2))
                second_future = executor.submit(
                    create_run,
                    db_path,
                    second_project["id"],
                    user["id"],
                    "Second project run",
                    data_root=data_root,
                )
                second_run = second_future.result(timeout=2)
                self.assertEqual(second_run["status"], "queued")
                release_initialization.set()
                first_run = first_future.result(timeout=2)
        finally:
            release_initialization.set()
            executor.shutdown(wait=True)

        self.assertEqual(first_run["status"], "queued")

    def test_initializing_run_rejects_same_project_before_storage_finishes(self):
        db_path, data_root, user, project = self.make_context()
        initialization_started = threading.Event()
        release_initialization = threading.Event()

        def controlled_initialize(paths, run_id):
            initialization_started.set()
            contender = run_storage.RunInitializationLock(paths, run_id)
            self.assertFalse(contender.try_acquire())
            if not release_initialization.wait(timeout=5):
                raise TimeoutError("test did not release initialization")
            return initialize_run_storage_real(paths, run_id)

        executor = ThreadPoolExecutor(max_workers=2)
        try:
            with patch("specgate.web_runs.initialize_run_storage", side_effect=controlled_initialize):
                first_future = executor.submit(
                    create_run,
                    db_path,
                    project["id"],
                    user["id"],
                    "First run",
                    data_root=data_root,
                )
                self.assertTrue(initialization_started.wait(timeout=2))
                second_future = executor.submit(
                    create_run,
                    db_path,
                    project["id"],
                    user["id"],
                    "Conflicting run",
                    data_root=data_root,
                )
                with self.assertRaises(ActiveRunConflict):
                    second_future.result(timeout=2)
                release_initialization.set()
                run = first_future.result(timeout=2)
        finally:
            release_initialization.set()
            executor.shutdown(wait=True)

        paths = project_paths(data_root, user["id"], project["id"])
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 1)
            self.assertEqual(conn.execute("select count(*) from messages").fetchone()[0], 1)
            self.assertEqual(conn.execute("select status from runs").fetchone()[0], "queued")
        self.assertEqual(
            sorted(path.name for path in paths.runs.iterdir() if path.is_dir()),
            [str(run["id"])],
        )

    def test_get_run_rejects_other_user(self):
        db_path, data_root, user, project = self.make_context()
        other = create_user(db_path, "bob", "correct-password")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        self.assertEqual(get_run(db_path, user["id"], run["id"])["id"], run["id"])
        with self.assertRaises(ValueError):
            get_run(db_path, other["id"], run["id"])

    def write_ownership_marker(self, root, run_id):
        (root / self.ownership_marker).write_text(
            json.dumps({"run_id": run_id, "schema_version": 1}, sort_keys=True),
            encoding="utf-8",
        )

    def test_execute_run_once_publishes_index_and_zip_artifacts(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        paths = project_paths(data_root, user["id"], project["id"])
        run_paths = web_run_paths(paths, run["id"])
        latest_index = run_paths.index_artifact
        result_zip = run_paths.zip_artifact

        self.assertIn(updated["status"], {"completed", "failed", "needs_approval"})
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["index_artifact_path"], str(latest_index))
        self.assertEqual(updated["zip_artifact_path"], str(result_zip))
        self.assertTrue(latest_index.is_file())
        self.assertTrue(result_zip.is_file())
        self.assertIn("SpecGate Result", latest_index.read_text(encoding="utf-8"))
        self.assertTrue((run_paths.audit / "publication-manifest.json").is_file())
        self.assertFalse((paths.artifacts / "latest-index.html").exists())
        self.assertFalse((paths.artifacts / "result.zip").exists())
        self.assertEqual((paths.workspace / "index.html").read_bytes(), latest_index.read_bytes())

        with closing(connect_db(db_path)) as conn:
            artifacts = conn.execute(
                "select kind, path from artifacts where run_id = ? order by kind",
                (run["id"],),
            ).fetchall()

        self.assertEqual(
            [(row["kind"], row["path"]) for row in artifacts],
            [("index", str(latest_index)), ("zip", str(result_zip))],
        )

    def test_publish_artifacts_rejects_mocked_reparse_artifact_root(self):
        _db_path, data_root, user, project = self.make_context()
        project_storage = project_paths(data_root, user["id"], project["id"])
        paths = initialize_run_storage_real(project_storage, 99)
        (paths.workspace / "index.html").write_text("trusted", encoding="utf-8")
        real_is_link_like = workspace_fs.is_link_like

        def mark_artifacts_reparse(path):
            if Path(path) == paths.artifacts:
                return True
            return real_is_link_like(path)

        with patch(
            "specgate.workspace_fs.is_link_like",
            side_effect=mark_artifacts_reparse,
        ):
            with self.assertRaises(WorkspacePathError) as raised:
                web_runs._publish_artifacts(paths)

        self.assertEqual(raised.exception.rule_family, "reparse_point")
        self.assertFalse(paths.index_artifact.exists())
        self.assertFalse(paths.zip_artifact.exists())

    def test_completed_run_is_prepared_as_publishing_before_workspace_promotion(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        observed = {}

        def inspect_then_promote(project_storage, run_id):
            with closing(connect_db(db_path)) as conn:
                row = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
                artifacts = conn.execute(
                    "select kind, path from artifacts where run_id = ? order by kind",
                    (run_id,),
                ).fetchall()
            observed["status"] = row["status"]
            observed["finished_at"] = row["finished_at"]
            observed["error_message"] = row["error_message"]
            observed["artifacts"] = [(item["kind"], item["path"]) for item in artifacts]
            promote_run_workspace_real(project_storage, run_id)

        with patch("specgate.web_runs.promote_run_workspace", side_effect=inspect_then_promote):
            execute_run_once(db_path, data_root, run["id"])

        run_paths = web_run_paths(project_paths(data_root, user["id"], project["id"]), run["id"])
        self.assertEqual(observed["status"], "publishing")
        self.assertIsNone(observed["finished_at"])
        self.assertIsNone(observed["error_message"])
        self.assertEqual(
            observed["artifacts"],
            [("index", str(run_paths.index_artifact)), ("zip", str(run_paths.zip_artifact))],
        )
        self.assertEqual(get_run(db_path, user["id"], run["id"])["status"], "completed")

    def test_completed_run_holds_publication_lock_across_prepare_promote_finalize(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        project_storage = project_paths(data_root, user["id"], project["id"])
        original_prepare = web_runs._prepare_run_publication
        lock_observations = []

        def inspect_then_prepare(*args, **kwargs):
            contender = run_storage.RunPublicationLock(project_storage, run["id"])
            lock_observations.append(contender.try_acquire())
            contender.release()
            return original_prepare(*args, **kwargs)

        with patch("specgate.web_runs._prepare_run_publication", side_effect=inspect_then_prepare):
            execute_run_once(db_path, data_root, run["id"])

        self.assertEqual(lock_observations, [False])
        contender = run_storage.RunPublicationLock(project_storage, run["id"])
        self.assertTrue(contender.try_acquire())
        contender.release()

    def test_execute_run_once_uses_user_governance_and_context_settings(self):
        db_path, data_root, user, project = self.make_context()
        update_settings(
            db_path,
            user["id"],
            governance_profile="strict",
            context_strategy="rag-select",
        )
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        execute_run_once(db_path, data_root, run["id"])

        paths = project_paths(data_root, user["id"], project["id"])
        run_paths = web_run_paths(paths, run["id"])
        trace_text = (run_paths.audit / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn('"strategy": "rag-select"', trace_text)
        self.assertIn('"profile": "strict"', trace_text)
        self.assertFalse((paths.workspace / "runs" / "latest").exists())

    def test_execute_run_once_failure_marks_run_failed_when_index_is_missing(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        class FinishOnlyLLM:
            def __init__(self, responses):
                pass

            def complete(self, context):
                return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'

        with patch("specgate.web_runs.MockLLM", FinishOnlyLLM):
            execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        paths = project_paths(data_root, user["id"], project["id"])
        run_paths = web_run_paths(paths, run["id"])

        self.assertEqual(updated["status"], "failed")
        self.assertIsNotNone(updated["finished_at"])
        self.assertEqual(updated["error_message"], "Run did not produce index.html")
        self.assertIsNone(updated["index_artifact_path"])
        self.assertFalse(run_paths.index_artifact.exists())

    def test_execute_run_once_does_not_publish_stale_index_from_previous_state(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        paths = project_paths(data_root, user["id"], project["id"])
        run_paths = web_run_paths(paths, run["id"])
        old_html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Old Result</title>
</head>
<body>
  <h1>Old Result</h1>
  <input type="search" aria-label="Filter" placeholder="Filter">
</body>
</html>
        """
        (run_paths.workspace / "index.html").write_text(old_html, encoding="utf-8")
        stale_index_path = run_paths.artifacts / "old-index.html"
        stale_zip_path = run_paths.artifacts / "old-result.zip"
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set index_artifact_path = ?, zip_artifact_path = ? where id = ?",
                (str(stale_index_path), str(stale_zip_path), run["id"]),
            )
            conn.execute(
                "insert into artifacts (run_id, kind, path) values (?, ?, ?)",
                (run["id"], "index", str(stale_index_path)),
            )
            conn.execute(
                "insert into artifacts (run_id, kind, path) values (?, ?, ?)",
                (run["id"], "zip", str(stale_zip_path)),
            )
            conn.commit()

        class FinishOnlyLLM:
            def __init__(self, responses):
                pass

            def complete(self, context):
                return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'

        with patch("specgate.web_runs.MockLLM", FinishOnlyLLM):
            execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["error_message"], "Run did not produce index.html")
        self.assertIsNone(updated["index_artifact_path"])
        self.assertIsNone(updated["zip_artifact_path"])
        self.assertFalse(run_paths.index_artifact.exists())
        self.assertFalse(run_paths.zip_artifact.exists())
        with closing(connect_db(db_path)) as conn:
            artifact_count = conn.execute(
                "select count(*) from artifacts where run_id = ?",
                (run["id"],),
            ).fetchone()[0]
        self.assertEqual(artifact_count, 0)

    def test_execute_run_once_ignores_runs_that_are_not_queued(self):
        db_path, data_root, user, project = self.make_context()
        completed_run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Build the result",
            data_root=data_root,
        )
        execute_run_once(db_path, data_root, completed_run["id"])
        completed_before = get_run(db_path, user["id"], completed_run["id"])
        paths = project_paths(data_root, user["id"], project["id"])
        completed_paths = web_run_paths(paths, completed_run["id"])
        index_before = completed_paths.index_artifact.read_text(encoding="utf-8")

        running_run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Second result",
            data_root=data_root,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute("update runs set status = 'running' where id = ?", (running_run["id"],))
            conn.commit()

        class FailsIfCalledLLM:
            def __init__(self, responses):
                pass

            def complete(self, context):
                raise AssertionError("non-queued run was executed")

        with patch("specgate.web_runs.MockLLM", FailsIfCalledLLM):
            execute_run_once(db_path, data_root, completed_run["id"])
            execute_run_once(db_path, data_root, running_run["id"])

        completed_after = get_run(db_path, user["id"], completed_run["id"])
        running_after = get_run(db_path, user["id"], running_run["id"])

        self.assertEqual(completed_after["status"], "completed")
        self.assertEqual(completed_after["index_artifact_path"], completed_before["index_artifact_path"])
        self.assertEqual(completed_after["zip_artifact_path"], completed_before["zip_artifact_path"])
        self.assertEqual(completed_paths.index_artifact.read_text(encoding="utf-8"), index_before)
        self.assertEqual(running_after["status"], "running")
        self.assertIsNone(running_after["index_artifact_path"])
        self.assertIsNone(running_after["zip_artifact_path"])

    def test_completed_runs_keep_immutable_artifacts_and_audit(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        run1 = create_run(db_path, project["id"], user["id"], "First result", data_root=data_root)

        execute_run_once(db_path, data_root, run1["id"])

        run1_row = get_run(db_path, user["id"], run1["id"])
        run1_paths = web_run_paths(paths, run1["id"])
        run1_index = run1_paths.index_artifact.read_bytes()
        run1_zip = run1_paths.zip_artifact.read_bytes()
        run1_trace = (run1_paths.audit / "trace.jsonl").read_bytes()
        run2 = create_run(db_path, project["id"], user["id"], "Second result", data_root=data_root)
        run2_paths = web_run_paths(paths, run2["id"])
        self.assertEqual((run2_paths.workspace / "index.html").read_bytes(), run1_index)

        execute_run_once(db_path, data_root, run2["id"])

        run2_row = get_run(db_path, user["id"], run2["id"])
        self.assertEqual(run1_paths.index_artifact.read_bytes(), run1_index)
        self.assertEqual(run1_paths.zip_artifact.read_bytes(), run1_zip)
        self.assertEqual((run1_paths.audit / "trace.jsonl").read_bytes(), run1_trace)
        self.assertEqual(run1_row["index_artifact_path"], str(run1_paths.index_artifact))
        self.assertEqual(run2_row["index_artifact_path"], str(run2_paths.index_artifact))
        self.assertNotEqual(run1_row["index_artifact_path"], run2_row["index_artifact_path"])

    def test_workspace_promotion_failure_marks_run_failed_without_completed_record(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        with patch("specgate.web_runs.promote_run_workspace", side_effect=RuntimeError("promotion failed")):
            execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "failed")
        self.assertIn("promotion failed", updated["error_message"])
        self.assertIsNone(updated["index_artifact_path"])
        self.assertIsNone(updated["zip_artifact_path"])
        self.assertEqual((paths.workspace / "index.html").read_text(encoding="utf-8"), "old workspace")
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(
                conn.execute("select count(*) from artifacts where run_id = ?", (run["id"],)).fetchone()[0],
                0,
            )

    def test_post_rename_source_replacement_is_quarantined_and_keeps_publishing(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        replacement = paths.root / "unknown-promotion-source"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = paths.root / "displaced-owned-next"
        real_rename = workspace_fs._platform_rename_noreplace

        def replace_source_at_publish(source, destination):
            source = Path(source)
            destination = Path(destination)
            if destination == paths.workspace and source.name.startswith("workspace.next-"):
                real_rename(source, displaced)
                real_rename(replacement, source)
            return real_rename(source, destination)

        with patch.object(
            workspace_fs,
            "_platform_rename_noreplace",
            side_effect=replace_source_at_publish,
        ):
            with self.assertRaises(workspace_fs.WorkspaceTreeRenameError):
                execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("quarantined after verification failure", updated["error_message"])
        self.assertEqual(
            (paths.workspace / "index.html").read_text(encoding="utf-8"),
            "old workspace",
        )
        self.assertFalse((paths.workspace / "sentinel.txt").exists())
        quarantines = list(paths.root.glob(".workspace.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(
            (quarantines[0] / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertTrue(displaced.is_dir())

    def test_post_rename_quarantine_failure_keeps_publishing_and_evidence(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        replacement = paths.root / "unknown-promotion-source"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = paths.root / "displaced-owned-next"
        real_rename = workspace_fs._platform_rename_noreplace

        def replace_source_and_fail_quarantine(source, destination):
            source = Path(source)
            destination = Path(destination)
            if destination == paths.workspace and source.name.startswith("workspace.next-"):
                real_rename(source, displaced)
                real_rename(replacement, source)
            if destination.name.startswith(".workspace.specgate-quarantine-"):
                raise OSError("quarantine denied")
            return real_rename(source, destination)

        with patch.object(
            workspace_fs,
            "_platform_rename_noreplace",
            side_effect=replace_source_and_fail_quarantine,
        ):
            with self.assertRaises(run_storage.RunStoragePostRenameError) as raised:
                execute_run_once(db_path, data_root, run["id"])

        self.assertIn("promotion state is uncertain", str(raised.exception))
        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("promotion state is uncertain", updated["error_message"])
        self.assertIn("could not be quarantined", updated["error_message"])
        self.assertEqual(
            (paths.workspace / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertEqual(list(paths.root.glob(".workspace.specgate-quarantine-*")), [])
        self.assertTrue(displaced.is_dir())

    def test_backup_quota_after_workspace_switch_keeps_publishing_and_recoverable(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        for index in range(workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT - 1):
            (paths.root / workspace_fs.make_quarantine_name(f"old-{index}")).mkdir()

        real_cleanup = run_storage._quarantine_committed_phase
        occupied_last_slot = False

        def occupy_last_slot_after_switch(state, token):
            nonlocal occupied_last_slot
            if not occupied_last_slot:
                occupied_last_slot = True
                (paths.root / workspace_fs.make_quarantine_name("competitor")).mkdir()
            return real_cleanup(state, token)

        with patch(
            "specgate.run_storage._quarantine_committed_phase",
            side_effect=occupy_last_slot_after_switch,
        ):
            with self.assertRaises(run_storage.RunStoragePostRenameError):
                execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("quota exceeded", updated["error_message"])
        self.assertNotEqual(
            (paths.workspace / "index.html").read_text(encoding="utf-8"),
            "old workspace",
        )
        backups = list(paths.root.glob("workspace.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "index.html").read_text(encoding="utf-8"), "old workspace")

    def test_post_rename_ownership_validation_error_stays_publishing_and_redacted(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        secret = "sk-test-secret-1234567890"

        with patch(
            "specgate.run_storage._validate_published_workspace",
            side_effect=run_storage.RunStorageOwnershipError(
                f"published ownership mismatch {secret}"
            ),
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("published ownership mismatch", updated["error_message"])
        self.assertNotIn(secret, updated["error_message"])
        with patch("specgate.web_runs.initialize_run_storage") as initialize_storage:
            with self.assertRaises(ActiveRunConflict):
                create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Conflicting run",
                    data_root=data_root,
                )
        initialize_storage.assert_not_called()

    def test_post_rename_marker_and_identity_errors_stay_publishing(self):
        failures = (
            run_storage.RunStorageOwnershipError("published marker mismatch"),
            WorkspacePathError("published identity mismatch", "path_race"),
        )
        for failure in failures:
            with self.subTest(failure=str(failure)):
                db_path, data_root, user, project = self.make_context()
                run = create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Build the result",
                    data_root=data_root,
                )
                with patch(
                    "specgate.run_storage._validate_published_workspace",
                    side_effect=failure,
                ):
                    with self.assertRaises(run_storage.RunStoragePostRenameError):
                        execute_run_once(db_path, data_root, run["id"])

                updated = get_run(db_path, user["id"], run["id"])
                self.assertEqual(updated["status"], "publishing")
                self.assertIn(str(failure), updated["error_message"])

    def test_publish_and_rollback_rename_failure_keeps_publishing_and_blocks_new_run(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        real_rename = run_storage.rename_workspace_tree_noreplace
        secret = "sk-double-failure-secret-1234567890"
        calls = 0

        def fail_publish_and_rollback(binding, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(f"publish rename failed {secret}")
            if calls == 3:
                raise OSError("rollback rename failed")
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=fail_publish_and_rollback,
        ):
            with self.assertRaises(run_storage.RunStoragePostRenameError):
                execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("promotion state is uncertain", updated["error_message"])
        self.assertNotIn(secret, updated["error_message"])
        with patch("specgate.web_runs.initialize_run_storage") as initialize_storage:
            with self.assertRaises(ActiveRunConflict):
                create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Conflicting run",
                    data_root=data_root,
                )
        initialize_storage.assert_not_called()

    def test_resume_uncertain_promotion_error_keeps_publishing_and_redacted(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        project_storage = project_paths(data_root, user["id"], project["id"])
        paths = web_run_paths(project_storage, run["id"])
        with closing(connect_db(db_path)) as conn:
            conn.execute("update runs set status = 'needs_approval' where id = ?", (run["id"],))
            conn.commit()
        queue = Mock()
        queue.next_resume_candidate.return_value = object()
        secret = "sk-resume-secret-1234567890"
        real_rename = run_storage.rename_workspace_tree_noreplace
        rename_calls = 0

        def prepare_publishing(*_args, **_kwargs):
            with closing(connect_db(db_path)) as conn:
                conn.execute("update runs set status = 'publishing' where id = ?", (run["id"],))
                conn.commit()

        def fail_publish_and_rollback(binding, destination):
            nonlocal rename_calls
            rename_calls += 1
            if rename_calls == 2:
                raise OSError(f"publish rename failed {secret}")
            if rename_calls == 3:
                raise OSError("rollback rename failed")
            return real_rename(binding, destination)

        with (
            patch("specgate.web_runs.ApprovalQueue.read", return_value=queue),
            patch("specgate.web_runs._index_signature", side_effect=[None, "changed"]),
            patch("specgate.web_runs._run_resume_agent", return_value=object()),
            patch("specgate.web_runs._publish_artifacts", return_value=(paths.index_artifact, paths.zip_artifact)),
            patch("specgate.web_runs._status_for_result", return_value="completed"),
            patch("specgate.web_runs._trust_level", return_value="trusted"),
            patch("specgate.web_runs._write_and_validate_publication_manifest"),
            patch("specgate.web_runs._prepare_run_publication", side_effect=prepare_publishing),
            patch(
                "specgate.run_storage.rename_workspace_tree_noreplace",
                side_effect=fail_publish_and_rollback,
            ),
        ):
            with self.assertRaises(run_storage.RunStoragePostRenameError):
                web_runs.resume_run_once(db_path, data_root, user["id"], run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("promotion state is uncertain", updated["error_message"])
        self.assertNotIn(secret, updated["error_message"])

    def test_finalize_failure_after_promotion_keeps_publishing_and_blocks_new_run(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_completed_run before update of status on runs
                when new.status = 'completed'
                begin
                    select raise(abort, 'finalize failed');
                end
                """
            )
            conn.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "finalize failed"):
            execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        self.assertEqual(updated["status"], "publishing")
        self.assertIn("finalize failed", updated["error_message"])
        self.assertIn("SpecGate Result", (paths.workspace / "index.html").read_text(encoding="utf-8"))
        self.assertIsNotNone(updated["index_artifact_path"])
        self.assertIsNotNone(updated["zip_artifact_path"])
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(
                conn.execute("select count(*) from artifacts where run_id = ?", (run["id"],)).fetchone()[0],
                2,
            )
        with self.assertRaises(ActiveRunConflict):
            create_run(
                db_path,
                project["id"],
                user["id"],
                "Conflicting run",
                data_root=data_root,
            )

    def test_recover_publication_after_prepare_promotes_and_completes(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        with patch("specgate.web_runs.promote_run_workspace", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaisesRegex(KeyboardInterrupt, "interrupted"):
                execute_run_once(db_path, data_root, run["id"])

        self.assertEqual(get_run(db_path, user["id"], run["id"])["status"], "publishing")
        self.assertEqual((paths.workspace / "index.html").read_text(encoding="utf-8"), "old workspace")

        web_runs.recover_interrupted_run_publications(db_path, data_root)

        recovered = get_run(db_path, user["id"], run["id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertIsNotNone(recovered["finished_at"])
        self.assertIsNone(recovered["error_message"])
        self.assertIn("SpecGate Result", (paths.workspace / "index.html").read_text(encoding="utf-8"))

    def test_prepare_writes_atomic_publication_manifest_before_publishing(self):
        db_path, data_root, user, project = self.make_context()
        project_storage = project_paths(data_root, user["id"], project["id"])
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        run_paths = web_run_paths(project_storage, run["id"])

        with patch("specgate.web_runs.promote_run_workspace", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaises(KeyboardInterrupt):
                execute_run_once(db_path, data_root, run["id"])

        manifest_path = run_paths.audit / "publication-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with zipfile.ZipFile(run_paths.zip_artifact) as archive:
            zip_index = archive.read("index.html")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["run_id"], run["id"])
        self.assertEqual(manifest["ownership"], {"run_id": run["id"], "schema_version": 1})
        self.assertEqual(
            manifest["workspace_index_sha256"],
            hashlib.sha256((run_paths.workspace / "index.html").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["index_artifact_sha256"],
            hashlib.sha256(run_paths.index_artifact.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["zip_artifact_sha256"],
            hashlib.sha256(run_paths.zip_artifact.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["zip_index_sha256"], hashlib.sha256(zip_index).hexdigest())
        self.assertFalse((run_paths.audit / "publication-manifest.json.tmp").exists())

    def test_recover_publication_skips_held_lock_then_recovers_after_release(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        with patch("specgate.web_runs.promote_run_workspace", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaises(KeyboardInterrupt):
                execute_run_once(db_path, data_root, run["id"])
        publication_lock = run_storage.RunPublicationLock(paths, run["id"])
        publication_lock.acquire()
        try:
            web_runs.recover_interrupted_run_publications(db_path, data_root)
            self.assertEqual(get_run(db_path, user["id"], run["id"])["status"], "publishing")
        finally:
            publication_lock.release()

        web_runs.recover_interrupted_run_publications(db_path, data_root)

        self.assertEqual(get_run(db_path, user["id"], run["id"])["status"], "completed")

    def test_recover_publication_rechecks_status_after_lock_acquisition(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        with patch("specgate.web_runs.promote_run_workspace", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaises(KeyboardInterrupt):
                execute_run_once(db_path, data_root, run["id"])
        acquisition_started = threading.Event()
        allow_acquisition = threading.Event()
        original_try_acquire = run_storage.RunPublicationLock.try_acquire

        def delayed_try_acquire(lock):
            acquisition_started.set()
            if not allow_acquisition.wait(timeout=5):
                raise TimeoutError("test did not allow publication lock acquisition")
            return original_try_acquire(lock)

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.object(
                run_storage.RunPublicationLock,
                "try_acquire",
                autospec=True,
                side_effect=delayed_try_acquire,
            ):
                recovery = executor.submit(web_runs.recover_interrupted_run_publications, db_path, data_root)
                self.assertTrue(acquisition_started.wait(timeout=2))
                with closing(connect_db(db_path)) as conn:
                    conn.execute("update runs set status = 'completed' where id = ?", (run["id"],))
                    conn.commit()
                allow_acquisition.set()
                recovery.result(timeout=2)

        self.assertEqual((paths.workspace / "index.html").read_text(encoding="utf-8"), "old workspace")
        contender = run_storage.RunPublicationLock(paths, run["id"])
        self.assertTrue(contender.try_acquire())
        contender.release()

    def test_recover_publication_after_promotion_finalizes_completed(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_completed_run before update of status on runs
                when new.status = 'completed'
                begin
                    select raise(abort, 'finalize failed');
                end
                """
            )
            conn.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "finalize failed"):
            execute_run_once(db_path, data_root, run["id"])
        with closing(connect_db(db_path)) as conn:
            conn.execute("drop trigger reject_completed_run")
            conn.commit()

        web_runs.recover_interrupted_run_publications(db_path, data_root)

        recovered = get_run(db_path, user["id"], run["id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertIsNone(recovered["error_message"])
        self.assertIn("SpecGate Result", (paths.workspace / "index.html").read_text(encoding="utf-8"))

    def test_recover_completed_promotion_at_quarantine_limit_finalizes_without_new_slot(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        (paths.workspace / "index.html").write_text("old workspace", encoding="utf-8")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        for index in range(workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT - 1):
            (paths.root / workspace_fs.make_quarantine_name(f"old-{index}")).mkdir()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                create trigger reject_completed_run_at_limit before update of status on runs
                when new.status = 'completed'
                begin
                    select raise(abort, 'finalize failed at limit');
                end
                """
            )
            conn.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "finalize failed at limit"):
            execute_run_once(db_path, data_root, run["id"])
        binding = workspace_fs.bind_workspace_tree(paths.root)
        self.assertIsNotNone(binding)
        self.assertEqual(
            workspace_fs.count_quarantine_entries(binding),
            workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute("drop trigger reject_completed_run_at_limit")
            conn.commit()

        web_runs.recover_interrupted_run_publications(db_path, data_root)

        recovered = get_run(db_path, user["id"], run["id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertIsNone(recovered["error_message"])
        self.assertIn("SpecGate Result", (paths.workspace / "index.html").read_text(encoding="utf-8"))

    def test_recover_publication_error_stays_active_with_safe_diagnostic(self):
        db_path, data_root, user, project = self.make_context()
        paths = project_paths(data_root, user["id"], project["id"])
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        with patch("specgate.web_runs.promote_run_workspace", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaises(KeyboardInterrupt):
                execute_run_once(db_path, data_root, run["id"])
        web_run_paths(paths, run["id"]).zip_artifact.unlink()

        web_runs.recover_interrupted_run_publications(db_path, data_root)

        recovered = get_run(db_path, user["id"], run["id"])
        self.assertEqual(recovered["status"], "publishing")
        self.assertIn("result.zip", recovered["error_message"])
        with self.assertRaises(ActiveRunConflict):
            create_run(db_path, project["id"], user["id"], "Blocked run", data_root=data_root)

    def test_recover_publication_rejects_tampered_storage_and_manifest(self):
        tamper_cases = ("workspace", "artifact", "zip", "manifest", "marker")
        for tamper_case in tamper_cases:
            with self.subTest(tamper_case=tamper_case):
                db_path, data_root, user, project = self.make_context()
                project_storage = project_paths(data_root, user["id"], project["id"])
                (project_storage.workspace / "index.html").write_text("old workspace", encoding="utf-8")
                run = create_run(
                    db_path,
                    project["id"],
                    user["id"],
                    "Build the result",
                    data_root=data_root,
                )
                run_paths = web_run_paths(project_storage, run["id"])
                with patch(
                    "specgate.web_runs.promote_run_workspace",
                    side_effect=KeyboardInterrupt("interrupted"),
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        execute_run_once(db_path, data_root, run["id"])

                if tamper_case == "workspace":
                    (run_paths.workspace / "index.html").write_text("tampered", encoding="utf-8")
                elif tamper_case == "artifact":
                    run_paths.index_artifact.write_text("tampered", encoding="utf-8")
                elif tamper_case == "zip":
                    run_paths.zip_artifact.write_bytes(b"not a zip")
                elif tamper_case == "manifest":
                    manifest_path = run_paths.audit / "publication-manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["run_id"] = run["id"] + 1
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                else:
                    (run_paths.root / self.ownership_marker).write_text(
                        json.dumps({"run_id": run["id"] + 1, "schema_version": 1}),
                        encoding="utf-8",
                    )

                web_runs.recover_interrupted_run_publications(db_path, data_root)

                recovered = get_run(db_path, user["id"], run["id"])
                self.assertEqual(recovered["status"], "publishing")
                self.assertIsNotNone(recovered["error_message"])
                self.assertEqual(
                    (project_storage.workspace / "index.html").read_text(encoding="utf-8"),
                    "old workspace",
                )


if __name__ == "__main__":
    unittest.main()
