from contextlib import closing
from io import BytesIO
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient

from specgate.web_app import create_app
from specgate.web_db import connect_db


class WebAppTests(unittest.TestCase):
    def make_client(self, **app_kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        app = create_app(data_root=base / "data", db_path=base / "web.sqlite3", **app_kwargs)
        return TestClient(app), app

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

    def test_artifact_index_is_not_served_as_executable_same_origin_html(self):
        client, app = self.make_client()
        self.register(client)
        project = self.create_project(client)
        with patch("specgate.web_app.start_run_background"):
            run = client.post(
                f"/api/projects/{project['id']}/runs",
                json={"prompt": "Build the result"},
            ).json()["run"]
        artifact = app.state.data_root / "artifact-index.html"
        artifact.write_text("<!doctype html><script>fetch('/api/me')</script>", encoding="utf-8")
        with closing(connect_db(app.state.db_path)) as conn:
            conn.execute(
                "update runs set status = ?, index_artifact_path = ? where id = ?",
                ("completed", str(artifact), run["id"]),
            )
            conn.commit()

        response = client.get(f"/api/runs/{run['id']}/artifacts/index")
        fetched = client.get(f"/api/runs/{run['id']}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers.get("content-disposition", ""))
        self.assertIn("sandbox", response.headers.get("content-security-policy", ""))
        self.assertNotIn("index_artifact_path", fetched.json()["run"])
        self.assertEqual(
            fetched.json()["run"]["index_artifact_url"],
            f"/api/runs/{run['id']}/artifacts/index",
        )

    def test_secure_cookie_can_be_enabled_for_production(self):
        client, _app = self.make_client(secure_cookies=True)

        response = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "correct-password"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("secure", response.headers["set-cookie"].lower())

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
