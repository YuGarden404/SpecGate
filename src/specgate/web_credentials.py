from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from specgate.web_db import connect_db


WEB_PROVIDER = "openai-compatible"
WEB_KEY_VERSION = 1
MAX_CREDENTIAL_CHARS = 4096


class WebCredentialError(ValueError):
    code = "web_credential_error"


class InvalidCredentialKey(WebCredentialError):
    code = "invalid_credential_key"


class InvalidCredential(WebCredentialError):
    code = "invalid_credential"


class CredentialStoreUnavailable(WebCredentialError):
    code = "credential_store_unavailable"


class CredentialDecryptionFailed(WebCredentialError):
    code = "credential_decryption_failed"


class CredentialRequiresReentry(WebCredentialError):
    code = "credential_requires_reentry"


@dataclass(frozen=True)
class WebCredentialKey:
    value: bytes
    version: int
    key_id: str


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: bytes
    nonce: bytes
    key_version: int
    key_id: str

    def with_ciphertext(self, ciphertext: bytes) -> "EncryptedCredential":
        return replace(self, ciphertext=ciphertext)


def load_web_credential_key(raw: str | None) -> WebCredentialKey | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = base64.b64decode(
            raw.strip(),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise InvalidCredentialKey("invalid credential master key") from exc
    if len(value) != 32:
        raise InvalidCredentialKey("invalid credential master key")
    key_id = (
        base64.urlsafe_b64encode(hashlib.sha256(value).digest()[:12])
        .decode("ascii")
        .rstrip("=")
    )
    return WebCredentialKey(value, WEB_KEY_VERSION, key_id)


def _validate_secret(secret: str) -> str:
    normalized = secret.strip()
    if not normalized or len(normalized) > MAX_CREDENTIAL_CHARS:
        raise InvalidCredential("invalid credential")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise InvalidCredential("invalid credential")
    return normalized


class WebCredentialCipher:
    def __init__(self, key: WebCredentialKey):
        self.key = key
        self.aes = AESGCM(key.value)

    def _aad(self, user_id: int, provider: str) -> bytes:
        return (
            f"specgate:web:user:{user_id}:provider:{provider}:"
            f"v{self.key.version}:key:{self.key.key_id}"
        ).encode("utf-8")

    def encrypt(
        self,
        user_id: int,
        provider: str,
        secret: str,
    ) -> EncryptedCredential:
        plaintext = _validate_secret(secret).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = self.aes.encrypt(
            nonce,
            plaintext,
            self._aad(user_id, provider),
        )
        return EncryptedCredential(
            ciphertext,
            nonce,
            self.key.version,
            self.key.key_id,
        )

    def decrypt(
        self,
        user_id: int,
        provider: str,
        encrypted: EncryptedCredential,
    ) -> str:
        if (
            encrypted.key_version != self.key.version
            or encrypted.key_id != self.key.key_id
        ):
            raise CredentialRequiresReentry("credential requires re-entry")
        try:
            plaintext = self.aes.decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                self._aad(user_id, provider),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise CredentialDecryptionFailed(
                "credential could not be decrypted"
            ) from exc


@dataclass(frozen=True)
class WebCredentialStatus:
    configured: bool
    storage: str
    requires_reentry: bool
    store_available: bool


class WebCredentialService:
    def __init__(
        self,
        db_path: Path,
        cipher: WebCredentialCipher | None,
        unavailable_code: str | None = None,
    ):
        self.db_path = db_path
        self.cipher = cipher
        self.unavailable_code = unavailable_code

    @classmethod
    def from_key_value(
        cls,
        db_path: Path,
        raw_key: str | None,
    ) -> "WebCredentialService":
        try:
            key = load_web_credential_key(raw_key)
        except InvalidCredentialKey:
            return cls(db_path, None, "invalid_credential_key")
        if key is None:
            return cls(db_path, None, "credential_store_unavailable")
        return cls(db_path, WebCredentialCipher(key))

    def status(self, user_id: int) -> WebCredentialStatus:
        row = self._load(user_id)
        if row is None:
            return WebCredentialStatus(
                False,
                "not_stored",
                False,
                self.cipher is not None,
            )
        if row["status"] == "requires_reentry":
            return WebCredentialStatus(
                False,
                "requires_reentry",
                True,
                self.cipher is not None,
            )
        if self.cipher is not None:
            if (
                row["key_version"] != self.cipher.key.version
                or row["key_id"] != self.cipher.key.key_id
            ):
                return WebCredentialStatus(
                    False,
                    "requires_reentry",
                    True,
                    True,
                )
            return WebCredentialStatus(True, "encrypted", False, True)
        return WebCredentialStatus(False, "unavailable", False, False)

    def _require_cipher(self) -> WebCredentialCipher:
        if self.cipher is not None:
            return self.cipher
        if self.unavailable_code == "invalid_credential_key":
            raise InvalidCredentialKey("invalid credential master key")
        raise CredentialStoreUnavailable("credential store is unavailable")

    def put(self, user_id: int, secret: str) -> WebCredentialStatus:
        cipher = self._require_cipher()
        encrypted = cipher.encrypt(user_id, WEB_PROVIDER, secret)
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                """
                insert into user_credentials (
                    user_id, provider, status, ciphertext, nonce,
                    key_version, key_id, updated_at
                )
                values (?, ?, 'configured', ?, ?, ?, ?, current_timestamp)
                on conflict(user_id, provider) do update set
                    status = 'configured',
                    ciphertext = excluded.ciphertext,
                    nonce = excluded.nonce,
                    key_version = excluded.key_version,
                    key_id = excluded.key_id,
                    updated_at = current_timestamp
                """,
                (
                    user_id,
                    WEB_PROVIDER,
                    encrypted.ciphertext,
                    encrypted.nonce,
                    encrypted.key_version,
                    encrypted.key_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.status(user_id)

    def get(self, user_id: int) -> str | None:
        row = self._load(user_id)
        if row is None:
            return None
        if row["status"] == "requires_reentry":
            raise CredentialRequiresReentry("credential requires re-entry")
        cipher = self._require_cipher()
        if (
            row["key_version"] != cipher.key.version
            or row["key_id"] != cipher.key.key_id
        ):
            raise CredentialRequiresReentry("credential requires re-entry")
        encrypted = EncryptedCredential(
            row["ciphertext"],
            row["nonce"],
            row["key_version"],
            row["key_id"],
        )
        return cipher.decrypt(user_id, WEB_PROVIDER, encrypted)

    def _load(self, user_id: int):
        conn = connect_db(self.db_path)
        try:
            return conn.execute(
                """
                select * from user_credentials
                where user_id = ? and provider = ?
                """,
                (user_id, WEB_PROVIDER),
            ).fetchone()
        finally:
            conn.close()

    def clear(self, user_id: int) -> WebCredentialStatus:
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                """
                delete from user_credentials
                where user_id = ? and provider = ?
                """,
                (user_id, WEB_PROVIDER),
            )
            conn.commit()
        finally:
            conn.close()
        return self.status(user_id)
