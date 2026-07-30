import unittest
from dataclasses import FrozenInstanceError, replace

from specgate.actions import Action
from specgate.gate import GateResult
from specgate.hooks import (
    AfterGate,
    AfterTool,
    BeforeTool,
    BeforeToolDecision,
    BeforeToolDecisionKind,
    HookBus,
    RunFinished,
    RunStarted,
)
from specgate.run_state import RunStatus
from specgate.runtime_events import InMemoryRunEventSink, RunEventContext
from specgate.tool_registry import default_tool_registry
from specgate.tool_runtime import PreparedToolCall, ToolResult, ToolRuntime


class HookBusTests(unittest.TestCase):
    def setUp(self):
        self.sink = InMemoryRunEventSink(
            clock=lambda: "2026-07-30T00:00:00Z"
        )
        self.context = RunEventContext("run-1", "agent-run-1", "parent-1")
        preparation = ToolRuntime(default_tool_registry()).prepare(
            Action("1", "read_file", {"path": "index.html"})
        )
        self.call = preparation.call
        self.tool_result = ToolResult.success(
            "read_file",
            {"path": "index.html", "content": "page"},
        )
        self.gate_result = GateResult(True, [], [], "passed")

    def test_before_tool_hooks_run_in_registration_order(self):
        calls = []
        bus = HookBus(event_sink=self.sink)
        bus.register_before_tool(
            lambda event: calls.append("first")
            or BeforeToolDecision.continue_()
        )
        bus.register_before_tool(
            lambda event: calls.append("second")
            or BeforeToolDecision.continue_()
        )

        result = bus.before_tool(BeforeTool(self.context, self.call, step=2))

        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(result.kind, BeforeToolDecisionKind.CONTINUE)

    def test_first_restrictive_before_tool_decision_stops_later_hooks(self):
        calls = []
        bus = HookBus(event_sink=self.sink)
        bus.register_before_tool(
            lambda event: calls.append("block")
            or BeforeToolDecision.block("policy_hook", "project policy")
        )
        bus.register_before_tool(
            lambda event: calls.append("late")
            or BeforeToolDecision.continue_()
        )

        result = bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(calls, ["block"])
        self.assertEqual(result.kind, BeforeToolDecisionKind.BLOCK)
        self.assertEqual(result.code, "policy_hook")

    def test_all_lifecycle_observers_are_ordered_and_cannot_control(self):
        calls = []
        bus = HookBus(event_sink=self.sink)

        def observe(name):
            def hook(event):
                calls.append(name)
                return BeforeToolDecision.block("ignored")

            return hook

        bus.register_run_started(observe("run_started"))
        bus.register_after_tool(observe("after_tool"))
        bus.register_after_gate(observe("after_gate"))
        bus.register_run_finished(observe("run_finished"))

        self.assertIsNone(bus.run_started(RunStarted(self.context, "task")))
        self.assertIsNone(
            bus.after_tool(
                AfterTool(self.context, self.call, self.tool_result, step=1)
            )
        )
        self.assertIsNone(
            bus.after_gate(
                AfterGate(
                    self.context,
                    self.call,
                    self.tool_result,
                    self.gate_result,
                    step=1,
                )
            )
        )
        self.assertIsNone(
            bus.run_finished(
                RunFinished(self.context, RunStatus.COMPLETED, step=1)
            )
        )
        self.assertEqual(
            calls,
            ["run_started", "after_tool", "after_gate", "run_finished"],
        )

    def test_observer_failure_is_redacted_recorded_and_continues(self):
        calls = []
        bus = HookBus(event_sink=self.sink)

        def failing(event):
            raise RuntimeError("token sk-secret-hook-1234567890")

        bus.register_after_tool(failing)
        bus.register_after_tool(lambda event: calls.append("continued"))

        bus.after_tool(
            AfterTool(self.context, self.call, self.tool_result, step=3)
        )

        self.assertEqual(calls, ["continued"])
        self.assertEqual(self.sink.events[0].event_type, "HookFailed")
        self.assertEqual(self.sink.events[0].step, 3)
        self.assertNotIn("sk-secret-hook", str(self.sink.events[0].payload))

    def test_unprintable_observer_failure_is_recorded_and_continues(self):
        calls = []
        bus = HookBus(event_sink=self.sink)

        class UnprintableError(RuntimeError):
            def __str__(self):
                raise RuntimeError("render failed")

        def failing(event):
            raise UnprintableError()

        bus.register_after_tool(failing)
        bus.register_after_tool(lambda event: calls.append("continued"))

        bus.after_tool(
            AfterTool(self.context, self.call, self.tool_result, step=3)
        )

        self.assertEqual(calls, ["continued"])
        self.assertEqual(self.sink.events[0].event_type, "HookFailed")
        self.assertEqual(
            self.sink.events[0].payload["error_type"],
            "UnprintableError",
        )

    def test_non_enforcing_before_tool_failure_records_and_continues(self):
        bus = HookBus(event_sink=self.sink)
        bus.register_before_tool(
            lambda event: 1 / 0,
            enforcing=False,
        )

        result = bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(result.kind, BeforeToolDecisionKind.CONTINUE)
        self.assertEqual(self.sink.events[0].event_type, "HookFailed")

    def test_enforcing_before_tool_failure_blocks(self):
        bus = HookBus(event_sink=self.sink)
        bus.register_before_tool(lambda event: 1 / 0, enforcing=True)

        result = bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(result.kind, BeforeToolDecisionKind.BLOCK)
        self.assertEqual(result.code, "hook_failed_closed")

    def test_unprintable_enforcing_before_tool_failure_blocks(self):
        bus = HookBus(event_sink=self.sink)

        class UnprintableError(RuntimeError):
            def __str__(self):
                raise RuntimeError("render failed")

        def failing(event):
            raise UnprintableError()

        bus.register_before_tool(failing, enforcing=True)

        result = bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(result.kind, BeforeToolDecisionKind.BLOCK)
        self.assertEqual(result.code, "hook_failed_closed")
        self.assertEqual(self.sink.events[0].event_type, "HookFailed")

    def test_invalid_allow_override_result_cannot_expand_permissions(self):
        class AllowOverride:
            kind = "allow_override"

        bus = HookBus(event_sink=self.sink)
        bus.register_before_tool(lambda event: AllowOverride())
        bus.register_before_tool(
            lambda event: BeforeToolDecision.require_approval(
                "review_required",
                "review this action",
            )
        )

        result = bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(
            result.kind,
            BeforeToolDecisionKind.REQUIRE_APPROVAL,
        )
        self.assertEqual(result.code, "review_required")
        self.assertEqual(self.sink.events[0].event_type, "HookFailed")

    def test_before_tool_hooks_receive_independent_call_snapshots(self):
        observed_paths = []
        bus = HookBus(event_sink=self.sink)

        def mutate(event):
            event.prepared_call.args.path = "changed.html"
            return BeforeToolDecision.continue_()

        bus.register_before_tool(mutate)
        bus.register_before_tool(
            lambda event: observed_paths.append(event.prepared_call.args.path)
            or BeforeToolDecision.continue_()
        )

        bus.before_tool(BeforeTool(self.context, self.call, step=1))

        self.assertEqual(observed_paths, ["index.html"])
        self.assertEqual(self.call.args.path, "index.html")

    def test_call_snapshot_does_not_copy_the_tool_handler(self):
        calls = []
        bus = HookBus(event_sink=self.sink)

        class NonCopyableHandler:
            def __deepcopy__(self, memo):
                raise TypeError("handler cannot be copied")

        definition = replace(
            self.call.definition,
            handler=NonCopyableHandler(),
        )
        call = PreparedToolCall(definition, self.call.args)
        bus.register_before_tool(
            lambda event: calls.append(event.prepared_call.definition.name)
            or BeforeToolDecision.continue_()
        )

        result = bus.before_tool(BeforeTool(self.context, call, step=1))

        self.assertEqual(calls, ["read_file"])
        self.assertEqual(result.kind, BeforeToolDecisionKind.CONTINUE)
        self.assertEqual(self.sink.events, ())

    def test_after_gate_hooks_receive_independent_result_snapshots(self):
        observed = []
        bus = HookBus(event_sink=self.sink)

        def mutate(event):
            event.tool_result.data["path"] = "changed.html"
            event.gate_result.checks.append("changed")

        def observe(event):
            observed.append(
                (event.tool_result.data["path"], event.gate_result.checks)
            )

        bus.register_after_gate(mutate)
        bus.register_after_gate(observe)

        bus.after_gate(
            AfterGate(
                self.context,
                self.call,
                self.tool_result,
                self.gate_result,
                step=1,
            )
        )

        self.assertEqual(observed, [("index.html", [])])
        self.assertEqual(self.tool_result.data["path"], "index.html")
        self.assertEqual(self.gate_result.checks, [])

    def test_hooks_registered_during_dispatch_start_on_next_event(self):
        calls = []
        bus = HookBus(event_sink=self.sink)

        def register_late(event):
            calls.append("current")
            bus.register_after_tool(lambda event: calls.append("late"))

        bus.register_after_tool(register_late)
        event = AfterTool(self.context, self.call, self.tool_result, step=1)

        bus.after_tool(event)
        self.assertEqual(calls, ["current"])

        bus.after_tool(event)
        self.assertEqual(calls, ["current", "current", "late"])

    def test_hook_events_and_decisions_are_frozen(self):
        event = BeforeTool(self.context, self.call, step=1)
        decision = BeforeToolDecision.continue_()

        with self.assertRaises(FrozenInstanceError):
            event.step = 2
        with self.assertRaises(FrozenInstanceError):
            decision.code = "changed"

    def test_before_tool_decision_kind_has_no_allow_override(self):
        self.assertEqual(
            {kind.value for kind in BeforeToolDecisionKind},
            {"continue", "block", "require_approval"},
        )


if __name__ == "__main__":
    unittest.main()
