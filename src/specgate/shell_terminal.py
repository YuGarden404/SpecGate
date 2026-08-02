from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Protocol

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import DummyHistory, FileHistory
from prompt_toolkit.shortcuts import clear

from specgate.user_config import user_config_path


_ANSI_STYLES = {
    "prompt": "\x1b[34m",
    "agent": "\x1b[36m",
    "context": "\x1b[36m",
    "tool": "\x1b[35m",
    "governance": "\x1b[33m",
    "gate": "\x1b[36m",
    "approval": "\x1b[33m",
    "success": "\x1b[32m",
    "warning": "\x1b[33m",
    "error": "\x1b[31m",
    "muted": "\x1b[90m",
}
_ANSI_RESET = "\x1b[0m"
SHELL_PROMPT = "SpecGate >> "
_SAFE_NO_ARGUMENT_COMMANDS = frozenset(
    {"help", "status", "setup", "api-key", "approvals", "clear", "exit"}
)


def _safe_history_command(value: str) -> bool:
    stripped = value.strip()
    if not stripped.startswith("/"):
        return False
    head, separator, tail = stripped[1:].partition(" ")
    command = head.lower()
    argument = tail.strip() if separator else ""
    if command in _SAFE_NO_ARGUMENT_COMMANDS:
        return not argument
    if command == "mode":
        return not argument or argument.lower() in {"mock", "real"}
    if command == "verbose":
        return not argument or argument.lower() in {"on", "off"}
    return False


class SafeFileHistory(FileHistory):
    """Persist only non-sensitive local Shell commands."""

    def store_string(self, string: str) -> None:
        if _safe_history_command(string):
            super().store_string(string)


def shell_history_path() -> Path:
    return user_config_path().with_name("shell_history")


class ShellTerminal(Protocol):
    def read(self, prompt: str, *, secret: bool = False) -> str: ...

    def write(self, text: str, *, style: str | None = None) -> None: ...

    def clear(self) -> None: ...


def color_enabled(*, is_tty: bool, environ: Mapping[str, str]) -> bool:
    return is_tty and "NO_COLOR" not in environ


def _ansi(text: str, style: str | None) -> str:
    prefix = _ANSI_STYLES.get(style or "")
    if prefix is None:
        return text
    return f"{prefix}{text}{_ANSI_RESET}"


class PromptToolkitTerminal:
    def __init__(
        self,
        *,
        session=None,
        secret_session=None,
        output=None,
        is_tty=None,
        environ=None,
        history_path=None,
    ):
        values = os.environ if environ is None else environ
        if session is None:
            persistent_path = (
                shell_history_path() if history_path is None else Path(history_path)
            )
            persistent_path.parent.mkdir(parents=True, exist_ok=True)
            session = PromptSession(history=SafeFileHistory(persistent_path))
        self._session = session
        self._secret_session = (
            PromptSession(history=DummyHistory())
            if secret_session is None
            else secret_session
        )
        self._output = output
        detected_tty = sys.stdout.isatty() if is_tty is None else is_tty
        self._color = color_enabled(is_tty=detected_tty, environ=values)
        self._lock = Lock()

    def read(self, prompt: str, *, secret: bool = False) -> str:
        session = self._secret_session if secret else self._session
        rendered_prompt = prompt
        if not secret and self._color and prompt == SHELL_PROMPT:
            rendered_prompt = ANSI(_ansi(prompt, "prompt"))
        return session.prompt(rendered_prompt, is_password=secret)

    def write(self, text: str, *, style: str | None = None) -> None:
        rendered = _ansi(text, style) if self._color else text
        with self._lock:
            print_formatted_text(ANSI(rendered), output=self._output)

    def clear(self) -> None:
        clear()
