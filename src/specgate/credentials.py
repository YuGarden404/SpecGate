from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    message: str


def credential_status(provider: str) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus("mock", True, True, "mock mode does not require credentials")
    return CredentialStatus(
        provider=provider,
        configured=False,
        safe_to_run=False,
        message="real provider credentials are not configured; use OS keyring support before enabling this provider",
    )
