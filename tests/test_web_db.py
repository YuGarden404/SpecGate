import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from importlib import import_module
from pathlib import Path

from specgate.web_db import connect_db, init_db


class WebDbTests(unittest.TestCase):
    def table_columns(self, conn, table_name):
        rows = conn.execute(f"pragma table_info({table_name})").fetchall()
        return {row[1]: row for row in rows}

    def test_init_db_creates_runtime_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"

            init_db(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
                user_version = conn.execute("pragma user_version").fetchone()[0]

            tables = {row[0] for row in rows}
            self.assertGreaterEqual(
                tables,
                {
                    "users",
                    "sessions",
                    "user_settings",
                    "projects",
                    "messages",
                    "runs",
                    "approvals",
                    "artifacts",
                },
            )
            self.assertEqual(user_version, 1)

    def test_init_db_creates_product_model_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"

            init_db(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                sessions = self.table_columns(conn, "sessions")
                user_settings = self.table_columns(conn, "user_settings")
                projects = self.table_columns(conn, "projects")
                runs = self.table_columns(conn, "runs")
                approvals = self.table_columns(conn, "approvals")
                artifacts = self.table_columns(conn, "artifacts")

            self.assertIn("token", sessions)

            for column_name in (
                "governance_profile",
                "context_strategy",
                "api_key_configured",
                "api_key_ciphertext",
            ):
                self.assertIn(column_name, user_settings)
            self.assertEqual(user_settings["governance_profile"][4], "'review'")
            self.assertEqual(user_settings["context_strategy"][4], "'injection-safe'")
            self.assertEqual(user_settings["api_key_configured"][4], "0")

            for column_name in (
                "create_mode",
                "root_path",
                "last_run_status",
            ):
                self.assertIn(column_name, projects)

            for column_name in (
                "prompt",
                "trust_level",
                "report_path",
                "index_artifact_path",
                "zip_artifact_path",
                "error_message",
                "started_at",
                "finished_at",
            ):
                self.assertIn(column_name, runs)

            for column_name in (
                "project_id",
                "approval_id",
                "action_name",
                "target_path",
                "preview_json",
            ):
                self.assertIn(column_name, approvals)

            for column_name in (
                "run_id",
                "kind",
                "path",
                "created_at",
            ):
                self.assertIn(column_name, artifacts)

    def test_connect_db_returns_rows_addressable_by_column_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)

            with closing(connect_db(db_path)) as conn:
                self.assertIs(conn.row_factory, sqlite3.Row)
                foreign_keys = conn.execute("pragma foreign_keys").fetchone()[0]
                conn.execute(
                    "insert into users (username, password_hash) values (?, ?)",
                    ("alice", "hash"),
                )
                row = conn.execute(
                    "select username from users where username = ?",
                    ("alice",),
                ).fetchone()

            self.assertEqual(foreign_keys, 1)
            self.assertEqual(row["username"], "alice")

    def test_web_entrypoint_imports_before_server_is_implemented(self):
        web = import_module("specgate.web")

        self.assertTrue(callable(web.main))

    def test_web_module_entrypoint_invokes_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "specgate.web", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Run the SpecGate Web UI server.", result.stdout)


if __name__ == "__main__":
    unittest.main()
