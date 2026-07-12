from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
from specgate.web_debug import build_run_debug
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run, execute_run_once


class WebDebugTests(unittest.TestCase):
    def make_completed_run(self):
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
            name="Audit Site",
            spec_text="# Spec\nBuild an HTML page.",
            checklist_text="- Ship index.html",
            index_html=None,
        )
        run = create_run(db_path, project["id"], user["id"], "Build it")
        execute_run_once(db_path, data_root, run["id"])
        return db_path, data_root, user, project, run

    def test_build_run_debug_returns_run_project_artifacts_trace_and_summary(self):
        db_path, data_root, user, project, run = self.make_completed_run()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["run"]["id"], run["id"])
        self.assertEqual(payload["project"]["id"], project["id"])
        self.assertEqual(payload["summary"]["status"], "completed")
        self.assertTrue(payload["summary"]["has_artifacts"])
        self.assertGreaterEqual(len(payload["artifacts"]), 2)
        self.assertTrue(all("download_url" in artifact for artifact in payload["artifacts"]))
        self.assertIn("trace", payload)
        self.assertIn("events", payload["trace"])
        self.assertIn("evidence", payload)

    def test_build_run_debug_limits_trace_events_and_event_size(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = project_paths(data_root, user["id"], project["id"])
        trace_path = paths.workspace / "runs" / "latest" / "trace.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            "\n".join(json.dumps({"event": i, "payload": "x" * 50}) for i in range(5)),
            encoding="utf-8",
        )

        payload = build_run_debug(
            db_path,
            data_root,
            user["id"],
            run["id"],
            max_trace_events=2,
            max_event_chars=30,
        )

        self.assertTrue(payload["trace"]["truncated"])
        self.assertEqual(len(payload["trace"]["events"]), 2)
        self.assertEqual([event["event"] for event in payload["trace"]["events"]], [3, 4])
        self.assertTrue(payload["trace"]["events"][0]["truncated"])

    def test_build_run_debug_reads_evidence_files(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = project_paths(data_root, user["id"], project["id"])
        evidence_path = paths.workspace / "runs" / "latest" / "retrieval.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps({"selected_chunks": [{"path": "TASK_SPEC.md"}]}),
            encoding="utf-8",
        )

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["evidence"]["retrieval"]["selected_chunks"][0]["path"], "TASK_SPEC.md")
        self.assertIsNone(payload["evidence"]["compression"])

    def test_build_run_debug_rejects_other_user(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        other = create_user(db_path, "bob", "correct-password")

        with self.assertRaises(ValueError):
            build_run_debug(db_path, data_root, other["id"], run["id"])


if __name__ == "__main__":
    unittest.main()
