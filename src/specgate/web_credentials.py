from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, replace
import hashlib
import hmac
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


class CredentialMissing(WebCredentialError):
    code = "credential_missing"


class CredentialChanged(WebCredentialError):
    code = "credential_changed"


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


@dataclass(frozen=True)
class CredentialSnapshot:
    exists: bool
    configured: bool
    requires_reentry: bool
    store_available: bool
    fingerprint: str | None


_FINGERPRINT_FIELDS = (
    "provider",
    "status",
    "ciphertext",
    "nonce",
    "key_version",
    "key_id",
    "updated_at",
)


def _credential_fingerprint(row) -> str:
    digest = hashlib.sha256(b"specgate:web-credential-fingerprint:v1")
    for field in _FINGERPRINT_FIELDS:
        value = row[field]
        if value is None:
            kind = b"n"
            encoded = b""
        elif isinstance(value, bytes):
            kind = b"b"
            encoded = value
        else:
            kind = b"s"
            encoded = str(value).encode("utf-8")
        name = field.encode("ascii")
        digest.update(len(name).to_bytes(2, "big"))
        digest.update(name)
        digest.update(kind)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


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
        return self._status_from_row(row)

    def _status_from_row(self, row) -> WebCredentialStatus:
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

    def snapshot(self, user_id: int, *, conn=None) -> CredentialSnapshot:
        owned_connection = conn is None
        active_connection = connect_db(self.db_path) if owned_connection else conn
        try:
            row = self._load_from_connection(active_connection, user_id)
            if row is None:
                return CredentialSnapshot(
                    False,
                    False,
                    False,
                    self.cipher is not None,
                    None,
                )
            status = self._status_from_row(row)
            return CredentialSnapshot(
                True,
                status.configured,
                status.requires_reentry,
                status.store_available,
                _credential_fingerprint(row),
            )
        finally:
            if owned_connection:
                active_connection.close()

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
        return self._decrypt_row(user_id, row)

    def get_matching(self, user_id: int, expected_fingerprint: str) -> str:
        row = self._load(user_id)
        if row is None:
            raise CredentialMissing("credential is missing")
        actual_fingerprint = _credential_fingerprint(row)
        if not hmac.compare_digest(actual_fingerprint, expected_fingerprint):
            raise CredentialChanged("credential has changed")
        return self._decrypt_row(user_id, row)

    def _decrypt_row(self, user_id: int, row) -> str:
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

    def _load_from_connection(self, conn, user_id: int):
        return conn.execute(
            """
            select * from user_credentials
            where user_id = ? and provider = ?
            """,
            (user_id, WEB_PROVIDER),
        ).fetchone()

    def _load(self, user_id: int):
        conn = connect_db(self.db_path)
        try:
            return self._load_from_connection(conn, user_id)
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
