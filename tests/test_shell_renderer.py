import unittest

from tests.shell_support import ScriptedTerminal
from specgate.runtime_events import RunEventContext
from specgate.shell_renderer import ShellEventRenderer, render_event_line


class ShellEventRendererTests(unittest.TestCase):
    def setUp(self):
        self.context = RunEventContext("run-1", "agent-1")

    def test_renderer_maps_core_events_without_raw_payloads(self):
        terminal = ScriptedTerminal([])
        renderer = ShellEventRenderer(terminal, verbose=False)

        renderer.emit(
            self.context,
            "ContextBuilt",
            {"selected_files": ["TASK_SPEC.md", "CHECKLIST.md"]},
        )
        renderer.emit(
            self.context,
            "GovernanceEvaluated",
            {
                "action": "write_file",
                "path": "index.html",
                "decision": "allow",
                "content": "must not render",
            },
        )
        renderer.emit(
            self.context,
            "GateCompleted",
            {"passed": True, "summary": "all checks passed"},
        )

        output = terminal.output
        self.assertIn("[Context]", output)
        self.assertIn("TASK_SPEC.md", output)
        self.assertIn("CHECKLIST.md", output)
        self.assertIn("[Governance] Allowed write_file: index.html", output)
        self.assertIn("[Gate] Passed", output)
        self.assertNotIn("must not render", output)
        self.assertNotIn("run=", output)

    def test_renderer_redacts_secrets_and_verbose_never_prints_raw_content(self):
        terminal = ScriptedTerminal([])
        renderer = ShellEventRenderer(terminal, verbose=True)

        renderer.emit(
            self.context,
            "ToolCompleted",
            {
                "action": "write_file",
                "path": "index.html",
                "code": "ok",
                "content": "sk-secret-1234567890",
                "headers": {"Authorization": "Bearer private"},
                "message": "raw model text",
                "data": {"body": "raw tool data"},
            },
            step=2,
            phase="tool",
        )

        output = terminal.output
        self.assertIn("[Tool]", output)
        self.assertIn("run=run-1 step=2 phase=tool", output)
        for forbidden in (
            "sk-secret",
            "content",
            "Authorization",
            "private",
            "raw model text",
            "raw tool data",
            "headers",
            "data",
        ):
            self.assertNotIn(forbidden, output)

    def test_renderer_redacts_secret_like_text_in_allowed_summary_field(self):
        terminal = ScriptedTerminal([])

        ShellEventRenderer(terminal, verbose=False).emit(
            self.context,
            "GateCompleted",
            {
                "passed": False,
                "summary": "provider sk-summary-secret-1234567890 failed",
            },
        )

        self.assertIn("[REDACTED]", terminal.output)
        self.assertNotIn("sk-summary-secret", terminal.output)

    def test_renderer_maps_approval_and_terminal_run_states(self):
        terminal = ScriptedTerminal([])
        renderer = ShellEventRenderer(terminal, verbose=False)

        renderer.emit(
            self.context,
            "ApprovalRequested",
            {
                "approval_id": "approval-1",
                "action": "write_file",
                "path": "index.html",
                "risk_level": "review",
                "reason": "workspace write",
            },
        )
        renderer.emit(
            self.context,
            "RunFinished",
            {"status": "cancelled", "code": "run_cancelled"},
        )
        renderer.emit(
            self.context,
            "RunFailed",
            {"status": "failed", "code": "llm_request_failed"},
        )

        output = terminal.output
        self.assertIn("[Approval] approval-1", output)
        self.assertIn("write_file: index.html", output)
        self.assertIn("[Agent] Cancelled", output)
        self.assertIn("[Agent] Failed: llm_request_failed", output)

    def test_unknown_events_are_hidden_unless_verbose(self):
        concise_terminal = ScriptedTerminal([])
        verbose_terminal = ScriptedTerminal([])

        ShellEventRenderer(concise_terminal, verbose=False).emit(
            self.context,
            "FutureEvent",
            {"content": "sk-secret-1234567890"},
            step=4,
            phase="future",
        )
        ShellEventRenderer(verbose_terminal, verbose=True).emit(
            self.context,
            "FutureEvent",
            {"content": "sk-secret-1234567890"},
            step=4,
            phase="future",
        )

        self.assertEqual(concise_terminal.output, "")
        self.assertIn("[Event] FutureEvent", verbose_terminal.output)
        self.assertIn("step=4 phase=future", verbose_terminal.output)
        self.assertNotIn("sk-secret", verbose_terminal.output)
        self.assertNotIn("content", verbose_terminal.output)

    def test_render_event_line_uses_bounded_allowed_fields_only(self):
        long_summary = "summary " + ("x" * 500)
        line = render_event_line(
            "GateCompleted",
            {
                "passed": False,
                "summary": long_summary,
                "message": "forbidden message",
                "unknown": "forbidden unknown",
            },
        )

        self.assertTrue(line.startswith("Failed: summary"))
        self.assertLessEqual(len(line), 260)
        self.assertNotIn("forbidden message", line)
        self.assertNotIn("forbidden unknown", line)


if __name__ == "__main__":
    unittest.main()
