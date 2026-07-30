from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from specgate.actions import Action
from specgate.approvals import (
    ApprovalRequester,
    GovernanceConfig,
    PendingApproval,
)
from specgate.gate import GateContext, GateResult, GateRunner
from specgate.governance import (
    GovernanceDecisionKind,
    GovernanceEngine,
)
from specgate.hooks import (
    AfterGate,
    AfterTool,
    BeforeTool,
    BeforeToolDecisionKind,
    HookBus,
)
from specgate.policy import WorkspacePolicy
from specgate.run_state import Observation, RunStatus, StateDelta
from specgate.runtime_events import RunEventContext
from specgate.tool_handlers import ToolExecutionContext
from specgate.tool_registry import SideEffectClass
from specgate.tool_runtime import (
    PreparedToolCall,
    ToolResult,
    ToolRuntime,
)
from specgate.trace import redact
from specgate.validation import ValidationPolicy


class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class RuntimeErrorInfo:
    code: str
    message: str


@dataclass(frozen=True)
class ExecutionOutcome:
    status: ExecutionStatus
    state_delta: StateDelta
    tool_result: ToolResult | None = None
    gate_result: GateResult | None = None
    approval_request: PendingApproval | None = None
    feedback: Observation | None = None
    error: RuntimeErrorInfo | None = None


@dataclass(frozen=True)
class PipelineExecutionContext:
    event_context: RunEventContext
    step: int
    capabilities: frozenset[str]
    policy: WorkspacePolicy
    governance_config: GovernanceConfig
    tool_context: ToolExecutionContext
    gate_context: GateContext
    approval_requester: ApprovalRequester | None = None

    def __post_init__(self) -> None:
        if self.tool_context.policy != self.policy:
            raise ValueError("tool context policy must match pipeline policy")
        if self.gate_context.policy != self.policy:
            raise ValueError("gate context policy must match pipeline policy")


class ActionPipeline:
    def __init__(
        self,
        runtime: ToolRuntime,
        hooks: HookBus,
        governance: GovernanceEngine,
        validation_policy: ValidationPolicy,
        gate_runner: GateRunner,
    ) -> None:
        self._runtime = runtime
        self._hooks = hooks
        self._governance = governance
        self._validation_policy = validation_policy
        self._gate_runner = gate_runner

    def execute(
        self,
        action: Action,
        context: PipelineExecutionContext,
    ) -> ExecutionOutcome:
        preparation = self._runtime.prepare(action)
        if preparation.failure is not None:
            assert preparation.call is None
            return _tool_failure_outcome(preparation.failure, context.step)
        assert preparation.call is not None
        call = preparation.call

        before_decision = self._hooks.before_tool(
            BeforeTool(context.event_context, call, step=context.step)
        )
        if before_decision.kind is BeforeToolDecisionKind.BLOCK:
            return _decision_blocked_outcome(
                action,
                before_decision.code,
                before_decision.reason,
                "hook",
                context.step,
            )
        if before_decision.kind is BeforeToolDecisionKind.REQUIRE_APPROVAL:
            return _approval_outcome(
                action,
                before_decision.code,
                before_decision.reason,
                context,
            )
        assert before_decision.kind is BeforeToolDecisionKind.CONTINUE

        governance_decision = self._governance.evaluate(
            call,
            capabilities=context.capabilities,
            policy=context.policy,
            config=context.governance_config,
        )
        if governance_decision.kind is GovernanceDecisionKind.BLOCK:
            return _decision_blocked_outcome(
                action,
                governance_decision.code,
                governance_decision.reason,
                governance_decision.rule_family,
                context.step,
            )
        if governance_decision.kind is GovernanceDecisionKind.REQUIRE_APPROVAL:
            return _approval_outcome(
                action,
                governance_decision.code,
                governance_decision.reason,
                context,
            )
        assert governance_decision.kind is GovernanceDecisionKind.ALLOW

        tool_result = self._runtime.execute_prepared(call, context.tool_context)
        self._hooks.after_tool(
            AfterTool(
                context.event_context,
                call,
                tool_result,
                step=context.step,
            )
        )
        tool_observation = _tool_observation(tool_result)
        if not tool_result.ok:
            return _tool_failure_outcome(
                tool_result,
                context.step,
                observations=(tool_observation,),
            )

        if not self._validation_policy.should_validate(call, tool_result):
            return ExecutionOutcome(
                ExecutionStatus.SUCCEEDED,
                StateDelta(
                    step=context.step,
                    append_observations=(tool_observation,),
                ),
                tool_result=tool_result,
            )

        gate_result = self._gate_runner.run(context.gate_context)
        self._hooks.after_gate(
            AfterGate(
                context.event_context,
                call,
                tool_result,
                gate_result,
                step=context.step,
            )
        )
        gate_observation = _gate_observation(gate_result)
        observations = (tool_observation, gate_observation)
        if not gate_result.passed:
            return ExecutionOutcome(
                ExecutionStatus.FAILED,
                StateDelta(
                    step=context.step,
                    append_observations=observations,
                    latest_gate=gate_result,
                ),
                tool_result=tool_result,
                gate_result=gate_result,
                feedback=gate_observation,
                error=RuntimeErrorInfo("gate_failed", gate_result.summary),
            )

        finish_requested = (
            True if _is_finish_request(call, tool_result) else None
        )
        return ExecutionOutcome(
            ExecutionStatus.SUCCEEDED,
            StateDelta(
                step=context.step,
                append_observations=observations,
                latest_gate=gate_result,
                finish_requested=finish_requested,
            ),
            tool_result=tool_result,
            gate_result=gate_result,
        )


def _approval_outcome(
    action: Action,
    code: str,
    reason: str,
    context: PipelineExecutionContext,
) -> ExecutionOutcome:
    if context.approval_requester is None:
        message = "approval was required but no approval requester is configured"
        observation = _observation(
            "approval_required",
            {
                "action": action.action,
                "code": code,
                "reason": reason,
                "error": message,
            },
        )
        return ExecutionOutcome(
            ExecutionStatus.FAILED,
            StateDelta(
                step=context.step,
                append_observations=(observation,),
            ),
            feedback=observation,
            error=RuntimeErrorInfo("approval_requester_missing", message),
        )

    approval = context.approval_requester.request(
        action,
        step=context.step,
        reason=reason or code,
    )
    observation = _observation(
        "approval_required",
        {
            "approval_id": approval.id,
            "action": action.action,
            "code": code,
            "reason": reason,
        },
    )
    return ExecutionOutcome(
        ExecutionStatus.APPROVAL_REQUIRED,
        StateDelta(
            status=RunStatus.NEEDS_APPROVAL,
            step=context.step,
            append_observations=(observation,),
            pending_approval_id=approval.id,
        ),
        approval_request=approval,
        feedback=observation,
    )


def _decision_blocked_outcome(
    action: Action,
    code: str,
    reason: str,
    rule_family: str,
    step: int,
) -> ExecutionOutcome:
    message = reason or code or "action blocked"
    observation = _observation(
        "tool_result",
        {
            "action": action.action,
            "ok": False,
            "blocked": True,
            "code": code,
            "message": message,
            "rule_family": rule_family,
            "data": {},
        },
    )
    return ExecutionOutcome(
        ExecutionStatus.BLOCKED,
        StateDelta(step=step, append_observations=(observation,)),
        feedback=observation,
        error=RuntimeErrorInfo(code or "blocked", message),
    )


def _tool_failure_outcome(
    result: ToolResult,
    step: int,
    *,
    observations: tuple[Observation, ...] | None = None,
) -> ExecutionOutcome:
    observation = _tool_observation(result)
    appended = (observation,) if observations is None else observations
    status = ExecutionStatus.BLOCKED if result.blocked else ExecutionStatus.FAILED
    return ExecutionOutcome(
        status,
        StateDelta(step=step, append_observations=appended),
        tool_result=result,
        feedback=observation,
        error=RuntimeErrorInfo(result.code, result.message),
    )


def _tool_observation(result: ToolResult) -> Observation:
    return _observation(
        "tool_result",
        {
            "action": result.action,
            "ok": result.ok,
            "blocked": result.blocked,
            "code": result.code,
            "message": result.message,
            "rule_family": result.rule_family,
            "data": result.data,
        },
    )


def _gate_observation(result: GateResult) -> Observation:
    return _observation(
        "gate_result",
        {
            "passed": result.passed,
            "summary": result.summary,
            "checks": [
                {
                    "code": check.code,
                    "passed": check.passed,
                    "message": check.message,
                }
                for check in result.checks
            ],
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "evidence": issue.evidence,
                    "repair_hint": issue.repair_hint,
                }
                for issue in result.issues
            ],
            "artifact_sha256": result.artifact_sha256,
            "checklist_sha256": result.checklist_sha256,
        },
    )


def _observation(kind: str, payload: dict[str, Any]) -> Observation:
    redacted_payload = redact(payload)
    assert isinstance(redacted_payload, dict)
    return Observation(kind, redacted_payload)


def _is_finish_request(
    call: PreparedToolCall,
    result: ToolResult,
) -> bool:
    return (
        call.definition.side_effect_class is SideEffectClass.RUN_CONTROL
        and call.definition.name == "finish"
        and result.action == call.definition.name
    )
