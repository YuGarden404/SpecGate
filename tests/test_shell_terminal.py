import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from specgate.shell_terminal import PromptToolkitTerminal, SafeFileHistory, color_enabled


class FakeSession:
    def __init__(self):
        self.calls = []

    def prompt(self, message, *, is_password=False):
        self.calls.append((message, is_password))
        return "secret-value" if is_password else "answer"


class ShellTerminalTests(unittest.TestCase):
    def test_file_history_persists_only_safe_slash_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shell-history"
            history = SafeFileHistory(path)
            entries = (
                "/help",
                "/status",
                "/mode mock",
                "/verbose on",
                "/approvals",
                "/api-key",
                "请根据 spec 生成 html",
                "/workspace D:/private/project",
                "/url https://api.example.com/v1",
                "/model private-model",
                "/api-key secret-on-command-line",
                "sk-secret-prompt-value",
            )
            for entry in entries:
                history.append_string(entry)

            restored = list(SafeFileHistory(path).load_history_strings())
            raw = path.read_text(encoding="utf-8")

            self.assertEqual(
                restored,
                [
                    "/api-key",
                    "/approvals",
                    "/verbose on",
                    "/mode mock",
                    "/status",
                    "/help",
                ],
            )
            for sensitive in (
                "请根据 spec 生成 html",
                "D:/private/project",
                "api.example.com",
                "private-model",
                "secret-on-command-line",
                "sk-secret-prompt-value",
            ):
                self.assertNotIn(sensitive, raw)

    def test_color_requires_tty_and_honors_no_color(self):
        self.assertTrue(color_enabled(is_tty=True, environ={}))
        self.assertFalse(color_enabled(is_tty=False, environ={}))
        self.assertFalse(color_enabled(is_tty=True, environ={"NO_COLOR": "1"}))

    def test_regular_prompt_uses_history_session(self):
        session = FakeSession()
        secret_session = FakeSession()
        terminal = PromptToolkitTerminal(
            session=session,
            secret_session=secret_session,
            is_tty=True,
            environ={},
        )

        self.assertEqual(terminal.read("Workspace: "), "answer")

        self.assertEqual(session.calls, [("Workspace: ", False)])
        self.assertEqual(secret_session.calls, [])

    def test_shell_prompt_is_blue_only_when_color_is_enabled(self):
        color_session = FakeSession()
        plain_session = FakeSession()

        PromptToolkitTerminal(
            session=color_session,
            secret_session=FakeSession(),
            is_tty=True,
            environ={},
        ).read("SpecGate >> ")
        PromptToolkitTerminal(
            session=plain_session,
            secret_session=FakeSession(),
            is_tty=False,
            environ={},
        ).read("SpecGate >> ")

        self.assertEqual(
            color_session.calls[0][0].value,
            "\x1b[34mSpecGate >> \x1b[0m",
        )
        self.assertEqual(plain_session.calls[0][0], "SpecGate >> ")

    def test_secret_prompt_uses_password_mode_and_not_history(self):
        session = FakeSession()
        secret_session = FakeSession()
        terminal = PromptToolkitTerminal(
            session=session,
            secret_session=secret_session,
            is_tty=True,
            environ={},
        )

        self.assertEqual(terminal.read("API key: ", secret=True), "secret-value")

        self.assertEqual(session.calls, [])
        self.assertEqual(secret_session.calls, [("API key: ", True)])

    def test_write_uses_approved_ansi_style_only_when_color_is_enabled(self):
        output = io.StringIO()
        with patch("specgate.shell_terminal.print_formatted_text") as printer:
            terminal = PromptToolkitTerminal(
                session=FakeSession(),
                secret_session=FakeSession(),
                output=output,
                is_tty=True,
                environ={},
            )

            terminal.write("SpecGate >>", style="prompt")

        rendered = printer.call_args.args[0]
        self.assertEqual(rendered.value, "\x1b[34mSpecGate >>\x1b[0m")
        self.assertIs(printer.call_args.kwargs["output"], output)

    def test_write_falls_back_to_plain_text_when_color_is_disabled(self):
        with patch("specgate.shell_terminal.print_formatted_text") as printer:
            terminal = PromptToolkitTerminal(
                session=FakeSession(),
                secret_session=FakeSession(),
                is_tty=False,
                environ={},
            )

            terminal.write("SpecGate >>", style="prompt")

        self.assertEqual(printer.call_args.args[0].value, "SpecGate >>")

    def test_unknown_style_falls_back_to_plain_text(self):
        with patch("specgate.shell_terminal.print_formatted_text") as printer:
            terminal = PromptToolkitTerminal(
                session=FakeSession(),
                secret_session=FakeSession(),
                is_tty=True,
                environ={},
            )

            terminal.write("message", style="not-approved")

        self.assertEqual(printer.call_args.args[0].value, "message")


if __name__ == "__main__":
    unittest.main()
