from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


KEYRING_SERVICE = "specgate"


class CredentialStoreError(ValueError):
    code = "credential_store_error"


class CredentialStoreUnavailable(CredentialStoreError):
    code = "credential_store_unavailable"


class CredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...

    def set(self, provider: str, secret: str) -> None: ...

    def clear(self, provider: str) -> None: ...


class KeyringCredentialStore:
    def __init__(self, backend=None):
        self.backend = backend or keyring

    def get(self, provider: str) -> str | None:
        try:
            return self.backend.get_password(KEYRING_SERVICE, provider)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc

    def set(self, provider: str, secret: str) -> None:
        try:
            self.backend.set_password(KEYRING_SERVICE, provider, secret)
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc

    def clear(self, provider: str) -> None:
        try:
            self.backend.delete_password(KEYRING_SERVICE, provider)
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CredentialStoreUnavailable(
                "credential store is unavailable"
            ) from exc
