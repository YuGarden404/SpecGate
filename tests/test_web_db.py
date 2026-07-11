import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from specgate.web_db import connect_db, init_db


class WebDbTests(unittest.TestCase):
    def test_init_db_creates_runtime_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"

            init_db(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()

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


if __name__ == "__main__":
    unittest.main()
