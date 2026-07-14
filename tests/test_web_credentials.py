import base64
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_credentials import (
    CredentialDecryptionFailed,
    CredentialRequiresReentry,
    CredentialStoreUnavailable,
    InvalidCredentialKey,
    WebCredentialCipher,
    WebCredentialService,
    load_web_credential_key,
)


TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class WebCredentialCipherTests(unittest.TestCase):
    def make_database_user(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        return db_path, int(user["id"])

    def test_loads_exactly_32_byte_base64_key(self):
        key = load_web_credential_key(TEST_KEY)
        self.assertIsNotNone(key)
        self.assertEqual(key.version, 1)
        self.assertTrue(key.key_id)

        with self.assertRaises(InvalidCredentialKey):
            load_web_credential_key(
                base64.urlsafe_b64encode(b"short").decode("ascii")
            )

    def test_encrypt_round_trip_uses_random_nonce(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))

        first = cipher.encrypt(7, "openai-compatible", "secret-value")
        second = cipher.encrypt(7, "openai-compatible", "secret-value")

        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertEqual(
            cipher.decrypt(7, "openai-compatible", first),
            "secret-value",
        )

    def test_ciphertext_cannot_move_between_users(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))
        encrypted = cipher.encrypt(7, "openai-compatible", "secret-value")

        with self.assertRaises(CredentialDecryptionFailed):
            cipher.decrypt(8, "openai-compatible", encrypted)

    def test_tampering_fails_without_secret_in_error(self):
        cipher = WebCredentialCipher(load_web_credential_key(TEST_KEY))
        encrypted = cipher.encrypt(
            7,
            "openai-compatible",
            "SECRET_SENTINEL_web",
        )
        tampered = encrypted.with_ciphertext(
            encrypted.ciphertext[:-1]
            + bytes([encrypted.ciphertext[-1] ^ 1])
        )

        with self.assertRaises(CredentialDecryptionFailed) as raised:
            cipher.decrypt(7, "openai-compatible", tampered)

        self.assertNotIn("SECRET_SENTINEL_web", str(raised.exception))

    def test_service_stores_ciphertext_and_round_trips(self):
        db_path, user_id = self.make_database_user()
        service = WebCredentialService.from_key_value(db_path, TEST_KEY)
        secret = "SECRET_SENTINEL_database"

        status = service.put(user_id, secret)

        self.assertTrue(status.configured)
        self.assertEqual(status.storage, "encrypted")
        self.assertEqual(service.get(user_id), secret)
        with closing(connect_db(db_path)) as conn:
            row = conn.execute(
                """
                select ciphertext, nonce, key_version, key_id
                from user_credentials
                where user_id = ? and provider = 'openai-compatible'
                """,
                (user_id,),
            ).fetchone()
        self.assertNotIn(secret.encode("utf-8"), row["ciphertext"])
        self.assertEqual(len(row["nonce"]), 12)

    def test_changed_master_key_requires_reentry_without_decrypting(self):
        db_path, user_id = self.make_database_user()
        first = WebCredentialService.from_key_value(db_path, TEST_KEY)
        second_key = base64.urlsafe_b64encode(
            bytes(reversed(range(32)))
        ).decode("ascii")
        second = WebCredentialService.from_key_value(db_path, second_key)
        first.put(user_id, "secret-value")

        status = second.status(user_id)

        self.assertFalse(status.configured)
        self.assertTrue(status.requires_reentry)
        self.assertEqual(status.storage, "requires_reentry")
        with self.assertRaises(CredentialRequiresReentry):
            second.get(user_id)

    def test_missing_key_blocks_put_but_allows_clear(self):
        db_path, user_id = self.make_database_user()
        configured = WebCredentialService.from_key_value(db_path, TEST_KEY)
        unavailable = WebCredentialService.from_key_value(db_path, None)
        configured.put(user_id, "secret-value")

        with self.assertRaises(CredentialStoreUnavailable):
            unavailable.put(user_id, "replacement")

        unavailable.clear(user_id)
        status = unavailable.status(user_id)
        self.assertEqual(status.storage, "not_stored")
        self.assertFalse(status.store_available)


if __name__ == "__main__":
    unittest.main()
