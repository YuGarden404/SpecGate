from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from specgate.credential_store import (
    CredentialStore,
    CredentialStoreUnavailable,
    KeyringCredentialStore,
)


MAX_CREDENTIAL_CHARS = 4096
ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
SUPPORTED_PROVIDERS = frozenset(ENV_NAMES)


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    source: str
    message: str


def _store(store: CredentialStore | None) -> CredentialStore:
    return store if store is not None else KeyringCredentialStore()


def _validate_provider(provider: str) -> None:
    if provider == "mock":
        return
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")


def _validate_secret(secret: str) -> str:
    normalized = secret.strip()
    if not normalized or len(normalized) > MAX_CREDENTIAL_CHARS:
        raise ValueError("invalid_credential")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("invalid_credential")
    return normalized


def read_credential(
    provider: str,
    *,
    store: CredentialStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    _validate_provider(provider)
    if provider == "mock":
        return None
    values = os.environ if environ is None else environ
    environment_value = values.get(ENV_NAMES[provider])
    if environment_value:
        return environment_value
    return _store(store).get(provider)


def credential_status(
    provider: str,
    *,
    store: CredentialStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus(
            "mock",
            True,
            True,
            "mock",
            "mock mode does not require credentials",
        )
    _validate_provider(provider)
    values = os.environ if environ is None else environ
    if values.get(ENV_NAMES[provider]):
        return CredentialStatus(
            provider,
            True,
            True,
            "environment",
            f"{provider} credential is configured via environment",
        )
    try:
        configured = bool(_store(store).get(provider))
    except CredentialStoreUnavailable:
        return CredentialStatus(
            provider,
            False,
            False,
            "unavailable",
            "credential store is unavailable",
        )
    return CredentialStatus(
        provider,
        configured,
        configured,
        "keyring" if configured else "none",
        (
            f"{provider} credential is configured via system keyring"
            if configured
            else f"{provider} credential is not configured"
        ),
    )


def set_credential(
    provider: str,
    secret: str,
    *,
    store: CredentialStore | None = None,
) -> None:
    _validate_provider(provider)
    if provider == "mock":
        raise ValueError("mock provider does not need credentials")
    _store(store).set(provider, _validate_secret(secret))


def clear_credential(
    provider: str,
    *,
    store: CredentialStore | None = None,
) -> None:
    _validate_provider(provider)
    _store(store).clear(provider)
