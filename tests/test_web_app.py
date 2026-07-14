import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import tempfile
import unittest
import warnings
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
import specgate.workspace_fs as workspace_fs
import specgate.web_runs as web_runs
from specgate.web_app import create_app
from specgate.web_db import connect_db
from specgate.web_projects import project_paths, web_run_paths
from specgate.web_runs import execute_run_once
from specgate.workspace_fs import WorkspacePathError, read_workspace_bytes


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


class WebAppTests(unittest.TestCase):
    @contextmanager
    def temporary_cwd(self, path):
        import os

        old_cwd = Path.cwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(old_cwd)

    def make_client(self, *, raise_server_exceptions=True, **app_kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        app = create_app(data_root=base / "data", db_path=base / "web.sqlite3", **app_kwargs)
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        self.addCleanup(client.close)
        return client, app

    def register(self, client, username="alice", password="correct-password"):
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def login(self, client, username="alice", password="correct-password"):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create_project(self, client, name="Manual Site"):
        response = client.post(
            "/api/projects",
            json={
                "name": name,
                "spec_text": "# Spec\nBuild a small page.",
                "checklist_text": "- Ship HTML.",
                "index_html": "<!doctype html><title>Seed</title>",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]

    def test_projects_require_session(self):
        client, _app = self.make_client()

        response = client.get("/api/projects")

        self.assertEqual(response.status_code, 401)

    def test_register_login_me_and_logout_use_session_cookie(self):
        client, _app = self.make_client()

        registered = self.register(client)

        self.assertEqual(registered["user"]["username"], "alice")
        self.assertIn("specgate_session", client.cookies)
        self.assertNotIn("password", registered["user"])

        me = client.get("/api/me")
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["user"]["username"], "alice")

        logout = client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200, logout.text)
        self.assertNotIn("specgate_session", client.cookies)
        self.assertEqual(client.get("/api/me").status_code, 401)

        self.login(client)
        self.assertIn("specgate_session", client.cookies)
        self.assertEqual(client.get("/api/me").json()["user"]["username"], "alice")

    def test_manual_project_creation_is_listed_for_current_user(self):
        client, _app = self.make_client()
        self.register(client)

        project = self.create_project(client)

        self.assertEqual(project["name"], "Manual Site")
        self.assertEqual(project["create_mode"], "manual")
        self.assertNotIn("root_path", project)

        projects = client.get("/api/projects")
        self.assertEqual(projects.status_code, 200, projects.text)
        self.assertEqual([row["id"] for row in projects.json()["projects"]], [project["id"]])
        self.assertNotIn("root_path", projects.json()["projects"][0])

        detail = client.get(f"/api/projects/{project['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["project"]["id"], project["id"])
        self.assertNotIn("root_path", detail.json()["project"])

    def test_project_preview_returns_source_as_plain_text(self):
        client, _app = self.make_client()
        self.register(client)
        project = self.create_project(client)

        response = client.get(f"/api/projects/{project['id']}/preview")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertIn("<!doctype html>", response.text)
        self.assertNotEqual(response.headers["content-type"].split(";")[0], "text/html")

    def test_project_preview_rejects_publishing_before_workspace_read(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            created = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            )
        run = created.json()["run"]
        with closing(connect_db(app.state.db_path)) as conn:
            conn.execute("update runs set status = 'publishing' where id = ?", (run["id"],))
            conn.commit()

        with patch("specgate.web_app.read_workspace_text", create=True) as read_text:
            response = client.get(f"/api/projects/{project['id']}/preview")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json(), {"detail": "project publication in progress"})
        read_text.assert_not_called()

    def test_quarantine_failure_sentinel_is_not_returned_by_project_preview(self):
        client, app = self.make_client()
        registered = self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            created = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            )
        run = created.json()["run"]
        paths = project_paths(app.state.data_root, registered["user"]["id"], project["id"])
        replacement = paths.root / "unknown-promotion-source"
        replacement.mkdir()
        (replacement / "sentinel.txt").write_text("external sentinel", encoding="utf-8")
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
            with self.assertRaises(web_runs.RunStoragePostRenameError):
                execute_run_once(app.state.db_path, app.state.data_root, run["id"])

        with patch("specgate.web_app.read_workspace_text") as read_text:
            preview = client.get(f"/api/projects/{project['id']}/preview")

        self.assertEqual(preview.status_code, 409, preview.text)
        self.assertNotIn("external sentinel", preview.text)
        read_text.assert_not_called()

    def test_preview_holds_writer_slot_until_workspace_read_finishes(self):
        for journal_mode in ("delete", "wal"):
            with self.subTest(journal_mode=journal_mode):
                client, app = self.make_client()
                registered = self.register(client)
                project = self.create_project(client)
                with patch("specgate.web_app.start_run_background"):
                    created = client.post(
                        f"/api/projects/{project['id']}/runs",
                        json={"prompt": "Build the result"},
                    )
                run = created.json()["run"]
                paths = web_run_paths(
                    project_paths(
                        app.state.data_root,
                        registered["user"]["id"],
                        project["id"],
                    ),
                    run["id"],
                )
                with closing(connect_db(app.state.db_path)) as conn:
                    selected_mode = conn.execute(
                        f"pragma journal_mode = {journal_mode}"
                    ).fetchone()[0]
                    self.assertEqual(selected_mode.lower(), journal_mode)
                    conn.execute("update runs set status = 'running' where id = ?", (run["id"],))
                    conn.commit()

                read_started = threading.Event()
                allow_read = threading.Event()
                prepare_started = threading.Event()
                prepare_finished = threading.Event()

                def blocking_read(root, relative):
                    read_started.set()
                    if not allow_read.wait(timeout=5):
                        raise AssertionError("preview read was not released")
                    return workspace_fs.read_workspace_text(root, relative)

                def prepare_publication():
                    prepare_started.set()
                    web_runs._prepare_run_publication(
                        app.state.db_path,
                        run["id"],
                        trust_level="trusted",
                        index_artifact_path=paths.index_artifact,
                        zip_artifact_path=paths.zip_artifact,
                        queue=type("Queue", (), {"approvals": []})(),
                    )
                    prepare_finished.set()

                with ThreadPoolExecutor(max_workers=2) as executor:
                    with patch("specgate.web_app.read_workspace_text", side_effect=blocking_read):
                        preview_future = executor.submit(
                            client.get,
                            f"/api/projects/{project['id']}/preview",
                        )
                        self.assertTrue(read_started.wait(timeout=3))
                        prepare_future = executor.submit(prepare_publication)
                        self.assertTrue(prepare_started.wait(timeout=3))
                        prepare_completed_while_preview_held = prepare_finished.wait(timeout=0.3)
                        allow_read.set()
                        preview = preview_future.result(timeout=5)
                        prepare_future.result(timeout=5)

                self.assertFalse(prepare_completed_while_preview_held)
                self.assertEqual(preview.status_code, 200, preview.text)
                with patch("specgate.web_app.read_workspace_text") as read_text:
                    rejected = client.get(f"/api/projects/{project['id']}/preview")
                self.assertEqual(rejected.status_code, 409, rejected.text)
                read_text.assert_not_called()

    def test_preview_busy_error_is_redacted_and_does_not_read_workspace(self):
        client, app = self.make_client(raise_server_exceptions=False)
        self.register(client)
        project = self.create_project(client)
        holder = connect_db(app.state.db_path)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")

        def short_timeout_connection(db_path):
            conn = connect_db(db_path)
            conn.execute("pragma busy_timeout = 1")
            return conn

        try:
            with (
                patch("specgate.web_app.connect_db", side_effect=short_timeout_connection),
                patch("specgate.web_app.read_workspace_text") as read_text,
            ):
                response = client.get(f"/api/projects/{project['id']}/preview")
        finally:
            holder.rollback()

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json(),
            {"detail": "Project preview is temporarily unavailable"},
        )
        self.assertNotIn("locked", response.text.lower())
        self.assertNotIn("busy", response.text.lower())
        read_text.assert_not_called()

    def test_uncertain_double_rename_failure_blocks_project_preview(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            created = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            )
        run = created.json()["run"]
        real_rename = workspace_fs.rename_workspace_tree_noreplace
        calls = 0

        def fail_publish_and_rollback(binding, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("publish rename failed")
            if calls == 3:
                raise OSError("rollback rename failed")
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=fail_publish_and_rollback,
        ):
            with self.assertRaises(web_runs.RunStoragePostRenameError):
                execute_run_once(app.state.db_path, app.state.data_root, run["id"])

        self.assertEqual(client.get(f"/api/runs/{run['id']}").json()["run"]["status"], "publishing")
        with patch("specgate.web_app.read_workspace_text") as read_text:
            preview = client.get(f"/api/projects/{project['id']}/preview")
        self.assertEqual(preview.status_code, 409, preview.text)
        read_text.assert_not_called()

    def test_post_run_returns_queued_and_run_can_be_read(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)

        with patch("specgate.web_app.start_run_background") as starter:
            response = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()["run"]
        self.assertEqual(run["status"], "queued")
        self.assertNotIn("project_id", run)
        self.assertNotIn("report_path", run)
        self.assertNotIn("index_artifact_path", run)
        self.assertNotIn("zip_artifact_path", run)
        self.assertFalse(run["has_index_artifact"])
        self.assertFalse(run["has_zip_artifact"])
        self.assertNotIn("index_artifact_url", run)
        self.assertNotIn("zip_artifact_url", run)
        starter.assert_called_once_with(app.state.db_path, app.state.data_root, run["id"])

        fetched = client.get(f"/api/runs/{run['id']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["run"]["id"], run["id"])
        self.assertEqual(fetched.json()["run"]["status"], "queued")
        self.assertNotIn("index_artifact_path", fetched.json()["run"])
        self.assertNotIn("zip_artifact_path", fetched.json()["run"])

    def test_app_shutdown_joins_started_run_threads(self):
        _client, app = self.make_client()
        joined = []

        class RecordingThread:
            daemon = True

            def join(self, timeout=None):
                joined.append(timeout)

        with TestClient(app) as lifespan_client:
            self.register(lifespan_client)
            project = self.create_project(lifespan_client)
            with patch("specgate.web_app.start_run_background", return_value=RecordingThread()):
                response = lifespan_client.post(
                    f"/api/projects/{project['id']}/runs",
                    json={"prompt": "Build the result"},
                )
            self.assertEqual(response.status_code, 200, response.text)

        self.assertEqual(len(joined), 1)
        self.assertGreater(joined[0], 0)
        self.assertLessEqual(joined[0], 5)

    def test_app_shutdown_uses_single_deadline_for_unfinished_run_threads(self):
        _client, app = self.make_client()
        join_timeouts = []

        class UnfinishedThread:
            daemon = True

            def join(self, timeout=None):
                join_timeouts.append(timeout)

            def is_alive(self):
                return True

        threads = [UnfinishedThread(), UnfinishedThread()]
        with patch("specgate.web_app.monotonic", side_effect=[100.0, 101.0, 104.5]):
            with TestClient(app):
                app.state.run_threads.extend(threads)

        self.assertEqual(join_timeouts, [4.0, 0.5])
        self.assertTrue(all(thread.daemon for thread in threads))

    def test_post_run_returns_409_for_active_run_without_starting_thread(self):
        client, _app = self.make_client()
        self.register(client)
        project = self.create_project(client)

        with patch("specgate.web_app.start_run_background") as starter:
            first = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "First run"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            starter.reset_mock()

            conflict = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Conflicting run"},
            )

        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(
            conflict.json(),
            {"detail": "该项目已有进行中的运行 / This project already has an active run"},
        )
        starter.assert_not_called()

    def test_post_run_returns_stable_503_when_database_is_locked(self):
        client, _app = self.make_client(raise_server_exceptions=False)
        self.register(client)
        project = self.create_project(client)

        with patch(
            "specgate.web_app.create_run",
            side_effect=sqlite3.OperationalError("database is locked"),
        ), patch("specgate.web_app.start_run_background") as starter:
            response = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            )

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json(),
            {"detail": "运行创建暂时不可用 / Run creation is temporarily unavailable"},
        )
        starter.assert_not_called()

    def test_run_debug_endpoint_returns_backend_audit_payload(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])

        response = client.get(f"/api/runs/{run['id']}/debug")

        self.assertEqual(response.status_code, 200, response.text)
        debug = response.json()["debug"]
        self.assertEqual(debug["run"]["id"], run["id"])
        self.assertEqual(debug["project"]["id"], project["id"])
        self.assertEqual(debug["summary"]["status"], "completed")
        self.assertIn("artifacts", debug)
        self.assertIn("trace", debug)
        self.assertIn("evidence", debug)

    def test_settings_can_be_updated_and_api_key_cleared(self):
        client, _app = self.make_client()
        self.register(client)

        defaults = client.get("/api/settings")
        self.assertEqual(defaults.status_code, 200, defaults.text)
        self.assertEqual(defaults.json()["settings"]["governance_profile"], "review")
        self.assertFalse(defaults.json()["settings"]["api_key_configured"])

        updated = client.put(
            "/api/settings",
            json={"governance_profile": "strict", "context_strategy": "rag-select"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["settings"]["governance_profile"], "strict")
        self.assertEqual(updated.json()["settings"]["context_strategy"], "rag-select")

        api_key = client.put("/api/settings/api-key", json={"api_key": "sk-test-secret"})
        self.assertEqual(api_key.status_code, 200, api_key.text)
        self.assertTrue(api_key.json()["settings"]["api_key_configured"])
        self.assertNotIn("sk-test-secret", repr(api_key.json()))

        cleared = client.delete("/api/settings/api-key")
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertFalse(cleared.json()["settings"]["api_key_configured"])

    def test_artifact_endpoints_return_404_when_artifacts_are_missing(self):
        client, _app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]

        index = client.get(f"/api/runs/{run['id']}/artifacts/index")
        result_zip = client.get(f"/api/runs/{run['id']}/artifacts/zip")

        self.assertEqual(index.status_code, 404)
        self.assertEqual(result_zip.status_code, 404)

    def test_artifact_endpoints_return_same_404_for_expected_but_missing_files(self):
        client, app = self.make_client()
        user = self.register(client)["user"]
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        paths = web_run_paths(
            project_paths(app.state.data_root, user["id"], project["id"]),
            run["id"],
        )
        with closing(connect_db(app.state.db_path)) as conn:
            conn.execute(
                "update runs set index_artifact_path = ?, zip_artifact_path = ? where id = ?",
                (str(paths.index_artifact), str(paths.zip_artifact), run["id"]),
            )
            conn.commit()

        responses = (
            client.get(f"/api/runs/{run['id']}/artifacts/index"),
            client.get(f"/api/runs/{run['id']}/artifacts/zip"),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json(), {"detail": "artifact not found"})

    def test_artifact_index_is_not_served_as_executable_same_origin_html(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])

        response = client.get(f"/api/runs/{run['id']}/artifacts/index")
        result_zip = client.get(f"/api/runs/{run['id']}/artifacts/zip")
        fetched = client.get(f"/api/runs/{run['id']}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(result_zip.status_code, 200, result_zip.text)
        self.assertTrue(result_zip.headers["content-type"].startswith("application/zip"))
        self.assertIn("attachment", response.headers.get("content-disposition", ""))
        self.assertIn("sandbox", response.headers.get("content-security-policy", ""))
        self.assertNotIn("index_artifact_path", fetched.json()["run"])
        self.assertEqual(
            fetched.json()["run"]["index_artifact_url"],
            f"/api/runs/{run['id']}/artifacts/index",
        )

    def test_artifact_downloads_reject_tampered_paths_without_leaking_existence(self):
        client, app = self.make_client()
        user = self.register(client)["user"]
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run1 = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the first result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run1["id"])
        with patch("specgate.web_app.start_run_background"):
            run2 = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the second result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run2["id"])

        project_root = project_paths(app.state.data_root, user["id"], project["id"])
        run2_paths = web_run_paths(project_root, run2["id"])
        project_root.artifacts.mkdir(parents=True, exist_ok=True)
        shared_index = project_root.artifacts / "shared-index.html"
        shared_zip = project_root.artifacts / "shared-result.zip"
        shared_index.write_text("shared", encoding="utf-8")
        shared_zip.write_bytes(b"shared")
        outside_index = app.state.data_root.parent / "outside-index.html"
        outside_zip = app.state.data_root.parent / "outside-result.zip"
        outside_index.write_text("outside", encoding="utf-8")
        outside_zip.write_bytes(b"outside")

        cases = (
            (
                "index_artifact_path",
                "index",
                (run2_paths.index_artifact, shared_index, outside_index, outside_index.with_name("missing.html")),
            ),
            (
                "zip_artifact_path",
                "zip",
                (run2_paths.zip_artifact, shared_zip, outside_zip, outside_zip.with_name("missing.zip")),
            ),
        )
        for column, endpoint, tampered_paths in cases:
            for tampered_path in tampered_paths:
                with self.subTest(endpoint=endpoint, tampered_path=tampered_path):
                    with closing(connect_db(app.state.db_path)) as conn:
                        conn.execute(
                            f"update runs set {column} = ? where id = ?",
                            (str(tampered_path), run1["id"]),
                        )
                        conn.commit()

                    response = client.get(f"/api/runs/{run1['id']}/artifacts/{endpoint}")

                    self.assertEqual(response.status_code, 404, response.text)
                    self.assertEqual(response.json(), {"detail": "artifact not found"})

    def test_artifact_download_rejects_mocked_junction_or_symlink_components(self):
        client, app = self.make_client()
        user = self.register(client)["user"]
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])
        paths = web_run_paths(
            project_paths(app.state.data_root, user["id"], project["id"]),
            run["id"],
        )
        original_is_symlink = Path.is_symlink

        with patch_is_junction(lambda path: path == paths.root):
            junction = client.get(f"/api/runs/{run['id']}/artifacts/index")
        with patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=lambda path: path == paths.artifacts or original_is_symlink(path),
        ):
            symlink = client.get(f"/api/runs/{run['id']}/artifacts/index")

        for response in (junction, symlink):
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json(), {"detail": "artifact not found"})

    def test_artifact_safe_read_rejection_returns_nonleaking_404(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])
        sentinel = "EXTERNAL_ARTIFACT_SENTINEL"

        for endpoint in ("index", "zip"):
            with self.subTest(endpoint=endpoint), patch(
                "specgate.web_app.read_workspace_bytes",
                side_effect=WorkspacePathError(sentinel, "path_race"),
            ) as safe_read:
                response = client.get(f"/api/runs/{run['id']}/artifacts/{endpoint}")

            self.assertTrue(safe_read.called)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json(), {"detail": "artifact not found"})
            self.assertNotIn(sentinel, response.text)

    def test_junction_patch_supports_path_type_without_is_junction(self):
        class LegacyPath:
            pass

        path = LegacyPath()

        with patch_is_junction(lambda candidate: candidate is path, path_type=LegacyPath):
            self.assertTrue(path.is_junction())

        self.assertFalse(hasattr(LegacyPath, "is_junction"))

    def test_artifact_download_uses_opened_file_when_path_is_replaced(self):
        client, app = self.make_client()
        user = self.register(client)["user"]
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])
        paths = web_run_paths(
            project_paths(app.state.data_root, user["id"], project["id"]),
            run["id"],
        )
        original_content = paths.index_artifact.read_bytes()
        replacement = paths.artifacts / "replacement.html"
        replacement_content = b"replacement artifact"
        replacement.write_bytes(replacement_content)

        def read_then_replace(root, relative):
            content = read_workspace_bytes(root, relative)
            replacement.replace(paths.index_artifact)
            return content

        with patch(
            "specgate.web_app.read_workspace_bytes",
            side_effect=read_then_replace,
        ) as safe_read:
            response = client.get(f"/api/runs/{run['id']}/artifacts/index")

        safe_read.assert_called_once()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, original_content)
        self.assertNotEqual(response.content, replacement_content)

    def test_artifact_download_rejects_run_directory_symlink_to_external(self):
        client, app = self.make_client()
        user = self.register(client)["user"]
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        execute_run_once(app.state.db_path, app.state.data_root, run["id"])
        paths = web_run_paths(
            project_paths(app.state.data_root, user["id"], project["id"]),
            run["id"],
        )
        backup = paths.root.with_name(f"{paths.root.name}-real")
        external = app.state.data_root.parent / "external-run"
        (external / "artifacts").mkdir(parents=True)
        (external / "artifacts" / "index.html").write_text("external", encoding="utf-8")
        paths.root.rename(backup)
        try:
            try:
                os.symlink(external, paths.root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            response = client.get(f"/api/runs/{run['id']}/artifacts/index")

            self.assertEqual(response.status_code, 404, response.text)
        finally:
            if paths.root.is_symlink():
                paths.root.unlink()
            if backup.exists() and not paths.root.exists():
                backup.rename(paths.root)

    def test_project_responses_include_latest_run_id_without_paths(self):
        client, _app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]

        listed = client.get("/api/projects")
        detail = client.get(f"/api/projects/{project['id']}")

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(detail.status_code, 200, detail.text)
        listed_project = listed.json()["projects"][0]
        detail_project = detail.json()["project"]
        self.assertEqual(listed_project["latest_run_id"], run["id"])
        self.assertEqual(detail_project["latest_run_id"], run["id"])
        self.assertNotIn("root_path", listed_project)
        self.assertNotIn("index_artifact_path", listed_project)
        self.assertNotIn("zip_artifact_path", listed_project)

    def test_secure_cookie_can_be_enabled_for_production(self):
        client, _app = self.make_client(secure_cookies=True)

        response = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_default_data_root_and_env_override_match_documented_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.temporary_cwd(base), patch.dict(
                "os.environ",
                {
                    "SPECGATE_WEB_DATA": "",
                    "SPECGATE_WEB_DATA_ROOT": "",
                    "SPECGATE_WEB_DB_PATH": "",
                },
                clear=False,
            ):
                app = create_app()

            self.assertEqual(app.state.data_root, base / "var" / "specgate_web")
            self.assertEqual(app.state.db_path, base / "var" / "specgate_web" / "web.sqlite3")

        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "custom-data"
            with patch.dict(
                "os.environ",
                {"SPECGATE_WEB_DATA": str(override), "SPECGATE_WEB_SECRET": "server-secret"},
                clear=False,
            ):
                app = create_app()

            self.assertEqual(app.state.data_root, override)
            self.assertEqual(app.state.db_path, override / "web.sqlite3")
            self.assertEqual(app.state.api_key_encryption_secret, "server-secret")

    def test_create_app_recovers_interrupted_run_initializations_after_database_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data_root = base / "data"
            db_path = base / "web.sqlite3"
            with (
                patch("specgate.web_app.recover_interrupted_run_initializations") as recover_initializations,
                patch("specgate.web_app.recover_interrupted_run_publications") as recover_publications,
            ):
                app = create_app(data_root=data_root, db_path=db_path)

        recover_initializations.assert_called_once_with(app.state.db_path, app.state.data_root)
        recover_publications.assert_called_once_with(app.state.db_path, app.state.data_root)

    def test_upload_rejects_files_over_limit(self):
        client, _app = self.make_client()
        self.register(client)
        oversized = BytesIO()
        with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("SPEC.md", "Spec")
            archive.writestr("CHECKLIST.md", "- Check")
            archive.writestr("large.bin", b"x" * (5 * 1024 * 1024 + 1))
        oversized.seek(0)

        response = client.post(
            "/api/projects/upload",
            data={"name": "Too Big"},
            files={"file": ("too-big.zip", oversized, "application/zip")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "upload exceeds 5 MiB limit")

    def test_upload_maps_archive_expansion_limit_to_413(self):
        client, _app = self.make_client()
        self.register(client)
        compressed = BytesIO()
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("SPEC.md", "Spec")
            archive.writestr("CHECKLIST.md", "Checklist")
            archive.writestr("data.txt", b"x" * (1024 * 1024))

        response = client.post(
            "/api/projects/upload",
            data={"name": "Expanded"},
            files={"file": ("expanded.zip", compressed.getvalue(), "application/zip")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "zip archive exceeds safety limits")

    def test_upload_maps_unsafe_archive_to_stable_400_without_internal_paths(self):
        client, app = self.make_client()
        self.register(client)
        unsafe = BytesIO()
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("SPEC.md", "Spec")
            archive.writestr("CHECKLIST.md", "Checklist")
            archive.writestr("../escape.txt", "unsafe")

        response = client.post(
            "/api/projects/upload",
            data={"name": "Unsafe"},
            files={"file": ("unsafe.zip", unsafe.getvalue(), "application/zip")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "zip archive is invalid or unsafe")
        self.assertNotIn(str(app.state.data_root), response.text)

    def test_upload_runs_synchronous_project_creation_in_threadpool(self):
        client, _app = self.make_client()
        self.register(client)
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("SPEC.md", "Spec")
            archive.writestr("CHECKLIST.md", "Checklist")
        calls = []

        async def run_in_test_threadpool(function, *args, **kwargs):
            calls.append((function, args, kwargs))
            return function(*args, **kwargs)

        with patch(
            "specgate.web_app.run_in_threadpool",
            create=True,
            side_effect=run_in_test_threadpool,
        ):
            response = client.post(
                "/api/projects/upload",
                data={"name": "Threaded"},
                files={"file": ("threaded.zip", archive_bytes.getvalue(), "application/zip")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0].__name__, "create_project_from_zip")

    def test_upload_maps_workspace_path_race_to_stable_409(self):
        client, app = self.make_client()
        self.register(client)
        internal_path = str(app.state.data_root / "users" / "1" / "projects" / "1")

        with patch(
            "specgate.web_app.create_project_from_zip",
            side_effect=WorkspacePathError(internal_path, "path_race"),
        ):
            response = client.post(
                "/api/projects/upload",
                data={"name": "Race"},
                files={"file": ("race.zip", b"zip", "application/zip")},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "project archive storage changed during upload")
        self.assertNotIn(internal_path, response.text)

    def test_upload_maps_other_workspace_errors_to_stable_500(self):
        client, app = self.make_client()
        self.register(client)
        internal_path = str(app.state.data_root / "private-sentinel")

        with patch(
            "specgate.web_app.create_project_from_zip",
            side_effect=WorkspacePathError(internal_path, "reparse_point"),
        ):
            response = client.post(
                "/api/projects/upload",
                data={"name": "Unsafe storage"},
                files={"file": ("unsafe.zip", b"zip", "application/zip")},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "project archive could not be stored safely")
        self.assertNotIn(internal_path, response.text)

    def test_users_cannot_access_each_others_projects_or_runs(self):
        client_a, app = self.make_client()
        self.register(client_a, "alice", "correct-password")
        project = self.create_project(client_a, "Alice Site")
        with patch("specgate.web_app.start_run_background"):
            run = client_a.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build Alice result"},
            ).json()["run"]

        client_b = TestClient(app)
        self.addCleanup(client_b.close)
        self.register(client_b, "bob", "correct-password")

        self.assertEqual(client_b.get(f"/api/projects/{project['id']}").status_code, 404)
        self.assertEqual(client_b.get(f"/api/runs/{run['id']}").status_code, 404)
        self.assertEqual(client_b.get("/api/projects").json()["projects"], [])
        self.assertEqual(
            client_b.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build Bob result"},
            ).status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
