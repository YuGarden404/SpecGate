from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from specgate.credential_store import CredentialStore, KeyringCredentialStore
from specgate.credentials import set_credential
from specgate.llm_transport import LLMEndpointPolicy, LLMTransportError
from specgate.shell_terminal import ShellTerminal
from specgate.user_config import (
    MAX_CONFIG_VALUE_CHARS,
    SUPPORTED_PROVIDER,
    UserConfigError,
    UserLLMConfig,
    UserShellConfig,
    load_user_shell_config,
    load_user_shell_config_draft,
    save_user_shell_config,
    user_config_path,
)


COMMANDS = frozenset(
    {
        "help",
        "status",
        "setup",
        "mode",
        "workspace",
        "model",
        "url",
        "api-key",
        "verbose",
        "approvals",
        "clear",
        "exit",
    }
)


class _CredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...

    def set(self, provider: str, secret: str) -> None: ...

    def clear(self, provider: str) -> None: ...


@dataclass(frozen=True)
class ConfigCommandResult:
    ok: bool
    config: UserShellConfig
    request_connection_test: bool = False


def _config_text(name: str, value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_CONFIG_VALUE_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise ValueError(f"invalid_{name}")
    return normalized


def normalize_base_url(raw_url: str) -> str:
    value = _config_text("url", raw_url)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("invalid_url") from exc
    if host is None:
        raise ValueError("invalid_url")
    authority = host if port == 443 else f"{host}:{port}"
    try:
        policy = LLMEndpointPolicy.from_csv(authority)
        return policy.normalize(value).base_url
    except (ValueError, LLMTransportError) as exc:
        raise ValueError("invalid_url") from exc


class ShellConfigController:
    def __init__(
        self,
        terminal: ShellTerminal,
        *,
        path: Path | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self._terminal = terminal
        self._path = user_config_path() if path is None else Path(path)
        self._credential_store: _CredentialStore = (
            KeyringCredentialStore()
            if credential_store is None
            else credential_store
        )
        draft = load_user_shell_config_draft(path=self._path)
        try:
            loaded = load_user_shell_config(path=self._path)
        except UserConfigError:
            loaded = None
        recovered_llm = None
        if (
            draft is not None
            and draft.provider is not None
            and draft.base_url is not None
            and draft.model is not None
        ):
            recovered_llm = UserLLMConfig(
                draft.provider,
                draft.base_url,
                draft.model,
            )
        self._had_config = loaded is not None or draft is not None
        self._mode_valid = loaded is not None or (
            draft is not None and draft.mode is not None
        )
        self._draft_base_url = (
            loaded.llm.base_url
            if loaded is not None and loaded.llm is not None
            else None if draft is None else draft.base_url
        )
        self._draft_model = (
            loaded.llm.model
            if loaded is not None and loaded.llm is not None
            else None if draft is None else draft.model
        )
        self.config = loaded or UserShellConfig(
            "mock" if draft is None or draft.mode is None else draft.mode,
            None if draft is None else draft.workspace,
            False if draft is None else draft.verbose,
            recovered_llm,
        )

    def ensure_ready(self) -> UserShellConfig:
        if (
            not self._had_config
            or not self._mode_valid
            or not self._workspace_valid(self.config.workspace)
            or (
                self.config.mode == "real"
                and not self._real_complete(self.config)
            )
        ):
            self.config = self._setup(full=False)
        self.print_status()
        return self.config

    def setup(self) -> UserShellConfig:
        self.config = self._setup(full=True)
        return self.config

    def execute(
        self,
        name: str,
        argument: str | None,
    ) -> ConfigCommandResult:
        command = name.strip().lower()
        if command not in COMMANDS:
            self._terminal.write(
                f"Unknown command: /{command}. Type /help for commands.",
                style="error",
            )
            return ConfigCommandResult(False, self.config)
        if command == "help":
            self._print_help()
            return ConfigCommandResult(True, self.config)
        if command == "status":
            self.print_status()
            return ConfigCommandResult(True, self.config)
        if command == "clear":
            self._terminal.clear()
            return ConfigCommandResult(True, self.config)
        if command in {"approvals", "exit"}:
            return ConfigCommandResult(True, self.config)
        if command == "setup":
            try:
                config = self.setup()
            except (ValueError, UserConfigError):
                self._terminal.write("Setup failed; previous settings were kept.", style="error")
                return ConfigCommandResult(False, self.config)
            return ConfigCommandResult(
                True,
                config,
                request_connection_test=config.mode == "real",
            )
        if command == "mode":
            return self._set_mode(argument)
        if command == "workspace":
            return self._set_workspace(argument)
        if command == "model":
            return self._set_model(argument)
        if command == "url":
            return self._set_url(argument)
        if command == "api-key":
            return self._set_api_key()
        if command == "verbose":
            return self._set_verbose(argument)
        raise AssertionError("unreachable shell configuration command")

    def print_status(self) -> None:
        config = self.config
        mode = "Real LLM" if config.mode == "real" else "MockLLM Demo"
        self._terminal.write(f"Mode: {mode}")
        self._terminal.write(
            f"Model: {config.llm.model if config.llm is not None else 'not configured'}"
        )
        self._terminal.write(
            "Base URL: "
            + (
                config.llm.base_url
                if config.llm is not None
                else "not configured"
            )
        )
        if config.mode == "mock":
            self._terminal.write("API key: not required in Mock mode")
        else:
            configured = self._credential_configured()
            self._terminal.write(
                "API key: "
                + ("securely configured" if configured else "not configured")
            )
            self._terminal.write(
                f"Credential source: {'keyring' if configured else 'none'}"
            )
        self._terminal.write(
            f"Workspace: {config.workspace or 'not configured'}"
        )
        self._terminal.write(f"Verbose: {'on' if config.verbose else 'off'}")

    def _setup(self, *, full: bool) -> UserShellConfig:
        previous = self.config
        mode = previous.mode
        if full or not self._mode_valid:
            mode = self._read_choice(
                "Mode [mock/real]",
                {"mock", "real"},
                default=mode if self._had_config else None,
            )

        workspace = previous.workspace
        if full or not self._workspace_valid(workspace):
            workspace = self._read_workspace(workspace)

        llm = previous.llm
        new_secret: str | None = None
        if mode == "real":
            base_url = (
                self._draft_base_url if llm is None else llm.base_url
            )
            model = self._draft_model if llm is None else llm.model
            try:
                base_url = normalize_base_url(base_url or "")
            except ValueError:
                base_url = None
            try:
                model = _config_text("model", model or "")
            except ValueError:
                model = None
            if full or base_url is None:
                base_url = self._read_url(base_url)
            if full or model is None:
                model = self._read_model(model)
            llm = UserLLMConfig(SUPPORTED_PROVIDER, base_url, model)
            if not self._credential_configured():
                new_secret = self._terminal.read("API key: ", secret=True)
                _config_text("api_key", new_secret)

        candidate = UserShellConfig(mode, workspace, previous.verbose, llm)
        if new_secret is not None:
            self._persist_with_secret(candidate, new_secret)
        else:
            self._persist(candidate)
        self._had_config = True
        self._mode_valid = True
        return candidate

    def _set_mode(self, argument: str | None) -> ConfigCommandResult:
        value = (
            self._read_choice("Mode [mock/real]", {"mock", "real"}, self.config.mode)
            if argument is None
            else argument.strip().lower()
        )
        if value not in {"mock", "real"}:
            return self._failed("Mode must be mock or real.")
        if value == "mock":
            candidate = replace(self.config, mode="mock")
            return self._save_result(candidate)

        previous = self.config
        try:
            llm = previous.llm
            base_url = self._read_url(None) if llm is None else llm.base_url
            model = self._read_model(None) if llm is None else llm.model
            new_secret = None
            if not self._credential_configured():
                new_secret = self._terminal.read("API key: ", secret=True)
                _config_text("api_key", new_secret)
            candidate = replace(
                previous,
                mode="real",
                llm=UserLLMConfig(SUPPORTED_PROVIDER, base_url, model),
            )
            if new_secret is not None:
                self._persist_with_secret(candidate, new_secret)
            else:
                self._persist(candidate)
        except (ValueError, UserConfigError):
            return self._failed("Real LLM configuration was not changed.")
        return ConfigCommandResult(True, candidate, request_connection_test=True)

    def _set_workspace(self, argument: str | None) -> ConfigCommandResult:
        raw = (
            self._terminal.read("Workspace: ")
            if argument is None
            else argument
        )
        try:
            workspace = self._normalize_workspace(raw)
        except ValueError:
            return self._failed("Workspace must be an accessible directory.")
        return self._save_result(replace(self.config, workspace=workspace))

    def _set_model(self, argument: str | None) -> ConfigCommandResult:
        if self.config.llm is None:
            return self._failed("Configure a Base URL with /mode real first.")
        raw = self._terminal.read("Model: ") if argument is None else argument
        try:
            model = _config_text("model", raw)
        except ValueError:
            return self._failed("Model must be non-empty.")
        return self._save_result(
            replace(self.config, llm=replace(self.config.llm, model=model)),
            request_connection_test=self.config.mode == "real",
        )

    def _set_url(self, argument: str | None) -> ConfigCommandResult:
        if self.config.llm is None:
            return self._failed("Configure a model with /mode real first.")
        raw = self._terminal.read("Base URL: ") if argument is None else argument
        try:
            base_url = normalize_base_url(raw)
        except ValueError:
            return self._failed("Base URL must be a valid HTTPS URL.")
        return self._save_result(
            replace(
                self.config,
                llm=replace(self.config.llm, base_url=base_url),
            ),
            request_connection_test=self.config.mode == "real",
        )

    def _set_api_key(self) -> ConfigCommandResult:
        secret = self._terminal.read("API key: ", secret=True)
        try:
            _config_text("api_key", secret)
            self._store_secret(secret)
        except ValueError:
            return self._failed("API key was not changed.")
        self._terminal.write("API key: securely configured", style="success")
        return ConfigCommandResult(
            True,
            self.config,
            request_connection_test=self.config.mode == "real",
        )

    def _set_verbose(self, argument: str | None) -> ConfigCommandResult:
        value = (
            self._terminal.read("Verbose [on/off]: ")
            if argument is None
            else argument
        ).strip().lower()
        if value not in {"on", "off"}:
            return self._failed("Verbose must be on or off.")
        return self._save_result(replace(self.config, verbose=value == "on"))

    def _read_choice(
        self,
        prompt: str,
        choices: set[str],
        default: str | None,
    ) -> str:
        while True:
            suffix = f" [{default}]" if default is not None else ""
            value = self._terminal.read(f"{prompt}{suffix}: ").strip().lower()
            if not value and default is not None:
                return default
            if value in choices:
                return value
            self._terminal.write("Please enter mock or real.", style="warning")

    def _read_workspace(self, current: str | None) -> str:
        while True:
            value = self._terminal.read(
                f"Workspace [{current}]: " if current else "Workspace: "
            ).strip()
            if not value and current is not None and self._workspace_valid(current):
                return str(Path(current).resolve())
            try:
                return self._normalize_workspace(value)
            except ValueError:
                self._terminal.write(
                    "Workspace must be an accessible directory.",
                    style="warning",
                )

    def _read_url(self, current: str | None) -> str:
        while True:
            value = self._terminal.read(
                f"Base URL [{current}]: " if current else "Base URL: "
            ).strip()
            if not value and current is not None:
                return current
            try:
                return normalize_base_url(value)
            except ValueError:
                self._terminal.write(
                    "Base URL must be a valid HTTPS URL.",
                    style="warning",
                )

    def _read_model(self, current: str | None) -> str:
        while True:
            value = self._terminal.read(
                f"Model [{current}]: " if current else "Model: "
            )
            if not value.strip() and current is not None:
                return current
            try:
                return _config_text("model", value)
            except ValueError:
                self._terminal.write("Model must be non-empty.", style="warning")

    def _workspace_valid(self, value: str | None) -> bool:
        if value is None:
            return False
        try:
            path = Path(value).expanduser().resolve(strict=True)
            if not path.is_dir():
                return False
            with os.scandir(path):
                return True
        except OSError:
            return False

    def _normalize_workspace(self, value: str) -> str:
        _config_text("workspace", value)
        try:
            path = Path(value).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError("invalid_workspace")
            with os.scandir(path):
                pass
        except OSError as exc:
            raise ValueError("invalid_workspace") from exc
        return str(path)

    def _credential_configured(self) -> bool:
        return bool(self._credential_store.get(SUPPORTED_PROVIDER))

    def _real_complete(self, config: UserShellConfig) -> bool:
        if config.llm is None or not self._workspace_valid(config.workspace):
            return False
        try:
            normalize_base_url(config.llm.base_url)
            _config_text("model", config.llm.model)
        except ValueError:
            return False
        return self._credential_configured()

    def _store_secret(self, secret: str) -> str | None:
        previous = self._credential_store.get(SUPPORTED_PROVIDER)
        try:
            set_credential(
                SUPPORTED_PROVIDER,
                secret,
                store=self._credential_store,
            )
        except ValueError:
            try:
                self._restore_secret(previous)
            except ValueError:
                pass
            raise
        return previous

    def _restore_secret(self, previous: str | None) -> None:
        if previous is None:
            self._credential_store.clear(SUPPORTED_PROVIDER)
        else:
            self._credential_store.set(SUPPORTED_PROVIDER, previous)

    def _persist_with_secret(
        self,
        candidate: UserShellConfig,
        secret: str,
    ) -> None:
        previous = self._store_secret(secret)
        try:
            self._persist(candidate)
        except UserConfigError:
            self._restore_secret(previous)
            raise

    def _persist(self, candidate: UserShellConfig) -> None:
        save_user_shell_config(candidate, path=self._path)
        self.config = candidate
        self._had_config = True
        self._mode_valid = True
        self._draft_base_url = (
            None if candidate.llm is None else candidate.llm.base_url
        )
        self._draft_model = None if candidate.llm is None else candidate.llm.model

    def _save_result(
        self,
        candidate: UserShellConfig,
        *,
        request_connection_test: bool = False,
    ) -> ConfigCommandResult:
        try:
            self._persist(candidate)
        except UserConfigError:
            return self._failed("Settings could not be saved.")
        return ConfigCommandResult(
            True,
            candidate,
            request_connection_test=request_connection_test,
        )

    def _failed(self, message: str) -> ConfigCommandResult:
        self._terminal.write(message, style="error")
        return ConfigCommandResult(False, self.config)

    def _print_help(self) -> None:
        self._terminal.write(
            "NAME\n"
            "  SpecGate interactive Agent Shell\n\n"
            "SYNOPSIS\n"
            "  /command [argument]\n"
            "  <natural-language request>\n\n"
            "COMMANDS\n"
            "  /help                 Show this command reference.\n"
            "  /status               Show mode, model, URL, credential state, "
            "workspace, verbosity, and last run.\n"
            "  /setup                Re-run the complete configuration wizard.\n"
            "  /mode [mock|real]      Show or switch the LLM mode.\n"
            "  /workspace [<path>]    Show or select an existing workspace directory.\n"
            "  /model [<name>]        Show or change the Real LLM model.\n"
            "  /url [<https-url>]     Show or change the Real LLM Base URL.\n"
            "  /api-key               Securely replace the Real LLM keyring credential.\n"
            "  /verbose [on|off]      Show or change detailed progress output.\n"
            "  /approvals             List and decide unresolved approvals.\n"
            "  /clear                 Clear the terminal display only.\n"
            "  /exit                  Exit the Shell.\n\n"
            "INPUT\n"
            "  Any other non-empty text starts one Agent run in Real mode or offers "
            "the fixed Demo in Mock mode.\n"
            "  exit | quit | q         Exit aliases; matching is case-insensitive."
        )
