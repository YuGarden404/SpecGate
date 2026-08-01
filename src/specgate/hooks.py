from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Callable, TypeVar, cast

from specgate.gate import GateResult
from specgate.run_state import RunStatus
from specgate.runtime_events import RunEventContext, RunEventSink
from specgate.tool_runtime import PreparedToolCall, ToolResult


@dataclass(frozen=True)
class RunStarted:
    context: RunEventContext
    task: str
    step: int = 0


@dataclass(frozen=True)
class BeforeTool:
    context: RunEventContext
    prepared_call: PreparedToolCall
    step: int = 1


@dataclass(frozen=True)
class AfterTool:
    context: RunEventContext
    prepared_call: PreparedToolCall
    tool_result: ToolResult
    step: int = 1


@dataclass(frozen=True)
class AfterGate:
    context: RunEventContext
    prepared_call: PreparedToolCall
    tool_result: ToolResult
    gate_result: GateResult
    step: int = 1


@dataclass(frozen=True)
class RunFinished:
    context: RunEventContext
    status: RunStatus
    step: int = 1


class BeforeToolDecisionKind(str, Enum):
    CONTINUE = "continue"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class BeforeToolDecision:
    kind: BeforeToolDecisionKind
    code: str = ""
    reason: str = ""

    @classmethod
    def continue_(cls) -> BeforeToolDecision:
        return cls(BeforeToolDecisionKind.CONTINUE)

    @classmethod
    def block(cls, code: str, reason: str = "") -> BeforeToolDecision:
        return cls(BeforeToolDecisionKind.BLOCK, code, reason)

    @classmethod
    def require_approval(
        cls,
        code: str,
        reason: str = "",
    ) -> BeforeToolDecision:
        return cls(BeforeToolDecisionKind.REQUIRE_APPROVAL, code, reason)


RunStartedHook = Callable[[RunStarted], object]
BeforeToolHook = Callable[[BeforeTool], BeforeToolDecision]
AfterToolHook = Callable[[AfterTool], object]
AfterGateHook = Callable[[AfterGate], object]
RunFinishedHook = Callable[[RunFinished], object]
ObserverEventT = TypeVar(
    "ObserverEventT",
    RunStarted,
    AfterTool,
    AfterGate,
    RunFinished,
)


def _snapshot_call(call: PreparedToolCall) -> PreparedToolCall:
    return PreparedToolCall(
        definition=call.definition,
        args=call.args.model_copy(deep=True),
    )


def _snapshot_tool_result(result: ToolResult) -> ToolResult:
    return ToolResult(
        ok=result.ok,
        action=result.action,
        message=result.message,
        data=deepcopy(result.data),
        blocked=result.blocked,
        rule_family=result.rule_family,
        code=result.code,
    )


def _snapshot_gate_result(result: GateResult) -> GateResult:
    return GateResult(
        passed=result.passed,
        checks=deepcopy(result.checks),
        issues=deepcopy(result.issues),
        summary=result.summary,
        artifact_sha256=result.artifact_sha256,
        checklist_sha256=result.checklist_sha256,
    )


def _snapshot_before_tool(event: BeforeTool) -> BeforeTool:
    return BeforeTool(
        event.context,
        _snapshot_call(event.prepared_call),
        event.step,
    )


def _snapshot_observer(event: ObserverEventT) -> ObserverEventT:
    if isinstance(event, AfterTool):
        snapshot = AfterTool(
            event.context,
            _snapshot_call(event.prepared_call),
            _snapshot_tool_result(event.tool_result),
            event.step,
        )
        return cast(ObserverEventT, snapshot)
    if isinstance(event, AfterGate):
        snapshot = AfterGate(
            event.context,
            _snapshot_call(event.prepared_call),
            _snapshot_tool_result(event.tool_result),
            _snapshot_gate_result(event.gate_result),
            event.step,
        )
        return cast(ObserverEventT, snapshot)
    return event


class HookBus:
    def __init__(self, event_sink: RunEventSink) -> None:
        self._event_sink = event_sink
        self._run_started: list[RunStartedHook] = []
        self._before_tool: list[tuple[BeforeToolHook, bool]] = []
        self._after_tool: list[AfterToolHook] = []
        self._after_gate: list[AfterGateHook] = []
        self._run_finished: list[RunFinishedHook] = []

    def register_run_started(self, hook: RunStartedHook) -> None:
        self._run_started.append(hook)

    def register_before_tool(
        self,
        hook: BeforeToolHook,
        *,
        enforcing: bool = False,
    ) -> None:
        self._before_tool.append((hook, enforcing))

    def register_after_tool(self, hook: AfterToolHook) -> None:
        self._after_tool.append(hook)

    def register_after_gate(self, hook: AfterGateHook) -> None:
        self._after_gate.append(hook)

    def register_run_finished(self, hook: RunFinishedHook) -> None:
        self._run_finished.append(hook)

    def run_started(self, event: RunStarted) -> None:
        self._notify("RunStarted", event, self._run_started)

    def before_tool(self, event: BeforeTool) -> BeforeToolDecision:
        for hook, enforcing in tuple(self._before_tool):
            try:
                decision = hook(_snapshot_before_tool(event))
                self._validate_before_tool_decision(decision)
            except Exception as exc:
                self._record_hook_failure("BeforeTool", event, exc)
                if enforcing:
                    return BeforeToolDecision.block("hook_failed_closed")
                continue
            if decision.kind is not BeforeToolDecisionKind.CONTINUE:
                return decision
        return BeforeToolDecision.continue_()

    def after_tool(self, event: AfterTool) -> None:
        self._notify("AfterTool", event, self._after_tool)

    def after_gate(self, event: AfterGate) -> None:
        self._notify("AfterGate", event, self._after_gate)

    def run_finished(self, event: RunFinished) -> None:
        self._notify("RunFinished", event, self._run_finished)

    def _notify(
        self,
        hook_event: str,
        event: ObserverEventT,
        hooks: Sequence[Callable[[ObserverEventT], object]],
    ) -> None:
        for hook in tuple(hooks):
            try:
                hook(_snapshot_observer(event))
            except Exception as exc:
                self._record_hook_failure(hook_event, event, exc)

    @staticmethod
    def _validate_before_tool_decision(decision: object) -> None:
        if type(decision) is not BeforeToolDecision:
            raise TypeError("BeforeTool hook must return BeforeToolDecision")
        if not isinstance(decision.kind, BeforeToolDecisionKind):
            raise TypeError("BeforeToolDecision.kind is invalid")
        if not isinstance(decision.code, str):
            raise TypeError("BeforeToolDecision.code must be a string")
        if not isinstance(decision.reason, str):
            raise TypeError("BeforeToolDecision.reason must be a string")

    def _record_hook_failure(
        self,
        hook_event: str,
        event: RunStarted | BeforeTool | AfterTool | AfterGate | RunFinished,
        error: Exception,
    ) -> None:
        try:
            error_message = str(error)
        except Exception:
            error_message = "<unprintable hook exception>"
        self._event_sink.emit(
            event.context,
            "HookFailed",
            {
                "hook_event": hook_event,
                "error_type": type(error).__name__,
                "error": error_message,
            },
            step=event.step,
            phase="hook",
        )
