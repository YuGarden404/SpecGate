import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_settings import (
    clear_api_key,
    get_settings,
    update_settings,
    upsert_api_key,
)


class WebSettingsTests(unittest.TestCase):
    def make_user(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        return db_path, user["id"]

    def test_get_settings_returns_mock_first_defaults(self):
        db_path, user_id = self.make_user()

        settings = get_settings(db_path, user_id)

        self.assertEqual(
            settings,
            {
                "governance_profile": "review",
                "context_strategy": "injection-safe",
                "api_key_configured": False,
                "api_key_storage": "not_stored",
                "llm_mode": "mock",
            },
        )

    def test_update_settings_accepts_valid_values_and_rejects_invalid_values(self):
        db_path, user_id = self.make_user()

        updated = update_settings(
            db_path,
            user_id,
            governance_profile="strict",
            context_strategy="rag-select",
        )

        self.assertEqual(updated["governance_profile"], "strict")
        self.assertEqual(updated["context_strategy"], "rag-select")

        with self.assertRaises(ValueError):
            update_settings(
                db_path,
                user_id,
                governance_profile="unsafe",
                context_strategy="rag-select",
            )
        with self.assertRaises(ValueError):
            update_settings(
                db_path,
                user_id,
                governance_profile="review",
                context_strategy="unsafe-context",
            )

    def test_upsert_api_key_without_secret_marks_configured_without_leaking_key(self):
        db_path, user_id = self.make_user()
        secret = "sk-test-secret-value"

        settings = upsert_api_key(db_path, user_id, secret, encryption_secret=None)

        self.assertTrue(settings["api_key_configured"])
        self.assertEqual(settings["api_key_storage"], "not_stored")
        self.assertEqual(settings["llm_mode"], "mock")
        self.assertEqual(get_settings(db_path, user_id)["llm_mode"], "mock")
        self.assertNotIn(secret, repr(settings))
        with closing(connect_db(db_path)) as conn:
            row = conn.execute(
                "select api_key_configured, api_key_ciphertext from user_settings where user_id = ?",
                (user_id,),
            ).fetchone()
        self.assertEqual(row["api_key_configured"], 1)
        self.assertIsNone(row["api_key_ciphertext"])

    def test_upsert_api_key_with_secret_stores_protected_value_and_clear_removes_it(self):
        db_path, user_id = self.make_user()
        api_key = "sk-test-secret-value"

        settings = upsert_api_key(
            db_path,
            user_id,
            api_key,
            encryption_secret="local-secret",
        )

        self.assertTrue(settings["api_key_configured"])
        self.assertEqual(settings["api_key_storage"], "protected")
        self.assertEqual(settings["llm_mode"], "mock")
        self.assertEqual(get_settings(db_path, user_id)["llm_mode"], "mock")
        self.assertNotIn(api_key, repr(settings))
        with closing(connect_db(db_path)) as conn:
            row = conn.execute(
                "select api_key_ciphertext from user_settings where user_id = ?",
                (user_id,),
            ).fetchone()
        self.assertIsNotNone(row["api_key_ciphertext"])
        self.assertNotEqual(row["api_key_ciphertext"], api_key)
        self.assertNotIn(api_key, row["api_key_ciphertext"])

        cleared = clear_api_key(db_path, user_id)

        self.assertFalse(cleared["api_key_configured"])
        self.assertEqual(cleared["api_key_storage"], "not_stored")
        with closing(connect_db(db_path)) as conn:
            cleared_row = conn.execute(
                "select api_key_configured, api_key_ciphertext from user_settings where user_id = ?",
                (user_id,),
            ).fetchone()
        self.assertEqual(cleared_row["api_key_configured"], 0)
        self.assertIsNone(cleared_row["api_key_ciphertext"])

    def test_upsert_api_key_rejects_empty_key(self):
        db_path, user_id = self.make_user()

        with self.assertRaises(ValueError):
            upsert_api_key(db_path, user_id, "   ", encryption_secret="local-secret")


if __name__ == "__main__":
    unittest.main()
