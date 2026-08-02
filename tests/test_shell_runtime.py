import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shell_support import NeverCancelled, RecordingSink
from specgate.llm import LLMProviderError, MockLLM
from specgate.shell_runtime import SpecGateShellRuntime
from specgate.user_config import UserLLMConfig, UserShellConfig


VALID_HTML = (
    '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
    '<title>Task</title></head><body><input type="search">Task Search Detail'
    '</body></html>'
)


def _workspace(root: Path, *, governance: str | None = None) -> None:
    root.joinpath("TASK_SPEC.md").write_text("# Task", encoding="utf-8")
    root.joinpath("CHECKLIST.md").write_text("", encoding="utf-8")
    root.joinpath("index.html").write_text(VALID_HTML, encoding="utf-8")
    if governance is not None:
        root.joinpath("specgate.toml").write_text(governance, encoding="utf-8")


def _mock_config(root: Path) -> UserShellConfig:
    return UserShellConfig("mock", str(root), False, None)


def _real_config(root: Path) -> UserShellConfig:
    return UserShellConfig(
        "real",
        str(root),
        False,
        UserLLMConfig(
            "openai-compatible",
            "https://api.example.com/v1",
            "model-1",
        ),
    )


class RecordingFinishLLM:
    def __init__(self) -> None:
        self.contexts = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'


class RecordingConnectionLLM:
    def __init__(self, *, error: LLMProviderError | None = None) -> None:
        self.calls = 0
        self.error = error

    def complete(self, context: str) -> str:
        self.calls += 1
        self.context = context
        if self.error is not None:
            raise self.error
        return '{"schema_version":"1","action":"finish","args":{"summary":"ok"}}'


class ShellRuntimeTests(unittest.TestCase):
    def test_runtime_creates_independent_evidence_for_each_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root)
            llms = []
            identifiers = iter(("shell-run-1", "shell-run-2"))

            def make_llm():
                llm = RecordingFinishLLM()
                llms.append(llm)
                return llm

            runtime = SpecGateShellRuntime(
                lambda: _mock_config(root),
                mock_llm_factory=make_llm,
                id_factory=lambda: next(identifiers),
            )

            first = runtime.start(
                "Generate the page",
                RecordingSink(),
                NeverCancelled(),
            )
            second = runtime.start(
                "Modify the page",
                RecordingSink(),
                NeverCancelled(),
            )

            self.assertNotEqual(first.run_id, second.run_id)
            for outcome in (first, second):
                self.assertEqual(outcome.status, "completed")
                self.assertTrue(outcome.trace_path.is_file())
                self.assertTrue(outcome.report_path.is_file())
                self.assertTrue(outcome.trace_path.is_absolute())
                self.assertTrue(outcome.report_path.is_absolute())
                self.assertTrue(outcome.html_path.is_absolute())
            self.assertIn("## User Request\nGenerate the page", llms[0].contexts[0])
            self.assertIn("## User Request\nModify the page", llms[1].contexts[0])
            self.assertNotIn("Generate the page", llms[1].contexts[0])

    def test_archived_report_link_still_targets_workspace_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root)
            runtime = SpecGateShellRuntime(
                lambda: _mock_config(root),
                mock_llm_factory=RecordingFinishLLM,
                id_factory=lambda: "shell-run-report",
            )

            outcome = runtime.start("Finish the page", RecordingSink(), NeverCancelled())

            report = outcome.report_path.read_text(encoding="utf-8")
            self.assertIn('href="../../index.html"', report)
            self.assertEqual(
                outcome.report_path.parent.joinpath("../../index.html").resolve(),
                outcome.html_path,
            )

    def test_connection_test_calls_model_without_creating_agent_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root)
            llm = RecordingConnectionLLM()
            factory_calls = []

            def factory(**kwargs):
                factory_calls.append(kwargs)
                return llm

            runtime = SpecGateShellRuntime(
                lambda: _real_config(root),
                llm_factory=factory,
                credential_reader=lambda provider: "secret",
            )

            result = runtime.test_connection()

            self.assertTrue(result.ok)
            self.assertEqual(result.code, "ok")
            self.assertEqual(llm.calls, 1)
            self.assertEqual(factory_calls[0]["model"], "model-1")
            self.assertFalse(root.joinpath("runs").exists())
            self.assertFalse(root.joinpath("reports").exists())
            self.assertFalse(root.joinpath("MEMORY.md").exists())

    def test_default_shell_credential_reader_ignores_environment_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root)
            factory_calls = []

            def factory(**kwargs):
                factory_calls.append(kwargs)
                return RecordingConnectionLLM()

            with (
                patch.dict(
                    os.environ,
                    {"OPENAI_COMPATIBLE_API_KEY": "environment-secret"},
                    clear=True,
                ),
                patch(
                    "specgate.credential_store.keyring.get_password",
                    return_value="keyring-secret",
                ),
            ):
                runtime = SpecGateShellRuntime(
                    lambda: _real_config(root),
                    llm_factory=factory,
                )
                result = runtime.test_connection()

            self.assertTrue(result.ok)
            self.assertEqual(factory_calls[0]["api_key"], "keyring-secret")

    def test_connection_test_returns_only_stable_provider_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root)
            llm = RecordingConnectionLLM(
                error=LLMProviderError(
                    "llm_authentication_failed",
                    "provider leaked sk-connection-secret-1234567890",
                )
            )
            runtime = SpecGateShellRuntime(
                lambda: _real_config(root),
                llm_factory=lambda **kwargs: llm,
                credential_reader=lambda provider: "secret",
            )

            result = runtime.test_connection()

            self.assertFalse(result.ok)
            self.assertEqual(result.code, "llm_authentication_failed")
            self.assertNotIn("secret", repr(result))

    def test_decide_resumes_existing_pending_run(self):
        governance = """[policy]
allowed_actions = ["write_file", "finish"]
allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]
allowed_write_paths = ["index.html"]

[governance]
profile = "review"
review_actions = ["write_file"]
review_paths = ["index.html"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root, governance=governance)
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": "index.html", "content": VALID_HTML},
                    },
                    {
                        "schema_version": "1",
                        "action": "finish",
                        "args": {"summary": "done"},
                    },
                ]
            )
            runtime = SpecGateShellRuntime(
                lambda: _mock_config(root),
                mock_llm_factory=lambda: llm,
                id_factory=lambda: "shell-run-approval",
            )
            pending = runtime.start(
                "Write index.html",
                RecordingSink(),
                NeverCancelled(),
            )

            self.assertEqual(pending.status, "pending_approval")
            self.assertIsNotNone(pending.pending_approval_id)
            self.assertFalse(root.joinpath("runs", pending.run_id).exists())

            completed = runtime.decide(
                pending,
                decision="approved",
                reason=None,
            )

            self.assertEqual(completed.run_id, pending.run_id)
            self.assertEqual(completed.status, "completed")
            self.assertTrue(completed.trace_path.is_file())
            self.assertTrue(completed.report_path.is_file())

    def test_new_request_is_rejected_while_approval_is_unresolved(self):
        governance = """[policy]
allowed_actions = ["write_file", "finish"]
allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]
allowed_write_paths = ["index.html"]

[governance]
profile = "review"
review_actions = ["write_file"]
review_paths = ["index.html"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _workspace(root, governance=governance)
            runtime = SpecGateShellRuntime(
                lambda: _mock_config(root),
                mock_llm_factory=lambda: MockLLM(
                    [
                        {
                            "schema_version": "1",
                            "action": "write_file",
                            "args": {"path": "index.html", "content": VALID_HTML},
                        }
                    ]
                ),
                id_factory=lambda: "shell-run-pending",
            )
            runtime.start("First", RecordingSink(), NeverCancelled())

            with self.assertRaisesRegex(RuntimeError, "approval_pending"):
                runtime.start("Second", RecordingSink(), NeverCancelled())

    def test_start_validates_required_workspace_files_before_creating_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("TASK_SPEC.md").write_text("# Task", encoding="utf-8")
            runtime = SpecGateShellRuntime(
                lambda: _mock_config(root),
                mock_llm_factory=RecordingFinishLLM,
            )

            with self.assertRaisesRegex(ValueError, "workspace_missing_checklist"):
                runtime.start("Run", RecordingSink(), NeverCancelled())

            self.assertFalse(root.joinpath("runs").exists())


if __name__ == "__main__":
    unittest.main()
