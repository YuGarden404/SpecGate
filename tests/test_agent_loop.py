import inspect
import unittest

import specgate.agent_loop as agent_loop_module
from specgate.action_pipeline import ExecutionOutcome, ExecutionStatus
from specgate.actions import ActionParseError, parse_action
from specgate.agent_loop import AgentLoop, ContextBuild, parse_error_delta
from specgate.gate import GateResult
from specgate.llm import LLMProviderError
from specgate.run_control import (
    DefaultStopPolicy,
    RunCancelled,
    RunTimedOut,
)
from specgate.run_state import (
    InMemoryRunStateStore,
    Observation,
    RunState,
    RunStatus,
    StateDelta,
)
from specgate.runtime_events import InMemoryRunEventSink, RunEventContext


class RecordingContextBuilder:
    def __init__(self):
        self.states = []

    def build(self, state):
        self.states.append(state)
        return ContextBuild(
            f"context at step {state.step}",
            {"context_kind": "test", "step": state.step},
        )


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.contexts = []

    def complete(self, context):
        self.contexts.append(context)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ScriptedExecutor:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def execute(self, action, state):
        self.calls.append((action, state))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ScriptedCancellationToken:
    def __init__(self, checks):
        self.checks = list(checks)

    def check(self):
        if not self.checks:
            return
        result = self.checks.pop(0)
        if isinstance(result, BaseException):
            raise result

    def remaining_seconds(self):
        return 60.0


class FailingEventSink:
    def __init__(self, error, event_type=None):
        self.error = error
        self.event_type = event_type

    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        if self.event_type is None or event_type == self.event_type:
            raise self.error


def action_json(name="finish"):
    return (
        '{"schema_version":"1","action":"'
        + name
        + '","args":{}}'
    )


def successful_outcome(step, *, finish=False, gate=None):
    return ExecutionOutcome(
        ExecutionStatus.SUCCEEDED,
        StateDelta(
            step=step,
            latest_gate=gate,
            finish_requested=True if finish else None,
        ),
        gate_result=gate,
    )


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryRunStateStore()
        self.store.create(RunState("run-1"))
        self.context_builder = RecordingContextBuilder()
        self.event_sink = InMemoryRunEventSink(
            clock=lambda: "2026-07-30T00:00:00Z"
        )
        self.event_context = RunEventContext("run-1", "agent-run-1")

    def make_loop(
        self,
        *,
        responses,
        outcomes=(),
        max_steps=5,
        cancel_checks=(),
        executor=None,
    ):
        llm = ScriptedLLM(responses)
        selected_executor = executor or ScriptedExecutor(outcomes)
        loop = AgentLoop(
            context_builder=self.context_builder,
            llm=llm,
            parse_action=parse_action,
            action_executor=selected_executor,
            state_store=self.store,
            stop_policy=DefaultStopPolicy(max_steps),
            cancel_token=ScriptedCancellationToken(cancel_checks),
            event_sink=self.event_sink,
            event_context=self.event_context,
        )
        return loop, llm, selected_executor

    def test_successful_finish_completes_after_final_gate(self):
        gate = GateResult(True, [], [], "passed")
        loop, llm, executor = self.make_loop(
            responses=[action_json()],
            outcomes=[successful_outcome(1, finish=True, gate=gate)],
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertTrue(result.finish_requested)
        self.assertEqual(result.latest_gate, gate)
        self.assertEqual(len(llm.contexts), 1)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(
            [event.event_type for event in self.event_sink.events],
            ["RunStarted", "ContextBuilt", "LLMCompleted", "RunFinished"],
        )

    def test_parse_error_is_redacted_feedback_and_loop_continues(self):
        secret = "sk-secret-loop-1234567890"
        gate = GateResult(True, [], [], "passed")
        loop, _, executor = self.make_loop(
            responses=[
                '{"schema_version":"' + secret + '","action":"finish","args":{}}',
                action_json(),
            ],
            outcomes=[successful_outcome(2, finish=True, gate=gate)],
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.metrics.parse_errors, 1)
        self.assertEqual(result.step, 2)
        parse_observation = result.observations[0]
        self.assertEqual(parse_observation.kind, "action_parse_failed")
        self.assertEqual(parse_observation.payload["code"], "action_parse_failed")
        self.assertNotIn(secret, repr(result))
        self.assertEqual(len(executor.calls), 1)

    def test_gate_repair_outcome_runs_another_iteration(self):
        failed_gate = GateResult(False, [], [], "repair index.html")
        passed_gate = GateResult(True, [], [], "passed")
        repair = ExecutionOutcome(
            ExecutionStatus.FAILED,
            StateDelta(
                step=1,
                append_observations=(
                    Observation("gate_result", {"summary": "repair index.html"}),
                ),
                latest_gate=failed_gate,
            ),
            gate_result=failed_gate,
        )
        loop, llm, executor = self.make_loop(
            responses=[action_json("write_file"), action_json()],
            outcomes=[repair, successful_outcome(2, finish=True, gate=passed_gate)],
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(len(llm.contexts), 2)
        self.assertEqual(len(executor.calls), 2)
        self.assertEqual(result.observations[0].kind, "gate_result")

    def test_approval_outcome_suspends_and_preserves_state(self):
        approval = ExecutionOutcome(
            ExecutionStatus.APPROVAL_REQUIRED,
            StateDelta(
                status=RunStatus.NEEDS_APPROVAL,
                step=1,
                pending_approval_id="approval-1",
            ),
        )
        loop, _, _ = self.make_loop(
            responses=[action_json("write_file")],
            outcomes=[approval],
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.NEEDS_APPROVAL)
        self.assertEqual(result.pending_approval_id, "approval-1")
        self.assertEqual(self.event_sink.events[-1].event_type, "RunSuspended")

    def test_max_steps_terminates_after_parse_error(self):
        loop, llm, executor = self.make_loop(
            responses=["not json"],
            max_steps=1,
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.FAILED)
        self.assertEqual(result.step, 1)
        self.assertEqual(result.metrics.parse_errors, 1)
        self.assertEqual(len(llm.contexts), 1)
        self.assertEqual(executor.calls, [])

    def test_cancellation_and_timeout_persist_distinct_statuses(self):
        cases = (
            (RunCancelled("user cancelled"), RunStatus.CANCELLED, "run_cancelled"),
            (RunTimedOut("deadline"), RunStatus.TIMED_OUT, "run_timed_out"),
        )
        for error, expected_status, expected_code in cases:
            with self.subTest(status=expected_status):
                store = InMemoryRunStateStore()
                store.create(RunState("run-1"))
                self.store = store
                self.event_sink = InMemoryRunEventSink(
                    clock=lambda: "2026-07-30T00:00:00Z"
                )
                loop, llm, _ = self.make_loop(
                    responses=[action_json()],
                    cancel_checks=[error],
                )

                result = loop.run("run-1")

                self.assertEqual(result.status, expected_status)
                self.assertEqual(result.observations[-1].payload["code"], expected_code)
                self.assertEqual(llm.contexts, [])

    def test_pipeline_program_error_is_persisted_then_re_raised(self):
        error = RuntimeError("secret transport body sk-secret-loop-1234567890")
        loop, _, _ = self.make_loop(
            responses=[action_json("read_file")],
            executor=ScriptedExecutor([error]),
        )

        with self.assertRaises(RuntimeError) as raised:
            loop.run("run-1")

        self.assertIs(raised.exception, error)
        state = self.store.get("run-1")
        self.assertEqual(state.status, RunStatus.FAILED)
        self.assertEqual(state.observations[-1].payload["code"], "runtime_failed")
        self.assertNotIn("sk-secret-loop", repr(state))
        self.assertNotIn("sk-secret-loop", repr(self.event_sink.events))

    def test_start_event_failure_is_persisted_then_re_raised(self):
        error = RuntimeError("event backend failed")
        self.event_sink = FailingEventSink(error)
        loop, _, _ = self.make_loop(responses=[action_json()])

        with self.assertRaises(RuntimeError) as raised:
            loop.run("run-1")

        self.assertIs(raised.exception, error)
        self.assertEqual(self.store.get("run-1").status, RunStatus.FAILED)

    def test_control_signal_event_failure_becomes_a_system_failure(self):
        error = RuntimeError("event backend failed during cancellation")
        self.event_sink = FailingEventSink(error, event_type="RunFinished")
        loop, _, _ = self.make_loop(
            responses=[action_json()],
            cancel_checks=[RunCancelled("user cancelled")],
        )

        with self.assertRaises(RuntimeError) as raised:
            loop.run("run-1")

        self.assertIs(raised.exception, error)
        self.assertEqual(self.store.get("run-1").status, RunStatus.FAILED)

    def test_provider_failures_use_stable_codes_without_raw_details(self):
        cases = (
            ("llm_authentication_failed", RunStatus.FAILED),
            ("llm_rate_limited", RunStatus.FAILED),
            ("llm_provider_unavailable", RunStatus.FAILED),
            ("llm_request_timeout", RunStatus.TIMED_OUT),
        )
        for code, expected_status in cases:
            with self.subTest(code=code):
                store = InMemoryRunStateStore()
                store.create(RunState("run-1"))
                self.store = store
                self.event_sink = InMemoryRunEventSink(
                    clock=lambda: "2026-07-30T00:00:00Z"
                )
                error = LLMProviderError(
                    code,
                    "Authorization: Bearer sk-secret-provider-1234567890 raw body",
                )
                loop, _, _ = self.make_loop(responses=[error])

                result = loop.run("run-1")

                self.assertEqual(result.status, expected_status)
                self.assertEqual(result.observations[-1].payload["code"], code)
                self.assertNotIn("sk-secret-provider", repr(result))
                self.assertNotIn("sk-secret-provider", repr(self.event_sink.events))

    def test_unknown_provider_code_is_normalized(self):
        secret = "sk-secret-provider-code-1234567890"
        loop, _, _ = self.make_loop(
            responses=[LLMProviderError(secret, "raw transport response")]
        )

        result = loop.run("run-1")

        self.assertEqual(result.status, RunStatus.FAILED)
        self.assertEqual(
            result.observations[-1].payload["code"],
            "llm_provider_failed",
        )
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, repr(self.event_sink.events))

    def test_parse_error_delta_accepts_error_without_storing_its_message(self):
        secret = "sk-secret-parse-error-1234567890"

        delta = parse_error_delta(
            self.store.get("run-1"),
            ActionParseError(secret),
        )

        self.assertEqual(delta.append_observations[0].kind, "action_parse_failed")
        self.assertNotIn(secret, repr(delta))

    def test_source_contains_no_role_tool_skill_or_workflow_branches(self):
        source = inspect.getsource(agent_loop_module)

        for forbidden in (
            "write_file",
            "planner",
            "reviewer",
            "SkillRegistry",
            "multi-agent-isolated",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
