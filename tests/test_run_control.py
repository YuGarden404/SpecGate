import threading
import unittest

from specgate.gate import GateResult
from specgate.run_control import (
    CallbackCancellationToken,
    CancellationToken,
    DefaultStopPolicy,
    LoopDecisionKind,
    RunCancelled,
    RunTimedOut,
)
from specgate.run_state import RunState, RunStatus
from specgate.web_runtime import (
    RunCancelled as WebRunCancelled,
    RunControl,
    RunTimedOut as WebRunTimedOut,
)


class StopPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = DefaultStopPolicy(max_steps=5)

    def test_running_state_continues(self):
        decision = self.policy.decide(RunState("run-1"))

        self.assertEqual(decision.kind, LoopDecisionKind.CONTINUE)
        self.assertIsNone(decision.outcome)

    def test_approval_state_suspends_without_terminating(self):
        decision = self.policy.decide(
            RunState("run-1", status=RunStatus.NEEDS_APPROVAL)
        )

        self.assertEqual(decision.kind, LoopDecisionKind.SUSPEND)
        self.assertIsNone(decision.outcome)
        self.assertEqual(decision.reason, "approval_required")

    def test_terminal_states_terminate_with_existing_outcome(self):
        terminal_statuses = (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        )
        for status in terminal_statuses:
            with self.subTest(status=status):
                decision = self.policy.decide(RunState("run-1", status=status))
                self.assertEqual(decision.kind, LoopDecisionKind.TERMINATE)
                self.assertEqual(decision.outcome, status)

    def test_step_exhaustion_terminates_as_failed(self):
        decision = self.policy.decide(RunState("run-1", step=5))

        self.assertEqual(decision.kind, LoopDecisionKind.TERMINATE)
        self.assertEqual(decision.outcome, RunStatus.FAILED)
        self.assertEqual(decision.reason, "max_steps_reached")

    def test_finish_with_passing_gate_completes(self):
        decision = self.policy.decide(
            RunState(
                "run-1",
                step=1,
                finish_requested=True,
                latest_gate=GateResult(True, [], [], "passed"),
            )
        )

        self.assertEqual(decision.kind, LoopDecisionKind.TERMINATE)
        self.assertEqual(decision.outcome, RunStatus.COMPLETED)
        self.assertEqual(decision.reason, "finish_accepted")

    def test_finish_without_passing_gate_continues_for_validation_or_repair(self):
        states = (
            RunState("run-1", finish_requested=True),
            RunState(
                "run-1",
                finish_requested=True,
                latest_gate=GateResult(False, [], [], "failed"),
            ),
        )
        for state in states:
            with self.subTest(latest_gate=state.latest_gate):
                decision = self.policy.decide(state)
                self.assertEqual(decision.kind, LoopDecisionKind.CONTINUE)
                self.assertIsNone(decision.outcome)

    def test_max_steps_must_be_a_positive_integer(self):
        for value in (True, 0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    DefaultStopPolicy(max_steps=value)


class CancellationTokenTests(unittest.TestCase):
    def test_callback_token_preserves_stop_exception_and_remaining_time(self):
        expected = RunCancelled("cancelled")

        def stop_check():
            raise expected

        token = CallbackCancellationToken(stop_check, remaining=lambda: 12.5)

        with self.assertRaises(RunCancelled) as raised:
            token.check()
        self.assertIs(raised.exception, expected)
        self.assertEqual(token.remaining_seconds(), 12.5)

    def test_web_run_control_is_the_shared_token_and_cancel_wins_timeout(self):
        cancelled = threading.Event()
        cancelled.set()
        control = RunControl(cancelled, "deadline", 5.0, lambda: 10.0)

        self.assertIsInstance(control, CancellationToken)
        self.assertIs(WebRunCancelled, RunCancelled)
        self.assertIs(WebRunTimedOut, RunTimedOut)
        with self.assertRaises(RunCancelled):
            control.check()


if __name__ == "__main__":
    unittest.main()
