from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

import specgate.web_debug as web_debug_module
from specgate.llm_config import LLMRunConfig
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_debug import build_run_debug
from specgate.runtime_config import RunRuntimeConfig
from specgate.workspace_fs import (
    WorkspacePathError,
    open_workspace_file,
    workspace_file_metadata,
)
from specgate.web_projects import create_manual_project, project_paths, web_run_paths
from specgate.web_runs import create_run, execute_run_once


def patch_is_junction(predicate, *, path_type=Path):
    original = getattr(path_type, "is_junction", None)

    def mocked(path):
        return predicate(path) or (original(path) if original is not None else False)

    return patch.object(
        path_type,
        "is_junction",
        new=mocked,
        create=original is None,
    )


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

    def test_build_run_debug_hides_stale_artifacts_for_failed_run(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set status = 'failed', trust_level = 'failed' where id = ?",
                (run["id"],),
            )
            conn.commit()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertFalse(payload["run"]["has_index_artifact"])
        self.assertFalse(payload["run"]["has_zip_artifact"])
        self.assertEqual(payload["artifacts"], [])
        self.assertFalse(payload["summary"]["has_artifacts"])
        self.assertEqual(payload["summary"]["artifact_count"], 0)

    def test_build_run_debug_returns_normalized_runtime_config(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        config = RunRuntimeConfig(
            governance_profile="strict",
            context_strategy="compressed-rag",
            max_steps=8,
            context_budget_chars=20000,
            retrieval_top_k=5,
            retrieval_budget_chars=8000,
            compression_max_tool_result_chars=700,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set runtime_config_json = ? where id = ?",
                (config.to_json(), run["id"]),
            )
            conn.commit()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["runtime_config"], config.to_dict())
        self.assertIsNone(payload["runtime_config_error"])

    def test_build_run_debug_returns_frozen_llm_mode_without_fingerprint(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        config = LLMRunConfig.real(
            "https://api.example.test/v1",
            "test-model",
            "a" * 64,
        )
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set llm_config_json = ? where id = ?",
                (config.to_json(), run["id"]),
            )
            conn.commit()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["run"]["llm_mode"], "openai-compatible")
        self.assertEqual(payload["run"]["llm_model"], "test-model")
        self.assertNotIn("credential_fingerprint", repr(payload))

    def test_build_run_debug_hides_invalid_llm_config_source(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        sentinel = "RAW_LLM_CONFIG_SENTINEL"
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set llm_config_json = ? where id = ?",
                (json.dumps({"schema_version": 99, "raw": sentinel}), run["id"]),
            )
            conn.commit()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["run"]["llm_mode"], "invalid")
        self.assertIsNone(payload["run"]["llm_model"])
        self.assertNotIn(sentinel, json.dumps(payload, ensure_ascii=False))

    def test_build_run_debug_hides_invalid_runtime_config_source(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        sentinel = "RAW_RUNTIME_CONFIG_SENTINEL"
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update runs set runtime_config_json = ? where id = ?",
                (
                    json.dumps({"schema_version": 99, "raw": sentinel}),
                    run["id"],
                ),
            )
            conn.commit()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertIsNone(payload["runtime_config"])
        self.assertEqual(payload["runtime_config_error"], "invalid_runtime_config")
        self.assertNotIn(sentinel, json.dumps(payload, ensure_ascii=False))

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

    def test_trace_only_parses_records_retained_by_the_tail_window(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        (paths.audit / "trace.jsonl").write_text(
            "\n".join(json.dumps({"event": index}) for index in range(1000)),
            encoding="utf-8",
        )

        with patch(
            "specgate.web_debug._parse_trace_line",
            wraps=web_debug_module._parse_trace_line,
        ) as parse_line:
            payload = build_run_debug(
                db_path,
                data_root,
                user["id"],
                run["id"],
                max_trace_events=7,
            )

        self.assertLessEqual(parse_line.call_count, 7)
        self.assertEqual(payload["trace"]["total_events"], 1000)
        self.assertEqual(
            [event["event"] for event in payload["trace"]["events"]],
            list(range(993, 1000)),
        )
        self.assertTrue(payload["trace"]["truncated"])

    def test_trace_event_truncation_is_linear_and_output_bounded(self):
        event = {
            "event_type": "tool_result",
            "status": "failed",
            **{f"field_{index}": "value" * 8 for index in range(4000)},
        }
        real_dumps = json.dumps

        with patch.object(
            web_debug_module.json,
            "dumps",
            wraps=real_dumps,
        ) as dumps:
            truncated = web_debug_module._truncate_event(event, 200)

        self.assertLessEqual(dumps.call_count, 2)
        self.assertTrue(truncated["truncated"])
        self.assertEqual(truncated["event_type"], "tool_result")
        self.assertEqual(truncated["status"], "failed")
        self.assertIn("preview", truncated)
        self.assertLessEqual(
            len(real_dumps(truncated, ensure_ascii=False, sort_keys=True)),
            200 + 768,
        )

    def test_trace_tail_preserves_parse_and_decode_error_semantics(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        historical = b"".join(
            json.dumps({"event": index}).encode("utf-8") + b"\n"
            for index in range(10)
        )
        (paths.audit / "trace.jsonl").write_bytes(
            historical
            + b"{invalid json}\n"
            + b"\xff\n"
            + json.dumps({"event": "final"}).encode("utf-8")
            + b"\n"
        )

        payload = build_run_debug(
            db_path,
            data_root,
            user["id"],
            run["id"],
            max_trace_events=3,
        )

        events = payload["trace"]["events"]
        self.assertEqual(events[0]["event_type"], "trace_parse_error")
        self.assertEqual(events[1]["event_type"], "trace_decode_error")
        self.assertEqual(events[2]["event"], "final")
        self.assertEqual(payload["trace"]["total_events"], 13)
        self.assertTrue(payload["trace"]["truncated"])

    def test_debug_limits_reject_unbounded_trace_options(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        cases = (
            {"max_trace_events": 1001},
            {"max_event_chars": 16001},
        )

        for options in cases:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    build_run_debug(
                        db_path,
                        data_root,
                        user["id"],
                        run["id"],
                        **options,
                    )

    def test_large_trace_and_evidence_use_bounded_safe_handle_reads(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        trace_path = paths.audit / "trace.jsonl"
        trace_path.write_bytes(
            json.dumps({"event": "kept"}).encode("utf-8")
            + b"\n"
            + b'{"event":"'
            + (b"x" * (2 * 1024 * 1024))
            + b'"}\n'
        )
        (paths.audit / "retrieval.json").write_bytes(
            b'{"value":"' + (b"y" * (1024 * 1024)) + b'"}'
        )
        calls = []

        class BoundedHandle:
            def __init__(self, handle, relative):
                self._handle = handle
                self._relative = relative

            def read(self, size=-1):
                calls.append((self._relative, "read", size))
                if size < 0 or size > 256 * 1024 + 1:
                    raise AssertionError("evidence read was not bounded")
                return self._handle.read(size)

            def readline(self, size=-1):
                calls.append((self._relative, "readline", size))
                if size < 0 or size > 64 * 1024 + 1:
                    raise AssertionError("trace line read was not bounded")
                return self._handle.readline(size)

        @contextmanager
        def tracking_open(root, relative, access="read", *, create=False):
            with open_workspace_file(root, relative, access, create=create) as handle:
                yield BoundedHandle(handle, relative)

        with patch(
            "specgate.web_debug.open_workspace_file",
            side_effect=tracking_open,
        ) as safe_open:
            payload = build_run_debug(
                db_path,
                data_root,
                user["id"],
                run["id"],
                max_trace_events=2,
                max_event_chars=100,
            )

        self.assertTrue(safe_open.called)
        self.assertTrue(any(call[:2] == ("trace.jsonl", "readline") for call in calls))
        trace_read_sizes = [
            size
            for relative, operation, size in calls
            if relative == "trace.jsonl" and operation == "readline"
        ]
        self.assertLessEqual(max(trace_read_sizes), 4 * 100 + 512 + 1)
        self.assertTrue(any(call[:2] == ("retrieval.json", "read") for call in calls))
        self.assertEqual(payload["trace"]["total_events"], 2)
        self.assertEqual(payload["trace"]["events"][0]["event"], "kept")
        self.assertEqual(
            payload["trace"]["events"][1]["event_type"],
            "trace_line_truncated",
        )
        self.assertTrue(payload["trace"]["events"][1]["truncated"])
        self.assertTrue(payload["evidence"]["retrieval"]["truncated"])
        self.assertIn("error", payload["evidence"]["retrieval"])
        self.assertLess(len(json.dumps(payload)), 100_000)

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
        with patch_is_junction(lambda path: path == paths.root):
            payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertTrue(payload["artifacts"])
        self.assertTrue(all(not item["exists"] for item in payload["artifacts"]))
        self.assertTrue(all(item["size_bytes"] == 0 for item in payload["artifacts"]))

    def test_artifact_metadata_uses_safe_stat_without_reading_large_zip(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        large_size = 8 * 1024 * 1024
        paths.zip_artifact.write_bytes(b"z" * large_size)

        with patch(
            "specgate.web_debug.workspace_file_metadata",
            wraps=workspace_file_metadata,
        ) as safe_metadata:
            payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertTrue(safe_metadata.called)
        zip_artifact = next(item for item in payload["artifacts"] if item["kind"] == "zip")
        self.assertTrue(zip_artifact["exists"])
        self.assertEqual(zip_artifact["size_bytes"], large_size)

    def test_audit_reads_reject_link_like_directory_and_files_without_leaking_content(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        audit_files = (
            paths.audit / "trace.jsonl",
            paths.audit / "retrieval.json",
            paths.audit / "compression.json",
            paths.audit / "isolation.json",
            paths.audit / "security.json",
        )
        sentinel = "EXTERNAL_AUDIT_SENTINEL"
        original_is_symlink = Path.is_symlink

        for linked_path in (paths.audit, *audit_files):
            with self.subTest(linked_path=linked_path.name):
                audit_files[0].write_text(
                    json.dumps({
                        "event_type": "audit",
                        "value": sentinel if linked_path in {paths.audit, audit_files[0]} else "safe",
                    }) + "\n",
                    encoding="utf-8",
                )
                for evidence_path in audit_files[1:]:
                    evidence_path.write_text(
                        json.dumps({
                            "value": sentinel
                            if linked_path in {paths.audit, evidence_path}
                            else "safe",
                        }),
                        encoding="utf-8",
                    )
                with patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=lambda path: path == linked_path or original_is_symlink(path),
                ):
                    payload = build_run_debug(db_path, data_root, user["id"], run["id"])

                self.assertNotIn(sentinel, json.dumps(payload))
                if linked_path in {paths.audit, audit_files[0]}:
                    self.assertEqual(payload["trace"]["error"]["rule_family"], "linked_path")
                for name, evidence_path in zip(
                    ("retrieval", "compression", "isolation", "security"),
                    audit_files[1:],
                ):
                    if linked_path in {paths.audit, evidence_path}:
                        self.assertEqual(
                            payload["evidence"][name]["rule_family"],
                            "linked_path",
                        )

    def test_audit_only_treats_exact_final_path_race_as_optional_missing(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        sentinel = "FILESYSTEM_ERROR_SENTINEL"
        cases = (
            (
                WorkspacePathError(
                    sentinel,
                    "path_race",
                    missing_path="retrieval.json",
                ),
                None,
            ),
            (
                WorkspacePathError(
                    sentinel,
                    "linked_path",
                    missing_path="retrieval.json",
                ),
                "linked_path",
            ),
            (
                WorkspacePathError(
                    sentinel,
                    "reparse_point",
                    missing_path="retrieval.json",
                ),
                "reparse_point",
            ),
            (
                WorkspacePathError(
                    sentinel,
                    "path_race",
                    missing_path="audit",
                ),
                "path_race",
            ),
        )

        for error, expected_family in cases:
            with self.subTest(
                family=error.rule_family,
                missing_path=error.missing_path,
            ):
                def selective_open(root, relative, access="read", *, create=False):
                    if Path(root) == paths.audit and relative == "retrieval.json":
                        raise error
                    return open_workspace_file(root, relative, access, create=create)

                with patch(
                    "specgate.web_debug.open_workspace_file",
                    side_effect=selective_open,
                ):
                    payload = build_run_debug(db_path, data_root, user["id"], run["id"])

                retrieval = payload["evidence"]["retrieval"]
                if expected_family is None:
                    self.assertIsNone(retrieval)
                else:
                    self.assertEqual(retrieval["rule_family"], expected_family)
                    self.assertEqual(retrieval["error"], "audit evidence unavailable")
                self.assertNotIn(sentinel, json.dumps(payload))

    def test_audit_read_race_does_not_retry_by_path_or_leak_replacement(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = web_run_paths(
            project_paths(data_root, user["id"], project["id"]),
            run["id"],
        )
        sentinel = "REPLACED_AUDIT_SENTINEL"
        target = paths.audit / "retrieval.json"
        target.write_text(json.dumps({"value": "original"}), encoding="utf-8")
        error = WorkspacePathError("audit changed while opening", "path_race")

        def fail_after_replacement(root, relative, access="read", *, create=False):
            if Path(root) == paths.audit and relative == "retrieval.json":
                target.write_text(json.dumps({"value": sentinel}), encoding="utf-8")
                raise error
            return open_workspace_file(root, relative, access, create=create)

        with patch(
            "specgate.web_debug.open_workspace_file",
            side_effect=fail_after_replacement,
        ) as safe_read:
            payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertTrue(safe_read.called)
        self.assertEqual(
            payload["evidence"]["retrieval"],
            {"error": "audit evidence unavailable", "rule_family": "path_race"},
        )
        self.assertNotIn(sentinel, json.dumps(payload))

    def test_junction_patch_supports_path_type_without_is_junction(self):
        class LegacyPath:
            pass

        path = LegacyPath()

        with patch_is_junction(lambda candidate: candidate is path, path_type=LegacyPath):
            self.assertTrue(path.is_junction())

        self.assertFalse(hasattr(LegacyPath, "is_junction"))

    def test_build_run_debug_rejects_other_user(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        other = create_user(db_path, "bob", "correct-password")

        with self.assertRaises(ValueError):
            build_run_debug(db_path, data_root, other["id"], run["id"])


if __name__ == "__main__":
    unittest.main()
