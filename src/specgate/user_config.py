from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping


SCHEMA_VERSION = 1
SUPPORTED_PROVIDER = "openai-compatible"
MAX_CONFIG_VALUE_CHARS = 2048


class UserConfigError(ValueError):
    pass


@dataclass(frozen=True)
class UserLLMConfig:
    provider: str
    base_url: str
    model: str


def user_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    override = values.get("SPECGATE_CONFIG_HOME")
    if override:
        return Path(override).expanduser() / "config.json"

    user_home = Path.home() if home is None else home
    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        base = Path(
            values.get("APPDATA", str(user_home / "AppData" / "Roaming"))
        )
        return base / "SpecGate" / "config.json"

    xdg = values.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else user_home / ".config"
    return base / "specgate" / "config.json"


def _config_value(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise UserConfigError(f"invalid user config: {name}")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_CONFIG_VALUE_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise UserConfigError(f"invalid user config: {name}")
    return normalized


def _from_payload(payload: object) -> UserLLMConfig:
    if not isinstance(payload, dict):
        raise UserConfigError("invalid user config: root")
    expected = {"schema_version", "provider", "base_url", "model"}
    if set(payload) != expected or payload.get("schema_version") != SCHEMA_VERSION:
        raise UserConfigError("invalid user config: schema")
    provider = _config_value("provider", payload["provider"])
    if provider != SUPPORTED_PROVIDER:
        raise UserConfigError("invalid user config: provider")
    return UserLLMConfig(
        provider=provider,
        base_url=_config_value("base_url", payload["base_url"]),
        model=_config_value("model", payload["model"]),
    )


def load_user_llm_config(*, path: Path | None = None) -> UserLLMConfig | None:
    target = user_config_path() if path is None else path
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserConfigError(f"invalid user config: {target}") from exc
    return _from_payload(payload)


def save_user_llm_config(
    config: UserLLMConfig,
    *,
    path: Path | None = None,
) -> None:
    normalized = _from_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
        }
    )
    target = user_config_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": normalized.provider,
        "base_url": normalized.base_url,
        "model": normalized.model,
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise UserConfigError(f"could not save user config: {target}") from exc


def resolve_user_llm_config(
    *,
    provider: str,
    model: str | None,
    base_url: str | None,
    environ: Mapping[str, str] | None = None,
    saved: UserLLMConfig | None = None,
) -> UserLLMConfig:
    values = os.environ if environ is None else environ
    resolved_model = (
        model
        or values.get("SPECGATE_LLM_MODEL")
        or (saved.model if saved else None)
    )
    resolved_base_url = (
        base_url
        or values.get("SPECGATE_LLM_BASE_URL")
        or (saved.base_url if saved else None)
    )
    if provider != SUPPORTED_PROVIDER:
        raise UserConfigError(f"unsupported provider: {provider}")
    if not resolved_model or not resolved_base_url:
        raise UserConfigError(
            "LLM configuration is incomplete; run: specgate configure"
        )
    return _from_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "provider": provider,
            "base_url": resolved_base_url,
            "model": resolved_model,
        }
    )
