import os
import sqlite3
import stat
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
from fastapi.responses import FileResponse

from specgate import web_app as web_app_module
from specgate.web_app import create_app
from specgate.web_db import connect_db
from specgate.web_projects import project_paths, web_run_paths
from specgate.web_runs import execute_run_once


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

    def test_artifact_reparse_attribute_is_rejected(self):
        checker = getattr(web_app_module, "_is_link_or_reparse", lambda _path, _stat: False)
        file_stat = type(
            "ReparseStat",
            (),
            {
                "st_mode": stat.S_IFREG,
                "st_file_attributes": stat.FILE_ATTRIBUTE_REPARSE_POINT,
            },
        )()

        with patch_is_junction(lambda _path: False):
            self.assertTrue(checker(Path("artifact"), file_stat))

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
        real_os_open = os.open
        real_file_response = FileResponse

        def open_then_replace(path, flags):
            descriptor = real_os_open(path, flags)
            try:
                replacement.replace(paths.index_artifact)
            except OSError:
                os.close(descriptor)
                raise
            return descriptor

        def legacy_file_response(path, *args, **kwargs):
            replacement.replace(paths.index_artifact)
            return real_file_response(path, *args, **kwargs)

        with (
            patch("specgate.web_app.os.open", side_effect=open_then_replace),
            patch("specgate.web_app.FileResponse", side_effect=legacy_file_response, create=True),
        ):
            response = client.get(f"/api/runs/{run['id']}/artifacts/index")

        self.assertIn(response.status_code, {200, 404}, response.text)
        if response.status_code == 200:
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

        self.assertIn(response.status_code, {400, 413})

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
