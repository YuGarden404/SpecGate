import tempfile
import time
import unittest
from pathlib import Path

from tests.shell_support import ScriptedTerminal
from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path
from specgate.interactive_shell import (
    MOCK_DEMO_REQUEST,
    EventCancellationToken,
    InteractiveShell,
    ShellInput,
    parse_input,
)
from specgate.run_control import RunCancelled
from specgate.shell_config import ConfigCommandResult
from specgate.shell_runtime import (
    ConnectionTestResult,
    ShellRunOutcome,
    SpecGateShellRuntime,
)
from specgate.user_config import UserShellConfig


def outcome(root: Path, status: str = "completed", *, approval_id=None):
    return ShellRunOutcome(
        run_id=f"run-{status}",
        status=status,
        passed=status == "completed",
        pending_approval_id=approval_id,
        html_path=(root / "index.html").resolve(),
        report_path=(root / "reports" / "latest" / "index.html").resolve(),
        trace_path=(root / "runs" / "latest" / "trace.jsonl").resolve(),
    )


class FakeConfigController:
    def __init__(
        self,
        terminal,
        config,
        *,
        ready_config=None,
        command_results=None,
        ready_error=None,
    ):
        self.terminal = terminal
        self.config = config
        self.ready_config = ready_config or config
        self.command_results = dict(command_results or {})
        self.ready_error = ready_error
        self.commands = []

    def ensure_ready(self):
        if self.ready_error is not None:
            raise self.ready_error
        self.config = self.ready_config
        return self.config

    def execute(self, name, argument):
        self.commands.append((name, argument))
        result = self.command_results.get(name)
        if result is not None:
            self.config = result.config
            return result
        if name == "status":
            self.terminal.write(f"Mode: {self.config.mode}")
        return ConfigCommandResult(True, self.config)


class PendingApprovalSummary:
    def __init__(self, approval_id, *, action="write_file", path="index.html"):
        self.id = approval_id
        self.action = action
        self.path = path
        self.risk_level = "review"
        self.reason = "write requires review"


class RecordingRuntime:
    def __init__(self, root, outcomes=()):
        self.workspace = root
        self.outcomes = list(outcomes)
        self.requests = []
        self.decisions = []
        self.connection_tests = 0
        self.pending = []
        self.external_decisions = []
        self.close_calls = 0

    def start(self, request, event_sink, cancel_token):
        del event_sink, cancel_token
        self.requests.append(request)
        return self.outcomes.pop(0)

    def decide(self, pending, *, decision, reason):
        self.decisions.append((pending.pending_approval_id, decision, reason))
        return self.outcomes.pop(0)

    def test_connection(self, cancel_token):
        del cancel_token
        self.connection_tests += 1
        return ConnectionTestResult(True, "ok")

    def pending_approvals(self):
        return tuple(self.pending)

    def decide_external(self, approval_id, *, decision, reason):
        self.external_decisions.append((approval_id, decision, reason))

    def close(self):
        self.close_calls += 1


class BlockingRuntime(RecordingRuntime):
    def __init__(self, root):
        super().__init__(root)
        self.cancel_seen = False

    def start(self, request, event_sink, cancel_token):
        del event_sink
        self.requests.append(request)
        if request != "long request":
            return outcome(self.workspace)
        while True:
            try:
                cancel_token.check()
            except RunCancelled:
                self.cancel_seen = True
                return outcome(self.workspace, "cancelled")
            time.sleep(0.001)


class PersistentApprovalRuntime:
    def __init__(self, root):
        self.workspace = root
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class InterruptOnceShell(InteractiveShell):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._interrupted = False

    def _wait_once(self, future):
        if not self._interrupted:
            self._interrupted = True
            raise KeyboardInterrupt
        return super()._wait_once(future)


def make_shell(terminal, runtime, *, mode="real", controller=None, shell_type=InteractiveShell):
    config = UserShellConfig(mode, str(runtime.workspace), False, None)
    config_controller = controller or FakeConfigController(terminal, config)
    return shell_type(terminal, config_controller, runtime)


class InteractiveShellTests(unittest.TestCase):
    def test_parse_input_preserves_argument_case_and_recognizes_exit_variants(self):
        self.assertEqual(
            parse_input("/MODEL DeepSeek-V4-Pro"),
            ShellInput("command", "model", "DeepSeek-V4-Pro"),
        )
        self.assertEqual(parse_input("   "), ShellInput("empty"))
        self.assertEqual(parse_input("request"), ShellInput("request", argument="request"))
        for value in ("exit", "ExiT", "q", "Q", "quit", "/EXIT"):
            with self.subTest(value=value):
                self.assertEqual(parse_input(value).kind, "exit")

    def test_event_cancellation_token_raises_only_after_cancel(self):
        token = EventCancellationToken()

        token.check()
        token.cancel()

        with self.assertRaises(RunCancelled):
            token.check()
        self.assertEqual(token.remaining_seconds(), float("inf"))

    def test_each_natural_language_input_starts_one_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["first request", "second request", "q"])
            runtime = RecordingRuntime(root, [outcome(root), outcome(root)])

            code = make_shell(terminal, runtime).run()

            self.assertEqual(code, 0)
            self.assertEqual(runtime.requests, ["first request", "second request"])
            self.assertEqual(runtime.close_calls, 1)

    def test_command_input_never_starts_run_and_preserves_argument_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["/MODEL DeepSeek-V4-Pro", "q"])
            runtime = RecordingRuntime(root)
            controller = FakeConfigController(
                terminal,
                UserShellConfig("real", str(root), False, None),
            )

            make_shell(terminal, runtime, controller=controller).run()

            self.assertEqual(runtime.requests, [])
            self.assertEqual(controller.commands, [("model", "DeepSeek-V4-Pro")])

    def test_mock_request_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["custom request", "n", "q"])
            runtime = RecordingRuntime(root)

            make_shell(terminal, runtime, mode="mock").run()

            self.assertEqual(runtime.requests, [])
            self.assertIn("只能展示内置 Demo", terminal.output)
            self.assertEqual(terminal.read_calls[1].prompt, "是否运行 Mock Demo？[Y/n] ")

    def test_mock_confirmation_runs_fixed_demo_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["custom request", "yes", "q"])
            runtime = RecordingRuntime(root, [outcome(root)])

            make_shell(terminal, runtime, mode="mock").run()

            self.assertEqual(runtime.requests, [MOCK_DEMO_REQUEST])
            self.assertNotIn("custom request", runtime.requests)

    def test_inline_approval_decides_and_resumes_same_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["write page", "yes", "q"])
            runtime = RecordingRuntime(
                root,
                [
                    outcome(root, "pending_approval", approval_id="approval-1"),
                    outcome(root),
                ],
            )

            make_shell(terminal, runtime).run()

            self.assertEqual(
                runtime.decisions,
                [("approval-1", "approved", None)],
            )
            self.assertIn(f"[Done] {root.joinpath('index.html').resolve()}", terminal.output)

    def test_keyboard_interrupt_cancels_active_run_but_keeps_shell_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["long request", "after cancel", "q"])
            runtime = BlockingRuntime(root)

            make_shell(
                terminal,
                runtime,
                shell_type=InterruptOnceShell,
            ).run()

            self.assertTrue(runtime.cancel_seen)
            self.assertEqual(runtime.requests, ["long request", "after cancel"])
            self.assertIn("[Cancelled]", terminal.output)

    def test_connection_test_runs_only_after_explicit_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = UserShellConfig("mock", str(root), False, None)
            ready = UserShellConfig("real", str(root), False, None)
            terminal = ScriptedTerminal(["yes", "q"])
            runtime = RecordingRuntime(root)
            controller = FakeConfigController(
                terminal,
                initial,
                ready_config=ready,
            )

            make_shell(terminal, runtime, controller=controller).run()

            self.assertEqual(runtime.connection_tests, 1)
            self.assertIn("可能产生少量 API 费用", terminal.output)

    def test_connection_test_is_skipped_without_explicit_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["no", "q"])
            runtime = RecordingRuntime(root)
            config = UserShellConfig("real", str(root), False, None)
            controller = FakeConfigController(
                terminal,
                UserShellConfig("mock", str(root), False, None),
                ready_config=config,
            )

            make_shell(terminal, runtime, controller=controller).run()

            self.assertEqual(runtime.connection_tests, 0)

    def test_approvals_command_lists_and_decides_selected_pending_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["/approvals", "approval-2", "no", "q"])
            runtime = RecordingRuntime(root)
            runtime.pending = [
                PendingApprovalSummary("approval-1"),
                PendingApprovalSummary("approval-2"),
            ]

            make_shell(terminal, runtime).run()

            self.assertEqual(
                runtime.external_decisions,
                [("approval-2", "denied", "human denied")],
            )
            self.assertIn("approval-1", terminal.output)
            self.assertIn("approval-2", terminal.output)

    def test_empty_approvals_explains_pending_only_scope_and_evidence_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["/approvals", "q"])
            runtime = RecordingRuntime(root)

            make_shell(terminal, runtime).run()

            self.assertIn("only lists unresolved approvals", terminal.output)
            self.assertIn(
                str((root / "reports" / "latest" / "index.html").resolve()),
                terminal.output,
            )
            self.assertIn(
                str((root / "runs" / "latest" / "trace.jsonl").resolve()),
                terminal.output,
            )

    def test_approvals_command_updates_real_persisted_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = PendingApproval(
                id="approval-step-1",
                step=1,
                action="write_file",
                path="index.html",
                risk_level="review",
                reason="write requires review",
                profile="review",
            )
            queue_path = approval_queue_path(root)
            ApprovalQueue([pending]).write(queue_path)
            terminal = ScriptedTerminal(
                ["/approvals", "approval-step-1", "yes", "q"]
            )
            runtime = PersistentApprovalRuntime(root)

            make_shell(terminal, runtime).run()

            saved = ApprovalQueue.read(queue_path).find("approval-step-1")
            self.assertEqual(saved.status, "approved")
            self.assertEqual(runtime.close_calls, 1)

    def test_shell_drives_real_runtime_and_archives_evidence(self):
        class FinishLLM:
            def complete(self, context):
                del context
                return (
                    '{"schema_version":"1","action":"finish",'
                    '"args":{"summary":"done"}}'
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("TASK_SPEC.md").write_text("# Task", encoding="utf-8")
            root.joinpath("CHECKLIST.md").write_text("", encoding="utf-8")
            root.joinpath("index.html").write_text(
                '<!doctype html><html><head>'
                '<meta name="viewport" content="width=device-width">'
                '<title>Task</title></head>'
                '<body><input type="search">Task Search Detail</body></html>',
                encoding="utf-8",
            )
            terminal = ScriptedTerminal(["custom request", "yes", "q"])
            runtime = SpecGateShellRuntime(
                UserShellConfig("mock", str(root), False, None),
                mock_llm_factory=FinishLLM,
                id_factory=lambda: "interactive-run-1",
            )

            code = make_shell(terminal, runtime, mode="mock").run()

            self.assertEqual(code, 0)
            self.assertTrue(root.joinpath("runs", "interactive-run-1", "trace.jsonl").is_file())
            self.assertTrue(
                root.joinpath("reports", "interactive-run-1", "index.html").is_file()
            )
            self.assertIn("[Done]", terminal.output)

    def test_status_adds_last_run_without_starting_another_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["request", "/status", "q"])
            runtime = RecordingRuntime(root, [outcome(root)])

            make_shell(terminal, runtime).run()

            self.assertEqual(runtime.requests, ["request"])
            self.assertIn("Last run: completed", terminal.output)

    def test_idle_keyboard_interrupt_and_eof_exit_cleanly(self):
        for signal in (KeyboardInterrupt(), EOFError()):
            with self.subTest(signal=type(signal).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                terminal = ScriptedTerminal([signal])
                runtime = RecordingRuntime(root)

                code = make_shell(terminal, runtime).run()

                self.assertEqual(code, 0)
                self.assertEqual(runtime.close_calls, 1)

    def test_setup_keyboard_interrupt_and_eof_exit_cleanly(self):
        for signal in (KeyboardInterrupt(), EOFError()):
            with self.subTest(signal=type(signal).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                terminal = ScriptedTerminal([])
                runtime = RecordingRuntime(root)
                config = UserShellConfig("mock", str(root), False, None)
                controller = FakeConfigController(
                    terminal,
                    config,
                    ready_error=signal,
                )

                code = make_shell(terminal, runtime, controller=controller).run()

                self.assertEqual(code, 0)
                self.assertEqual(runtime.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
