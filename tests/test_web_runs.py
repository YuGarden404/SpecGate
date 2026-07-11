import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run, execute_run_once, get_run


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
        db_path, _data_root, user, project = self.make_context()

        run = create_run(db_path, project["id"], user["id"], "Build the result")

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

        with self.assertRaises(ValueError):
            create_run(db_path, project["id"], user["id"], "   ")

    def test_get_run_rejects_other_user(self):
        db_path, _data_root, user, project = self.make_context()
        other = create_user(db_path, "bob", "correct-password")
        run = create_run(db_path, project["id"], user["id"], "Build the result")

        self.assertEqual(get_run(db_path, user["id"], run["id"])["id"], run["id"])
        with self.assertRaises(ValueError):
            get_run(db_path, other["id"], run["id"])

    def test_execute_run_once_publishes_index_and_zip_artifacts(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result")

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

    def test_execute_run_once_failure_marks_run_failed_when_index_is_missing(self):
        db_path, data_root, user, project = self.make_context()
        run = create_run(db_path, project["id"], user["id"], "Build the result")

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
        self.assertIn("Gate", updated["error_message"])
        self.assertIsNone(updated["index_artifact_path"])
        self.assertFalse((paths.artifacts / "latest-index.html").exists())


if __name__ == "__main__":
    unittest.main()
