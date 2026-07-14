import unittest

from keyring.errors import KeyringError, PasswordDeleteError

from specgate.credential_store import (
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        key = (service, username)
        if key not in self.values:
            raise PasswordDeleteError("missing")
        del self.values[key]


class BrokenKeyring:
    def get_password(self, service, username):
        raise KeyringError("backend unavailable")

    def set_password(self, service, username, password):
        raise KeyringError("backend unavailable")

    def delete_password(self, service, username):
        raise KeyringError("backend unavailable")


class CredentialStoreTests(unittest.TestCase):
    def test_keyring_round_trip_and_idempotent_clear(self):
        backend = MemoryKeyring()
        store = KeyringCredentialStore(backend=backend)

        self.assertIsNone(store.get("openai-compatible"))
        store.set("openai-compatible", "secret-value")
        self.assertEqual(store.get("openai-compatible"), "secret-value")
        store.clear("openai-compatible")
        store.clear("openai-compatible")
        self.assertIsNone(store.get("openai-compatible"))

    def test_keyring_errors_are_wrapped_without_secret(self):
        store = KeyringCredentialStore(backend=BrokenKeyring())
        sentinel = "SECRET_SENTINEL_credential_store"

        with self.assertRaises(CredentialStoreUnavailable) as raised:
            store.set("openai-compatible", sentinel)

        self.assertEqual(raised.exception.code, "credential_store_unavailable")
        self.assertNotIn(sentinel, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
