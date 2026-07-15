import base64
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from specgate.web_auth import create_user
from specgate.web_credentials import InvalidCredential, WebCredentialService
from specgate.web_db import connect_db, init_db
from specgate.runtime_config import RuntimeConfigError
from specgate.web_settings import (
    clear_api_key,
    get_runtime_settings,
    get_settings,
    update_settings,
    upsert_api_key,
)


TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class WebSettingsTests(unittest.TestCase):
    def make_user(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        return db_path, int(user["id"])

    def test_get_settings_returns_mock_first_defaults(self):
        db_path, user_id = self.make_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)

        settings = get_settings(db_path, user_id, service)

        self.assertEqual(
            settings,
            {
                "governance_profile": "review",
                "context_strategy": "injection-safe",
                "max_steps": 5,
                "context_budget_chars": 12000,
                "retrieval_top_k": 6,
                "retrieval_budget_chars": 9000,
                "compression_max_tool_result_chars": 1200,
                "api_key_configured": False,
                "api_key_storage": "not_stored",
                "api_key_requires_reentry": False,
                "credential_store_available": True,
                "llm_mode": "mock",
            },
        )

    def test_runtime_settings_excludes_all_credential_state(self):
        db_path, user_id = self.make_user()

        settings = get_runtime_settings(db_path, user_id)

        self.assertEqual(
            settings,
            {
                "governance_profile": "review",
                "context_strategy": "injection-safe",
                "max_steps": 5,
                "context_budget_chars": 12000,
                "retrieval_top_k": 6,
                "retrieval_budget_chars": 9000,
                "compression_max_tool_result_chars": 1200,
            },
        )

    def test_update_settings_accepts_valid_values_and_rejects_invalid_values(self):
        db_path, user_id = self.make_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)

        updated = update_settings(
            db_path,
            user_id,
            governance_profile="strict",
            context_strategy="rag-select",
            max_steps=8,
            context_budget_chars=20000,
            retrieval_top_k=5,
            retrieval_budget_chars=8000,
            compression_max_tool_result_chars=700,
            credentials=service,
        )

        self.assertEqual(updated["governance_profile"], "strict")
        self.assertEqual(updated["context_strategy"], "rag-select")
        self.assertEqual(updated["max_steps"], 8)
        self.assertEqual(updated["context_budget_chars"], 20000)

        with self.assertRaises(ValueError):
            update_settings(
                db_path,
                user_id,
                governance_profile="unsafe",
                context_strategy="rag-select",
                max_steps=8,
                context_budget_chars=20000,
                retrieval_top_k=5,
                retrieval_budget_chars=8000,
                compression_max_tool_result_chars=700,
                credentials=service,
            )
        with self.assertRaises(ValueError):
            update_settings(
                db_path,
                user_id,
                governance_profile="review",
                context_strategy="unsafe-context",
                max_steps=8,
                context_budget_chars=20000,
                retrieval_top_k=5,
                retrieval_budget_chars=8000,
                compression_max_tool_result_chars=700,
                credentials=service,
            )

    def test_invalid_runtime_setting_does_not_partially_update(self):
        db_path, user_id = self.make_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)
        before = get_runtime_settings(db_path, user_id)

        with self.assertRaises(RuntimeConfigError) as raised:
            update_settings(
                db_path,
                user_id,
                governance_profile="strict",
                context_strategy="compressed-rag",
                max_steps=0,
                context_budget_chars=20000,
                retrieval_top_k=5,
                retrieval_budget_chars=8000,
                compression_max_tool_result_chars=700,
                credentials=service,
            )

        self.assertEqual(raised.exception.field, "max_steps")
        self.assertEqual(get_runtime_settings(db_path, user_id), before)

    def test_settings_exposes_encrypted_credential_status(self):
        db_path, user_id = self.make_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)

        settings = upsert_api_key(
            db_path,
            user_id,
            "secret-value",
            service,
        )

        self.assertTrue(settings["api_key_configured"])
        self.assertEqual(settings["api_key_storage"], "encrypted")
        self.assertFalse(settings["api_key_requires_reentry"])
        self.assertTrue(settings["credential_store_available"])
        self.assertEqual(settings["llm_mode"], "mock")
        self.assertNotIn("secret-value", repr(settings))

        cleared = clear_api_key(db_path, user_id, service)
        self.assertFalse(cleared["api_key_configured"])
        self.assertEqual(cleared["api_key_storage"], "not_stored")

    def test_legacy_status_is_requires_reentry(self):
        db_path, user_id = self.make_user()
        with closing(connect_db(db_path)) as conn:
            conn.execute(
                """
                insert into user_credentials (
                    user_id, provider, status
                )
                values (?, 'openai-compatible', 'requires_reentry')
                """,
                (user_id,),
            )
            conn.commit()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)

        settings = get_settings(db_path, user_id, service)

        self.assertFalse(settings["api_key_configured"])
        self.assertEqual(settings["api_key_storage"], "requires_reentry")
        self.assertTrue(settings["api_key_requires_reentry"])

    def test_upsert_api_key_rejects_empty_key(self):
        db_path, user_id = self.make_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)

        with self.assertRaises(InvalidCredential):
            upsert_api_key(db_path, user_id, "   ", service)


if __name__ == "__main__":
    unittest.main()
