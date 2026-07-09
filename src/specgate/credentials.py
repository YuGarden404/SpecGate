from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    message: str


def credential_status(provider: str, env_file: Path | None = None) -> CredentialStatus:
    return credential_status_from_env(provider, env_file)


def _env_name(provider: str) -> str:
    return ENV_NAMES.get(provider, f"SPECGATE_{provider.upper()}_API_KEY")


def _read_env_file(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_file(env_file: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    if lines:
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif env_file.exists():
        env_file.unlink()


def credential_status_from_env(provider: str, env_file: Path | None = None) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus("mock", True, True, "mock mode does not require credentials")
    env_name = _env_name(provider)
    configured = bool(os.environ.get(env_name))
    if not configured and env_file is not None:
        configured = bool(_read_env_file(env_file).get(env_name))
    if configured:
        return CredentialStatus(
            provider=provider,
            configured=True,
            safe_to_run=True,
            message=f"{provider} credential is configured via {env_name}; secret value is hidden",
        )
    return CredentialStatus(
        provider=provider,
        configured=False,
        safe_to_run=False,
        message=f"{provider} credential is not configured; use credentials set or OS keyring before enabling this provider",
    )


def set_credential(provider: str, secret: str, env_file: Path) -> None:
    if provider == "mock":
        raise ValueError("mock provider does not need credentials")
    if not secret:
        raise ValueError("secret must be non-empty")
    values = _read_env_file(env_file)
    values[_env_name(provider)] = secret
    _write_env_file(env_file, values)


def clear_credential(provider: str, env_file: Path) -> None:
    values = _read_env_file(env_file)
    values.pop(_env_name(provider), None)
    _write_env_file(env_file, values)
