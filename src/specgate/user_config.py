from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
SUPPORTED_PROVIDER = "openai-compatible"
SHELL_MODES = frozenset({"mock", "real"})
MAX_CONFIG_VALUE_CHARS = 2048


class UserConfigError(ValueError):
    pass


@dataclass(frozen=True)
class UserLLMConfig:
    provider: str
    base_url: str
    model: str


@dataclass(frozen=True)
class UserShellConfig:
    mode: str
    workspace: str | None
    verbose: bool
    llm: UserLLMConfig | None

    def __post_init__(self) -> None:
        if self.mode not in SHELL_MODES:
            raise UserConfigError("invalid user config: mode")
        if self.workspace is not None:
            _config_value("workspace", self.workspace)
        if type(self.verbose) is not bool:
            raise UserConfigError("invalid user config: verbose")
        if self.llm is not None and not isinstance(self.llm, UserLLMConfig):
            raise UserConfigError("invalid user config: llm")


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


def _llm_from_values(
    provider_value: object,
    base_url_value: object,
    model_value: object,
) -> UserLLMConfig:
    provider = _config_value("provider", provider_value)
    if provider != SUPPORTED_PROVIDER:
        raise UserConfigError("invalid user config: provider")
    return UserLLMConfig(
        provider=provider,
        base_url=_config_value("base_url", base_url_value),
        model=_config_value("model", model_value),
    )


def _shell_from_payload(payload: object) -> UserShellConfig:
    if not isinstance(payload, dict):
        raise UserConfigError("invalid user config: root")
    schema_version = payload.get("schema_version")
    if schema_version == LEGACY_SCHEMA_VERSION:
        expected = {"schema_version", "provider", "base_url", "model"}
        if set(payload) != expected:
            raise UserConfigError("invalid user config: schema")
        return UserShellConfig(
            mode="real",
            workspace=None,
            verbose=False,
            llm=_llm_from_values(
                payload["provider"],
                payload["base_url"],
                payload["model"],
            ),
        )

    expected = {
        "schema_version",
        "provider",
        "base_url",
        "model",
        "mode",
        "workspace",
        "verbose",
    }
    if schema_version != SCHEMA_VERSION or set(payload) != expected:
        raise UserConfigError("invalid user config: schema")

    llm_values = (
        payload["provider"],
        payload["base_url"],
        payload["model"],
    )
    if all(value is None for value in llm_values):
        llm = None
    elif all(value is not None for value in llm_values):
        llm = _llm_from_values(*llm_values)
    else:
        raise UserConfigError("invalid user config: incomplete llm")

    workspace_value = payload["workspace"]
    workspace = (
        None
        if workspace_value is None
        else _config_value("workspace", workspace_value)
    )
    return UserShellConfig(
        mode=_config_value("mode", payload["mode"]),
        workspace=workspace,
        verbose=payload["verbose"],
        llm=llm,
    )


def _read_payload(target: Path) -> object:
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserConfigError(f"invalid user config: {target}") from exc


def load_user_shell_config(
    *,
    path: Path | None = None,
) -> UserShellConfig | None:
    target = user_config_path() if path is None else path
    if not target.exists():
        return None
    return _shell_from_payload(_read_payload(target))


def load_user_llm_config(*, path: Path | None = None) -> UserLLMConfig | None:
    shell = load_user_shell_config(path=path)
    return None if shell is None else shell.llm


def _normalized_shell_config(config: UserShellConfig) -> UserShellConfig:
    if not isinstance(config, UserShellConfig):
        raise UserConfigError("invalid user config: root")
    llm = (
        None
        if config.llm is None
        else _llm_from_values(
            config.llm.provider,
            config.llm.base_url,
            config.llm.model,
        )
    )
    workspace = (
        None
        if config.workspace is None
        else _config_value("workspace", config.workspace)
    )
    return UserShellConfig(
        mode=_config_value("mode", config.mode),
        workspace=workspace,
        verbose=config.verbose,
        llm=llm,
    )


def save_user_shell_config(
    config: UserShellConfig,
    *,
    path: Path | None = None,
) -> None:
    normalized = _normalized_shell_config(config)
    target = user_config_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    llm = normalized.llm
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": None if llm is None else llm.provider,
        "base_url": None if llm is None else llm.base_url,
        "model": None if llm is None else llm.model,
        "mode": normalized.mode,
        "workspace": normalized.workspace,
        "verbose": normalized.verbose,
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


def save_user_llm_config(
    config: UserLLMConfig,
    *,
    path: Path | None = None,
) -> None:
    normalized = _llm_from_values(
        config.provider,
        config.base_url,
        config.model,
    )
    target = user_config_path() if path is None else path
    current = load_user_shell_config(path=target)
    shell = current or UserShellConfig("real", None, False, None)
    save_user_shell_config(replace(shell, llm=normalized), path=target)


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
    return _llm_from_values(
        provider,
        resolved_base_url,
        resolved_model,
    )
