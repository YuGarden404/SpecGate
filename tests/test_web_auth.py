import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from specgate.web_auth import (
    authenticate_user,
    create_session,
    create_user,
    delete_session,
    get_user_by_session,
    hash_password,
    utc_now,
    verify_password,
)
from specgate.web_db import connect_db, init_db


class WebAuthTests(unittest.TestCase):
    def make_db(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        init_db(db_path)
        return db_path

    def test_hash_password_rejects_short_passwords_and_verifies_format(self):
        with self.assertRaises(ValueError):
            hash_password("short")

        password_hash = hash_password("long-enough", salt="fixed-salt")
        parts = password_hash.split("$")

        self.assertEqual(parts[0], "pbkdf2_sha256")
        self.assertEqual(parts[1], "260000")
        self.assertEqual(parts[2], "fixed-salt")
        self.assertTrue(verify_password("long-enough", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))
        self.assertFalse(verify_password("long-enough", "not-a-valid-hash"))

    def test_verify_password_uses_iterations_stored_in_hash(self):
        iterations = 1_000
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            b"long-enough",
            b"legacy-salt",
            iterations,
        ).hex()
        password_hash = f"pbkdf2_sha256${iterations}$legacy-salt${digest}"

        self.assertTrue(verify_password("long-enough", password_hash))

    def test_create_user_does_not_store_plaintext_and_authenticates(self):
        db_path = self.make_db()

        user = create_user(db_path, " alice ", "correct-password")
        authed = authenticate_user(db_path, "alice", "correct-password")

        self.assertIsInstance(user, sqlite3.Row)
        self.assertEqual(user["username"], "alice")
        self.assertEqual(authed["id"], user["id"])
        with closing(connect_db(db_path)) as conn:
            stored = conn.execute(
                "select password_hash from users where id = ?",
                (user["id"],),
            ).fetchone()["password_hash"]
            settings = conn.execute(
                "select user_id from user_settings where user_id = ?",
                (user["id"],),
            ).fetchone()
        self.assertNotEqual(stored, "correct-password")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertEqual(settings["user_id"], user["id"])

        with self.assertRaises(ValueError):
            authenticate_user(db_path, "alice", "wrong-password")

    def test_create_user_rejects_blank_and_duplicate_usernames(self):
        db_path = self.make_db()

        with self.assertRaises(ValueError):
            create_user(db_path, "   ", "correct-password")

        create_user(db_path, "alice", "correct-password")
        with self.assertRaises(ValueError):
            create_user(db_path, " alice ", "another-password")

    def test_session_round_trip_delete_and_expiry(self):
        db_path = self.make_db()
        user = create_user(db_path, "alice", "correct-password")

        token = create_session(db_path, user["id"])
        found = get_user_by_session(db_path, token)

        self.assertIsInstance(token, str)
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(found["id"], user["id"])

        delete_session(db_path, token)
        with self.assertRaises(ValueError):
            get_user_by_session(db_path, token)

        expired_token = create_session(db_path, user["id"])
        expired_at = (utc_now() - timedelta(seconds=1)).isoformat()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                "update sessions set expires_at = ? where token = ?",
                (expired_at, expired_token),
            )
            conn.commit()
        with self.assertRaises(ValueError):
            get_user_by_session(db_path, expired_token)
        with closing(connect_db(db_path)) as conn:
            session_count = conn.execute(
                "select count(*) from sessions where token = ?",
                (expired_token,),
            ).fetchone()[0]
        self.assertEqual(session_count, 0)

    def test_get_user_by_session_rejects_missing_token(self):
        db_path = self.make_db()

        with self.assertRaises(ValueError):
            get_user_by_session(db_path, None)


if __name__ == "__main__":
    unittest.main()
