from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from specgate.run_state import RunState, RunStatus


class RunCancelled(RuntimeError):
    pass


class RunTimedOut(RuntimeError):
    pass


class LoopDecisionKind(str, Enum):
    CONTINUE = "continue"
    SUSPEND = "suspend"
    TERMINATE = "terminate"


@dataclass(frozen=True)
class LoopDecision:
    kind: LoopDecisionKind
    outcome: RunStatus | None = None
    reason: str = ""


@runtime_checkable
class CancellationToken(Protocol):
    def check(self) -> None: ...

    def remaining_seconds(self) -> float: ...


@dataclass(frozen=True)
class CallbackCancellationToken:
    stop_check: Callable[[], None]
    remaining: Callable[[], float] = lambda: float("inf")

    def check(self) -> None:
        self.stop_check()

    def remaining_seconds(self) -> float:
        return self.remaining()


class StopPolicy(Protocol):
    def decide(self, state: RunState) -> LoopDecision: ...


@dataclass(frozen=True)
class DefaultStopPolicy:
    max_steps: int

    def __post_init__(self) -> None:
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int):
            raise ValueError("max_steps must be a positive integer")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")

    def decide(self, state: RunState) -> LoopDecision:
        if state.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }:
            return LoopDecision(
                LoopDecisionKind.TERMINATE,
                outcome=state.status,
                reason="terminal_state",
            )
        if state.status is RunStatus.NEEDS_APPROVAL:
            return LoopDecision(
                LoopDecisionKind.SUSPEND,
                reason="approval_required",
            )
        if state.step >= self.max_steps:
            return LoopDecision(
                LoopDecisionKind.TERMINATE,
                outcome=RunStatus.FAILED,
                reason="max_steps_reached",
            )
        if state.finish_requested:
            if state.latest_gate is None:
                return LoopDecision(
                    LoopDecisionKind.CONTINUE,
                    reason="final_gate_required",
                )
            if not state.latest_gate.passed:
                return LoopDecision(
                    LoopDecisionKind.CONTINUE,
                    reason="gate_repair_required",
                )
            return LoopDecision(
                LoopDecisionKind.TERMINATE,
                outcome=RunStatus.COMPLETED,
                reason="finish_accepted",
            )
        return LoopDecision(LoopDecisionKind.CONTINUE, reason="running")
