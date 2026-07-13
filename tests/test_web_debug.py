from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_debug import build_run_debug
from specgate.web_projects import create_manual_project, project_paths, web_run_paths
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
        run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Build it",
            data_root=data_root,
        )
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
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        trace_path = paths.audit / "trace.jsonl"
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
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        evidence_path = paths.audit / "retrieval.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps({"selected_chunks": [{"path": "TASK_SPEC.md"}]}),
            encoding="utf-8",
        )

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["evidence"]["retrieval"]["selected_chunks"][0]["path"], "TASK_SPEC.md")
        self.assertIsNone(payload["evidence"]["compression"])

    def test_completed_runs_read_only_their_immutable_audit_data(self):
        db_path, data_root, user, project, run1 = self.make_completed_run()
        project_root = project_paths(data_root, user["id"], project["id"])
        run1_paths = web_run_paths(project_root, run1["id"])
        evidence_names = ("retrieval", "compression", "isolation", "security")
        (run1_paths.audit / "trace.jsonl").write_text(
            json.dumps({"run_marker": "run-1"}) + "\n",
            encoding="utf-8",
        )
        for name in evidence_names:
            (run1_paths.audit / f"{name}.json").write_text(
                json.dumps({"run_marker": "run-1", "kind": name}),
                encoding="utf-8",
            )

        run1_before = build_run_debug(db_path, data_root, user["id"], run1["id"])
        run1_bytes = {
            path.name: path.read_bytes()
            for path in run1_paths.audit.iterdir()
            if path.is_file()
        }

        run2 = create_run(
            db_path,
            project["id"],
            user["id"],
            "Build it again",
            data_root=data_root,
        )
        execute_run_once(db_path, data_root, run2["id"])
        run2_paths = web_run_paths(project_root, run2["id"])
        (run2_paths.audit / "trace.jsonl").write_text(
            json.dumps({"run_marker": "run-2"}) + "\n",
            encoding="utf-8",
        )
        for name in evidence_names:
            (run2_paths.audit / f"{name}.json").write_text(
                json.dumps({"run_marker": "run-2", "kind": name}),
                encoding="utf-8",
            )
        shared_latest = project_root.workspace / "runs" / "latest"
        shared_latest.mkdir(parents=True, exist_ok=True)
        (shared_latest / "trace.jsonl").write_text(
            json.dumps({"run_marker": "shared-latest"}) + "\n",
            encoding="utf-8",
        )
        for name in evidence_names:
            (shared_latest / f"{name}.json").write_text(
                json.dumps({"run_marker": "shared-latest", "kind": name}),
                encoding="utf-8",
            )

        run1_after = build_run_debug(db_path, data_root, user["id"], run1["id"])
        run2_debug = build_run_debug(db_path, data_root, user["id"], run2["id"])

        self.assertEqual(run1_after["trace"]["events"], run1_before["trace"]["events"])
        self.assertEqual(run1_after["trace"]["events"][0]["run_marker"], "run-1")
        self.assertEqual(run2_debug["trace"]["events"][0]["run_marker"], "run-2")
        for name in evidence_names:
            self.assertEqual(run1_after["evidence"][name]["run_marker"], "run-1")
            self.assertEqual(run2_debug["evidence"][name]["run_marker"], "run-2")
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in run1_paths.audit.iterdir()
                if path.is_file()
            },
            run1_bytes,
        )

    def test_missing_run_audit_returns_safe_empty_values_without_latest_fallback(self):
        db_path, data_root, user, project, _completed = self.make_completed_run()
        project_root = project_paths(data_root, user["id"], project["id"])
        run = create_run(
            db_path,
            project["id"],
            user["id"],
            "Queued run",
            data_root=data_root,
        )
        shared_latest = project_root.workspace / "runs" / "latest"
        shared_latest.mkdir(parents=True, exist_ok=True)
        (shared_latest / "trace.jsonl").write_text(
            json.dumps({"run_marker": "shared-latest"}) + "\n",
            encoding="utf-8",
        )
        (shared_latest / "retrieval.json").write_text(
            json.dumps({"run_marker": "shared-latest"}),
            encoding="utf-8",
        )

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["trace"]["events"], [])
        self.assertFalse(payload["trace"]["truncated"])
        self.assertEqual(
            payload["evidence"],
            {
                "retrieval": None,
                "compression": None,
                "isolation": None,
                "security": None,
            },
        )

    def test_tampered_artifact_metadata_never_touches_external_database_path(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        external = data_root.parent / "external-secret.bin"
        external.write_bytes(b"secret-size")
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update artifacts set path = ? where run_id = ? and kind = 'index'",
                (str(external), run["id"]),
            )
            conn.commit()
        original_is_file = Path.is_file
        original_stat = Path.stat
        external_calls = []

        def guarded_is_file(path):
            if path == external:
                external_calls.append(("is_file", path))
            return original_is_file(path)

        def guarded_stat(path, *args, **kwargs):
            if path == external:
                external_calls.append(("stat", path))
            return original_stat(path, *args, **kwargs)

        with (
            patch.object(Path, "is_file", autospec=True, side_effect=guarded_is_file),
            patch.object(Path, "stat", autospec=True, side_effect=guarded_stat),
        ):
            payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        index_artifact = next(item for item in payload["artifacts"] if item["kind"] == "index")
        self.assertEqual(external_calls, [])
        self.assertFalse(index_artifact["exists"])
        self.assertEqual(index_artifact["size_bytes"], 0)

    def test_artifact_metadata_rejects_mocked_run_junction(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        original_is_junction = Path.is_junction

        with patch.object(
            Path,
            "is_junction",
            autospec=True,
            side_effect=lambda path: path == paths.root or original_is_junction(path),
        ):
            payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertTrue(payload["artifacts"])
        self.assertTrue(all(not item["exists"] for item in payload["artifacts"]))
        self.assertTrue(all(item["size_bytes"] == 0 for item in payload["artifacts"]))

    def test_build_run_debug_rejects_other_user(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        other = create_user(db_path, "bob", "correct-password")

        with self.assertRaises(ValueError):
            build_run_debug(db_path, data_root, other["id"], run["id"])


if __name__ == "__main__":
    unittest.main()
