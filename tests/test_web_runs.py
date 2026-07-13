import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from specgate.run_storage import initialize_run_storage as initialize_run_storage_real
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths, web_run_paths
from specgate.web_runs import ActiveRunConflict, create_run, execute_run_once, get_run
from specgate.web_settings import update_settings


class WebRunsTests(unittest.TestCase):
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

    def test_create_run_rejects_active_statuses_without_side_effects(self):
        for status in ("queued", "running", "needs_approval"):
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
                    sorted(path.name for path in project_run_root.iterdir()),
                    [str(first["id"])],
                )

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

    def test_create_run_rolls_back_database_and_storage_when_initialization_fails(self):
        db_path, data_root, user, project = self.make_context()

        def fail_after_initialization(paths, run_id):
            initialize_run_storage_real(paths, run_id)
            raise OSError("storage initialization failed")

        with patch("specgate.web_runs.initialize_run_storage", side_effect=fail_after_initialization):
            with self.assertRaisesRegex(OSError, "storage initialization failed"):
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
        self.assertEqual(list(paths.runs.iterdir()), [])

    def test_get_run_rejects_other_user(self):
        db_path, data_root, user, project = self.make_context()
        other = create_user(db_path, "bob", "correct-password")
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        self.assertEqual(get_run(db_path, user["id"], run["id"])["id"], run["id"])
        with self.assertRaises(ValueError):
            get_run(db_path, other["id"], run["id"])

    def test_execute_run_once_publishes_index_and_zip_artifacts(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)

        execute_run_once(db_path, data_root, run["id"])

        updated = get_run(db_path, user["id"], run["id"])
        paths = project_paths(data_root, user["id"], project["id"])
        latest_index = paths.artifacts / "latest-index.html"
        result_zip = paths.artifacts / "result.zip"

        self.assertIn(updated["status"], {"completed", "failed", "needs_approval"})
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["index_artifact_path"], str(latest_index))
        self.assertEqual(updated["zip_artifact_path"], str(result_zip))
        self.assertTrue(latest_index.is_file())
        self.assertTrue(result_zip.is_file())
        self.assertIn("SpecGate Result", latest_index.read_text(encoding="utf-8"))

        with closing(connect_db(db_path)) as conn:
            artifacts = conn.execute(
                "select kind, path from artifacts where run_id = ? order by kind",
                (run["id"],),
            ).fetchall()

        self.assertEqual(
            [(row["kind"], row["path"]) for row in artifacts],
            [("index", str(latest_index)), ("zip", str(result_zip))],
        )

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
        trace_text = (paths.workspace / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn('"strategy": "rag-select"', trace_text)
        self.assertIn('"profile": "strict"', trace_text)

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

        self.assertEqual(updated["status"], "failed")
        self.assertIsNotNone(updated["finished_at"])
        self.assertEqual(updated["error_message"], "Run did not produce index.html")
        self.assertIsNone(updated["index_artifact_path"])
        self.assertFalse((paths.artifacts / "latest-index.html").exists())

    def test_execute_run_once_does_not_publish_stale_index_from_previous_state(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result", data_root=data_root)
        paths = project_paths(data_root, user["id"], project["id"])
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
        (paths.workspace / "index.html").write_text(old_html, encoding="utf-8")
        stale_index_path = paths.artifacts / "old-index.html"
        stale_zip_path = paths.artifacts / "old-result.zip"
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
        self.assertFalse((paths.artifacts / "latest-index.html").exists())
        self.assertFalse((paths.artifacts / "result.zip").exists())
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
        index_before = (paths.artifacts / "latest-index.html").read_text(encoding="utf-8")

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
        self.assertEqual((paths.artifacts / "latest-index.html").read_text(encoding="utf-8"), index_before)
        self.assertEqual(running_after["status"], "running")
        self.assertIsNone(running_after["index_artifact_path"])
        self.assertIsNone(running_after["zip_artifact_path"])


if __name__ == "__main__":
    unittest.main()
