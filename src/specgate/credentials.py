from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
SUPPORTED_PROVIDERS = frozenset(ENV_NAMES)


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    message: str


def credential_status(provider: str, env_file: Path | None = None) -> CredentialStatus:
    return credential_status_from_env(provider, env_file)


def _env_name(provider: str) -> str:
    return ENV_NAMES[provider]


def _unsupported_status(provider: str) -> CredentialStatus:
    return CredentialStatus(
        provider=provider,
        configured=False,
        safe_to_run=False,
        message=f"{provider} provider is not supported by the credential fallback",
    )


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


def _set_env_line(env_file: Path, key: str, value: str) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        candidate = stripped.removeprefix("export ").split("=", 1)[0].strip() if "=" in stripped else ""
        if candidate == key:
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    env_file.write_text("\n".join(output) + "\n", encoding="utf-8")


def _remove_env_line(env_file: Path, key: str) -> None:
    if not env_file.exists():
        return
    output: list[str] = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        candidate = stripped.removeprefix("export ").split("=", 1)[0].strip() if "=" in stripped else ""
        if candidate != key:
            output.append(line)
    env_file.write_text("\n".join(output) + ("\n" if output else ""), encoding="utf-8")


def credential_status_from_env(provider: str, env_file: Path | None = None) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus("mock", True, True, "mock mode does not require credentials")
    if provider not in SUPPORTED_PROVIDERS:
        return _unsupported_status(provider)
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
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    if not secret:
        raise ValueError("secret must be non-empty")
    _set_env_line(env_file, _env_name(provider), secret)


def clear_credential(provider: str, env_file: Path) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    _remove_env_line(env_file, _env_name(provider))
