import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from specgate.web_db import connect_db, init_db


class WebDbTests(unittest.TestCase):
    def table_columns(self, conn, table_name):
        rows = conn.execute(f"pragma table_info({table_name})").fetchall()
        return {row[1]: row for row in rows}

    def create_version_one_database(self, *, configured: bool) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        configured_value = 1 if configured else 0
        ciphertext = "'hmac_sha256$legacy'" if configured else "null"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                f"""
                create table users (
                    id integer primary key,
                    username text,
                    password_hash text
                );
                create table user_settings (
                    user_id integer primary key,
                    governance_profile text not null default 'review',
                    context_strategy text not null default 'injection-safe',
                    api_key_configured integer not null default 0,
                    api_key_ciphertext text
                );
                create table runs (
                    id integer primary key,
                    status text not null,
                    prompt text not null
                );
                insert into users values (1, 'alice', 'hash');
                insert into user_settings values (
                    1, 'review', 'injection-safe',
                    {configured_value}, {ciphertext}
                );
                pragma user_version = 1;
                """
            )
        return db_path

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
            self.assertEqual(user_version, 3)

    def test_new_database_uses_schema_version_three_and_credentials_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"

            init_db(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                version = conn.execute("pragma user_version").fetchone()[0]
                columns = self.table_columns(conn, "user_credentials")

            self.assertEqual(version, 3)
            self.assertGreaterEqual(
                set(columns),
                {
                    "user_id",
                    "provider",
                    "status",
                    "ciphertext",
                    "nonce",
                    "key_version",
                    "key_id",
                    "updated_at",
                },
            )

    def test_new_database_uses_schema_version_three_and_runtime_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"

            init_db(db_path)

            with closing(connect_db(db_path)) as conn:
                self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 3)
                columns = {
                    row["name"]
                    for row in conn.execute("pragma table_info(runs)").fetchall()
                }
            self.assertIn("cancel_requested_at", columns)
            self.assertIn("deadline_at", columns)

    def test_connect_db_enables_runtime_concurrency_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)

            with closing(connect_db(db_path)) as conn:
                self.assertEqual(conn.execute("pragma foreign_keys").fetchone()[0], 1)
                self.assertEqual(conn.execute("pragma journal_mode").fetchone()[0], "wal")
                self.assertEqual(conn.execute("pragma synchronous").fetchone()[0], 1)
                self.assertEqual(conn.execute("pragma busy_timeout").fetchone()[0], 5000)

    def test_version_two_migrates_runtime_columns_without_data_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    create table runs (
                        id integer primary key,
                        status text not null,
                        prompt text not null
                    );
                    insert into runs (id, status, prompt) values (7, 'queued', 'legacy');
                    pragma user_version = 2;
                    """
                )

            init_db(db_path)

            with closing(connect_db(db_path)) as conn:
                row = conn.execute("select * from runs where id = 7").fetchone()
                self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 3)
            self.assertEqual(row["prompt"], "legacy")
            self.assertIsNone(row["cancel_requested_at"])
            self.assertIsNone(row["deadline_at"])

    def test_short_writer_contention_completes_with_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)
            first = connect_db(db_path)
            try:
                first.execute("begin immediate")
                first.execute(
                    "insert into users (username, password_hash) values ('first', 'hash')"
                )
                attempting = threading.Event()
                result = []

                def second_writer():
                    try:
                        with closing(connect_db(db_path)) as conn:
                            attempting.set()
                            conn.execute(
                                "insert into users (username, password_hash) values ('second', 'hash')"
                            )
                            conn.commit()
                        result.append("committed")
                    except Exception as exc:
                        result.append(type(exc).__name__)

                thread = threading.Thread(target=second_writer)
                thread.start()
                self.assertTrue(attempting.wait(timeout=1))
                first.commit()
                thread.join(timeout=1)

                self.assertFalse(thread.is_alive())
                self.assertEqual(result, ["committed"])
            finally:
                first.close()

    def test_version_one_hmac_state_requires_reentry(self):
        db_path = self.create_version_one_database(configured=True)

        init_db(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            credential = conn.execute(
                "select * from user_credentials where user_id = 1"
            ).fetchone()
            legacy = conn.execute(
                """
                select api_key_configured, api_key_ciphertext
                from user_settings where user_id = 1
                """
            ).fetchone()
            version = conn.execute("pragma user_version").fetchone()[0]

        self.assertEqual(version, 3)
        self.assertEqual(credential[2], "requires_reentry")
        self.assertIsNone(credential[3])
        self.assertEqual(legacy, (0, None))

    def test_newer_database_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("pragma user_version = 99")

            with self.assertRaisesRegex(RuntimeError, "newer schema"):
                init_db(db_path)

    def test_version_one_migration_is_idempotent(self):
        db_path = self.create_version_one_database(configured=True)

        init_db(db_path)
        init_db(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            version = conn.execute("pragma user_version").fetchone()[0]
            count = conn.execute(
                "select count(*) from user_credentials"
            ).fetchone()[0]
        self.assertEqual(version, 3)
        self.assertEqual(count, 1)

    def test_version_one_migration_rolls_back_on_schema_error(self):
        db_path = self.create_version_one_database(configured=True)

        with patch(
            "specgate.web_db.USER_CREDENTIALS_SCHEMA",
            "create table broken(",
        ):
            with self.assertRaises(sqlite3.OperationalError):
                init_db(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            version = conn.execute("pragma user_version").fetchone()[0]
            legacy = conn.execute(
                """
                select api_key_configured, api_key_ciphertext
                from user_settings
                """
            ).fetchone()
            table = conn.execute(
                """
                select name from sqlite_master
                where type = 'table' and name = 'user_credentials'
                """
            ).fetchone()
        self.assertEqual(version, 1)
        self.assertEqual(legacy, (1, "hmac_sha256$legacy"))
        self.assertIsNone(table)

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
