from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from threading import Lock
from typing import Protocol

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import DummyHistory, InMemoryHistory
from prompt_toolkit.shortcuts import clear


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
    ):
        values = os.environ if environ is None else environ
        self._session = (
            PromptSession(history=InMemoryHistory()) if session is None else session
        )
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
