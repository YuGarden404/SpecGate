import unittest

from specgate.credential_store import CredentialStoreUnavailable
from specgate.credentials import (
    CredentialStatus,
    clear_credential,
    credential_status,
    read_credential,
    set_credential,
)


class MemoryStore:
    def __init__(self):
        self.values = {}

    def get(self, provider):
        return self.values.get(provider)

    def set(self, provider, secret):
        self.values[provider] = secret

    def clear(self, provider):
        self.values.pop(provider, None)


class UnavailableStore:
    def get(self, provider):
        raise CredentialStoreUnavailable("credential store is unavailable")

    def set(self, provider, secret):
        raise CredentialStoreUnavailable("credential store is unavailable")

    def clear(self, provider):
        raise CredentialStoreUnavailable("credential store is unavailable")


class CredentialTests(unittest.TestCase):
    def test_mock_mode_needs_no_credentials(self):
        status = credential_status("mock", environ={})

        self.assertEqual(
            status,
            CredentialStatus(
                provider="mock",
                configured=True,
                safe_to_run=True,
                source="mock",
                message="mock mode does not require credentials",
            ),
        )

    def test_environment_overrides_keyring(self):
        store = MemoryStore()
        store.set("openai-compatible", "keyring-secret")
        environ = {"OPENAI_COMPATIBLE_API_KEY": "environment-secret"}

        self.assertEqual(
            read_credential("openai-compatible", store=store, environ=environ),
            "environment-secret",
        )
        self.assertEqual(
            credential_status(
                "openai-compatible",
                store=store,
                environ=environ,
            ).source,
            "environment",
        )

    def test_keyring_is_used_when_environment_is_missing(self):
        store = MemoryStore()
        set_credential("openai-compatible", "keyring-secret", store=store)

        status = credential_status(
            "openai-compatible",
            store=store,
            environ={},
        )

        self.assertEqual(status.source, "keyring")
        self.assertEqual(
            read_credential("openai-compatible", store=store, environ={}),
            "keyring-secret",
        )
        clear_credential("openai-compatible", store=store)
        self.assertFalse(
            credential_status(
                "openai-compatible",
                store=store,
                environ={},
            ).configured
        )

    def test_clear_does_not_hide_active_environment_variable(self):
        store = MemoryStore()
        store.set("openai", "keyring-secret")
        environ = {"OPENAI_API_KEY": "environment-secret"}

        clear_credential("openai", store=store)
        status = credential_status("openai", store=store, environ=environ)

        self.assertTrue(status.configured)
        self.assertEqual(status.source, "environment")

    def test_unavailable_keyring_fails_closed_without_leaking_secret(self):
        sentinel = "SECRET_SENTINEL_unavailable"

        status = credential_status("openai", store=UnavailableStore(), environ={})

        self.assertFalse(status.configured)
        self.assertFalse(status.safe_to_run)
        self.assertEqual(status.source, "unavailable")
        self.assertNotIn(sentinel, status.message)

    def test_set_rejects_empty_oversized_and_control_character_secrets(self):
        store = MemoryStore()

        for secret in ("", "x" * 4097, "valid\nsecret"):
            with self.subTest(secret_length=len(secret)):
                with self.assertRaisesRegex(ValueError, "invalid_credential"):
                    set_credential("openai", secret, store=store)

        self.assertEqual(store.values, {})

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported provider"):
            credential_status("localtest", store=MemoryStore(), environ={})


if __name__ == "__main__":
    unittest.main()
