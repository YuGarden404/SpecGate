from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from tests.shell_support import ScriptedTerminal
from specgate.cli import _mock_demo_llm
from specgate.interactive_shell import InteractiveShell
from specgate.shell_config import ShellConfigController
from specgate.shell_runtime import SpecGateShellRuntime


SECRET = "sk-e2e-secret-1234567890"


class MemoryCredentialStore:
    def __init__(self, secret: str | None = None) -> None:
        self.secret = secret

    def get(self, provider: str) -> str | None:
        del provider
        return self.secret

    def set(self, provider: str, secret: str) -> None:
        del provider
        self.secret = secret

    def clear(self, provider: str) -> None:
        del provider
        self.secret = None


@contextmanager
def temporary_demo_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "workspace"
        root.mkdir()
        root.joinpath("TASK_SPEC.md").write_text(
            "# Task\n\nGenerate a searchable knowledge navigation page.\n",
            encoding="utf-8",
        )
        root.joinpath("CHECKLIST.md").write_text("", encoding="utf-8")
        yield root


def build_test_shell(
    terminal: ScriptedTerminal,
    root: Path,
    *,
    credential: str,
) -> tuple[InteractiveShell, Path]:
    config_path = root.parent / "config-home" / "config.json"
    controller = ShellConfigController(
        terminal,
        path=config_path,
        credential_store=MemoryCredentialStore(credential),
    )
    runtime = SpecGateShellRuntime(
        lambda: controller.config,
        mock_llm_factory=_mock_demo_llm,
        id_factory=lambda: "shell-e2e-run",
    )
    return InteractiveShell(terminal, controller, runtime), config_path


class ShellEndToEndTests(unittest.TestCase):
    def test_mock_shell_generates_html_reports_progress_and_leaks_no_secret(self):
        with temporary_demo_workspace() as root:
            terminal = ScriptedTerminal(
                [
                    "mock",
                    str(root),
                    "Please generate HTML from the spec and checklist.",
                    "yes",
                    "q",
                ]
            )
            shell, config_path = build_test_shell(
                terminal,
                root,
                credential=SECRET,
            )

            code = shell.run()

            output = terminal.output
            self.assertEqual(code, 0)
            self.assertTrue(root.joinpath("index.html").is_file())
            for marker in (
                "[Context]",
                "[Tool]",
                "[Governance]",
                "[Gate]",
                "[Done]",
            ):
                with self.subTest(marker=marker):
                    self.assertIn(marker, output)
            self.assertNotIn(SECRET, output)
            self.assertEqual(
                len(list(root.joinpath("runs").glob("*/trace.jsonl"))),
                2,
            )
            self.assertTrue(
                root.joinpath("reports", "shell-e2e-run", "index.html").is_file()
            )

            persisted_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (config_path, *root.rglob("*.json"), *root.rglob("*.jsonl"))
            )
            self.assertNotIn(SECRET, persisted_text)


if __name__ == "__main__":
    unittest.main()
