from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable

import specgate.workspace_fs as workspace_fs
from specgate.action_pipeline import (
    ActionPipeline,
    ExecutionOutcome,
    ExecutionStatus,
    PipelineExecutionContext,
    RuntimeErrorInfo,
)
from specgate.actions import Action, ActionParseError, parse_action
from specgate.agent_loop import AgentLoop, ContextBuild
from specgate.agent_service import (
    AgentBudget,
    AgentDefinition,
    AgentRunResult,
    AgentResumeHandle,
    AgentService,
    BudgetExceeded,
)
from specgate.artifacts import (
    AgentArtifactValidationError,
    ImplementationArtifact,
    PlanArtifact,
    ReviewArtifact,
    parse_agent_artifact,
)
from specgate.approvals import (
    ApprovalDecision,
    ApprovalGrant,
    ApprovalQueue,
    ApprovalStore,
    GovernanceConfig,
    PendingApproval,
    WorkspaceApprovalRequester,
    approval_queue_path,
    capture_target_state,
    classify_action_risk,
)
from specgate.context import (
    ArtifactContextContributor,
    ContextContributor,
    LegacyContextBuilder,
    UserRequestContextContributor,
    build_context_pack_with_metadata,
)
from specgate.context_lifecycle import CompressionConfig
from specgate.gate import GateContext, GateResult, run_html_gate
from specgate.governance import GovernanceDecision, GovernanceDecisionKind, GovernanceEngine
from specgate.hooks import AfterGate, AfterTool, HookBus
from specgate.isolation import build_isolation_evidence
from specgate.llm import LLMClient, LLMProviderError
from specgate.memory import append_memory
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary, add_run_metrics, build_trust_summary, classify_rule_family
from specgate.multi_agent import build_agent_definitions
from specgate.policy import WorkspacePolicy
from specgate.retrieval import RetrievalConfig
from specgate.run_control import (
    CallbackCancellationToken,
    DefaultStopPolicy,
    LoopDecision,
    LoopDecisionKind,
)
from specgate.run_state import InMemoryRunStateStore, Observation, RunState, RunStatus, StateDelta
from specgate.runtime_events import (
    FanoutRunEventSink,
    RunEventContext,
    RunEventSink,
    TraceRunEventSink,
)
from specgate.snapshot import FileSnapshot
from specgate.skill_registry import SkillSession
from specgate.tool_handlers import ToolExecutionContext
from specgate.tool_registry import SideEffectClass, ToolRegistry, default_tool_registry
from specgate.tool_runtime import ToolRuntime
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore, redact
from specgate.validation import DefaultValidationPolicy
from specgate.workflows import SequentialReviewWorkflow, WorkflowBudget, WorkflowTask


def _utc_now_for_runner() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _permission_rule_family(rule_family: str | None, message: str) -> str:
    return rule_family or classify_rule_family(message)


VALID_RUN_OUTCOMES = {
    "completed",
    "needs_approval",
    "failed",
    "cancelled",
    "timed_out",
}
DEFAULT_AGENT_TASK = "Execute the configured workspace task."


@dataclass(frozen=True)
class RunResult:
    passed: bool
    steps: int
    final_gate: GateResult | None
    context_chars_max: int = 0
    metrics: RunMetrics | None = None
    permission_decisions: list[PermissionDecision] | None = None
    trust: TrustSummary | None = None
    profile: str = "strict"
    outcome: str = "failed"
    pending_approval_id: str | None = None
    run_id: str | None = None


class _LegacyRunStateStore:
    def __init__(self, trace: TraceStore, store=None) -> None:
        self._store = store or InMemoryRunStateStore()
        self._trace = trace
        self._pending_context_metrics = RunMetrics()
        self._pending_parse_error: str | None = None

    def create(self, state: RunState) -> RunState:
        return self._store.create(state)

    def get(self, run_id: str) -> RunState:
        return self._store.get(run_id)

    def add_context_metrics(self, metrics: RunMetrics) -> None:
        self._pending_context_metrics = add_run_metrics(
            self._pending_context_metrics,
            metrics,
        )

    def remember_parse_error(self, error: str) -> None:
        self._pending_parse_error = str(redact(error))

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState:
        observations = []
        for observation in delta.append_observations:
            payload = dict(observation.payload)
            if observation.kind in {
                "tool_result",
                "gate_result",
                "action_parse_failed",
                "approval_required",
            }:
                payload = {"step": delta.step, **payload}
            if (
                observation.kind == "action_parse_failed"
                and self._pending_parse_error is not None
            ):
                payload["error"] = self._pending_parse_error
                self._trace.append(
                    "parse_error",
                    {"step": delta.step, "error": self._pending_parse_error},
                )
                self._pending_parse_error = None
            observations.append(Observation(observation.kind, payload))

        merged = replace(
            delta,
            append_observations=tuple(observations),
            metrics=add_run_metrics(delta.metrics, self._pending_context_metrics),
        )
        self._pending_context_metrics = RunMetrics()
        return self._store.apply(run_id, expected_revision, merged)


class _LegacyRunEventSink:
    def __init__(
        self,
        trace: TraceStore,
        observer: RunEventSink | None = None,
    ) -> None:
        self._trace = trace
        observers = () if observer is None else (observer,)
        self._sink = FanoutRunEventSink(TraceRunEventSink(trace), observers)
        self._last_llm_response: str | None = None

    def remember_llm_response(self, response: str) -> None:
        self._last_llm_response = response

    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict,
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        if event_type == "LLMCompleted" and self._last_llm_response is not None:
            self._trace.append(
                "llm_response",
                {"step": step + 1, "text": self._last_llm_response},
            )
            self._last_llm_response = None
        self._sink.emit(
            context,
            event_type,
            payload,
            step=step,
            phase=phase,
        )


class _TracingLLM:
    def __init__(self, llm: LLMClient, event_sink: _LegacyRunEventSink) -> None:
        self._llm = llm
        self._event_sink = event_sink

    def complete(self, context: str) -> str:
        try:
            response = self._llm.complete(context)
        except LLMProviderError as exc:
            raise _LegacyProviderError(exc) from exc
        self._event_sink.remember_llm_response(response)
        return response


class _LegacyProviderError(RuntimeError):
    def __init__(self, original: Exception) -> None:
        super().__init__("provider request failed")
        self.original = original


class _LegacyStopPolicy:
    def __init__(self, max_steps: int) -> None:
        self._default = DefaultStopPolicy(max_steps)

    def decide(self, state: RunState) -> LoopDecision:
        if (
            state.finish_requested
            and state.latest_gate is not None
            and state.latest_gate.passed
        ):
            return LoopDecision(
                LoopDecisionKind.TERMINATE,
                outcome=RunStatus.COMPLETED,
                reason="finish_accepted",
            )
        return self._default.decide(state)


class _DispatcherRuntime(ToolRuntime):
    def __init__(self, dispatcher: ToolDispatcher) -> None:
        super().__init__(dispatcher.registry)
        self._dispatcher = dispatcher

    def execute_prepared(self, call, context):
        del context
        return self._dispatcher.dispatch(
            Action(
                "1",
                call.definition.name,
                call.args.model_dump(mode="python"),
            )
        )


class _RunnerGateRunner:
    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    def run(self, context: GateContext) -> GateResult:
        del context
        self._runner._check_stop()
        result = self._runner._evaluate_gate()
        self._runner._check_stop()
        return result


class _RunnerGovernanceEngine:
    def __init__(self) -> None:
        self._engine = GovernanceEngine()

    def evaluate(
        self,
        call,
        *,
        capabilities: frozenset[str],
        policy: WorkspacePolicy,
        config: GovernanceConfig,
    ) -> GovernanceDecision:
        action = Action(
            "1",
            call.definition.name,
            call.args.model_dump(mode="python"),
        )
        risk = classify_action_risk(action, policy, config)
        if risk.level in {"review", "blocked"}:
            kind = (
                GovernanceDecisionKind.REQUIRE_APPROVAL
                if risk.level == "review" and config.profile == "review"
                else GovernanceDecisionKind.BLOCK
            )
            code = (
                risk.rule_family
                if risk.rule_family != "none"
                else risk.level
            )
            return GovernanceDecision(
                kind,
                code,
                risk.reason,
                risk.rule_family,
                risk,
            )
        return self._engine.evaluate(
            call,
            capabilities=capabilities,
            policy=policy,
            config=config,
        )


class _RunnerActionExecutor:
    def __init__(
        self,
        runner: AgentRunner,
        pipeline: ActionPipeline,
        event_context: RunEventContext,
        permission_decisions: list[PermissionDecision],
        capabilities: frozenset[str] | None = None,
        role: str | None = None,
    ) -> None:
        self._runner = runner
        self._pipeline = pipeline
        self._event_context = event_context
        self._permission_decisions = permission_decisions
        self._capabilities = (
            frozenset(runner.policy.allowed_actions)
            if capabilities is None
            else capabilities
        )
        self._role = role
        self._approval_requester = WorkspaceApprovalRequester(
            runner.root,
            ApprovalStore(runner.approval_queue_file),
            profile=runner.governance_profile,
        )

    def execute(self, action: Action, state: RunState) -> ExecutionOutcome:
        return self._execute(action, state, step=state.step + 1)

    def execute_approval(
        self,
        action: Action,
        state: RunState,
        approval: PendingApproval,
        grant: ApprovalGrant,
    ) -> ExecutionOutcome:
        return self._execute(
            action,
            state,
            step=approval.step,
            approved_request=approval,
            approval_grant=grant,
        )

    def _execute(
        self,
        action: Action,
        state: RunState,
        *,
        step: int,
        approved_request: PendingApproval | None = None,
        approval_grant: ApprovalGrant | None = None,
    ) -> ExecutionOutcome:
        context = PipelineExecutionContext(
            event_context=self._event_context,
            step=step,
            capabilities=self._capabilities,
            policy=self._runner.policy,
            governance_config=self._runner.governance_config,
            tool_context=ToolExecutionContext(
                self._runner.policy,
                self._runner.dispatcher.snapshot,
            ),
            gate_context=GateContext(self._runner.root, self._runner.policy),
            approval_requester=self._approval_requester,
            approved_request=approved_request,
            approval_grant=approval_grant,
        )
        outcome = self._pipeline.execute(action, context)
        outcome = self._normalize_unknown_tool(action, outcome)
        outcome = self._normalize_role_capability_block(action, outcome)
        outcome = self._restore_legacy_blocked_payload(action, outcome)
        if outcome.tool_result is not None and outcome.gate_result is None:
            if outcome.tool_result.code not in {
                "tool_validation_failed",
                "unknown_tool",
            }:
                self._runner._check_stop()

        metrics = self._record_legacy_behavior(action, step, outcome)
        return replace(
            outcome,
            state_delta=replace(
                outcome.state_delta,
                metrics=add_run_metrics(outcome.state_delta.metrics, metrics),
            ),
        )

    def _normalize_role_capability_block(
        self,
        action: Action,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        if (
            self._role is None
            or outcome.feedback is None
            or (
                action.action in self._capabilities
                and (
                    outcome.error is None
                    or outcome.error.code != "capability"
                )
            )
        ):
            return outcome
        message = f"role {self._role} cannot perform {action.action}"
        feedback = Observation(
            outcome.feedback.kind,
            {
                **outcome.feedback.payload,
                "code": "capability",
                "message": message,
                "rule_family": "capability",
            },
        )
        observations = tuple(
            feedback
            if item is outcome.feedback or item.kind == outcome.feedback.kind
            else item
            for item in outcome.state_delta.append_observations
        )
        self._runner.trace.append(
            "role_action_blocked",
            {
                "role": self._role,
                "action": action.action,
                "message": message,
            },
        )
        tool_result = outcome.tool_result
        if tool_result is not None:
            tool_result = replace(
                tool_result,
                message=message,
                blocked=True,
                rule_family="capability",
            )
        return replace(
            outcome,
            feedback=feedback,
            error=RuntimeErrorInfo("capability", message),
            tool_result=tool_result,
            state_delta=replace(
                outcome.state_delta,
                append_observations=observations,
            ),
        )

    def _restore_legacy_blocked_payload(
        self,
        action: Action,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        if (
            outcome.status is not ExecutionStatus.BLOCKED
            or outcome.tool_result is not None
            or outcome.feedback is None
            or outcome.feedback.kind != "tool_result"
        ):
            return outcome
        risk = classify_action_risk(
            action,
            self._runner.policy,
            self._runner.governance_config,
        )
        if risk.level not in {"review", "blocked"}:
            return outcome
        feedback = Observation(
            outcome.feedback.kind,
            {
                **outcome.feedback.payload,
                "data": {"risk": risk.to_dict()},
            },
        )
        observations = tuple(
            feedback if item is outcome.feedback else item
            for item in outcome.state_delta.append_observations
        )
        return replace(
            outcome,
            feedback=feedback,
            state_delta=replace(
                outcome.state_delta,
                append_observations=observations,
            ),
        )

    def _normalize_unknown_tool(
        self,
        action: Action,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcome:
        result = outcome.tool_result
        if result is None or result.code != "unknown_tool":
            return outcome
        message = f"unknown action: {action.action}"
        normalized_result = replace(
            result,
            message=message,
            rule_family="action",
        )
        normalized_observations = tuple(
            Observation(
                observation.kind,
                {
                    **observation.payload,
                    "message": message,
                    "rule_family": "action",
                },
            )
            if observation.kind == "tool_result"
            else observation
            for observation in outcome.state_delta.append_observations
        )
        return replace(
            outcome,
            tool_result=normalized_result,
            state_delta=replace(
                outcome.state_delta,
                append_observations=normalized_observations,
            ),
        )

    def _record_legacy_behavior(
        self,
        action: Action,
        step: int,
        outcome: ExecutionOutcome,
    ) -> RunMetrics:
        result = outcome.tool_result
        validation_failed = (
            result is not None and result.code == "tool_validation_failed"
        )
        unknown_tool = result is not None and result.code == "unknown_tool"
        action_path_value = action.args.get("path")
        action_path = (
            action_path_value if isinstance(action_path_value, str) else None
        )

        if validation_failed:
            self._append_tool_trace(step, result)
            self._runner.trace.append(
                "tool_validation_failed",
                {
                    "step": step,
                    "action": action.action,
                    "code": result.code,
                    "message": result.message,
                },
            )
            metrics = RunMetrics(tool_validation_failures=1)
        elif outcome.status is ExecutionStatus.APPROVAL_REQUIRED:
            reason = str(outcome.feedback.payload.get("reason", ""))
            rule_family = str(outcome.feedback.payload.get("code", "none"))
            self._runner._record_permission_decision(
                self._permission_decisions,
                step,
                action.action,
                action_path,
                ok=False,
                blocked=False,
                message=reason,
                rule_family=rule_family,
            )
            approval = outcome.approval_request
            assert approval is not None
            queue = ApprovalQueue.read(self._runner.approval_queue_file)
            event = {
                "step": step,
                "type": "approval_requested",
                "approval": approval.to_dict(),
                "queue_revision": queue.revision,
            }
            self._runner.trace.append("approval_requested", redact(event))
            metrics = RunMetrics(approval_requests=1, pending_approvals=1)
        elif result is None or unknown_tool:
            feedback = outcome.feedback
            payload = feedback.payload if feedback is not None else {}
            message = (
                result.message
                if result is not None
                else str(payload.get("message", "action blocked"))
            )
            raw_rule_family = (
                result.rule_family
                if result is not None
                else payload.get("rule_family")
            )
            rule_family = _permission_rule_family(
                raw_rule_family if isinstance(raw_rule_family, str) else None,
                message,
            )
            self._runner._record_permission_decision(
                self._permission_decisions,
                step,
                action.action,
                action_path,
                ok=False,
                blocked=True,
                message=message,
                rule_family=rule_family,
            )
            self._append_blocked_feedback_trace(
                step,
                action.action,
                message,
                payload,
            )
            role_capability_block = (
                self._role is not None
                and outcome.error is not None
                and outcome.error.code == "capability"
            )
            metrics = RunMetrics(
                blocked_actions=0 if role_capability_block else 1
            )
        else:
            self._runner._record_permission_decision(
                self._permission_decisions,
                step,
                action.action,
                action_path,
                ok=result.ok,
                blocked=result.blocked,
                message=result.message,
                rule_family=result.rule_family,
            )
            self._append_tool_trace(step, result)
            metrics = RunMetrics(
                tool_calls=1,
                successful_tool_calls=1 if result.ok else 0,
                blocked_actions=1 if result.blocked else 0,
                finish_actions=1 if action.action == "finish" else 0,
            )

        if outcome.gate_result is not None:
            gate = outcome.gate_result
            self._runner.trace.append(
                "gate_result",
                {"step": step, "passed": gate.passed, "summary": gate.summary},
            )
            metrics = add_run_metrics(
                metrics,
                RunMetrics(
                    gate_runs=1,
                    gate_failures=0 if gate.passed else 1,
                ),
            )
        if (
            self._role is not None
            and outcome.error is not None
            and outcome.error.code == "capability"
        ):
            metrics = add_run_metrics(
                metrics,
                RunMetrics(role_blocked_actions=1),
            )
        return metrics

    def _append_tool_trace(self, step: int, result) -> None:
        self._runner.trace.append(
            "tool_result",
            {"step": step, "result": result.__dict__},
        )

    def _append_blocked_feedback_trace(
        self,
        step: int,
        action_name: str,
        message: str,
        payload: dict,
    ) -> None:
        self._runner.trace.append(
            "tool_result",
            {
                "step": step,
                "result": {
                    "ok": False,
                    "action": action_name,
                    "message": message,
                    "data": payload.get("data", {}),
                    "blocked": True,
                },
            },
        )


class _WorkflowValidationPolicy:
    def should_validate(self, call, result) -> bool:
        del result
        return (
            call.definition.side_effect_class
            is SideEffectClass.WORKSPACE_WRITE
        )


class _ArtifactStopPolicy:
    def __init__(self, max_steps: int) -> None:
        self._default = DefaultStopPolicy(max_steps)

    def decide(self, state: RunState) -> LoopDecision:
        if any(item.kind == "agent_artifact" for item in state.observations):
            return LoopDecision(
                LoopDecisionKind.TERMINATE,
                outcome=RunStatus.COMPLETED,
                reason="artifact_produced",
            )
        return self._default.decide(state)


class _ArtifactActionExecutor:
    def __init__(
        self,
        delegate: _RunnerActionExecutor,
        *,
        runner: AgentRunner,
        run_id: str,
        expected_type,
        references: tuple[str, ...],
    ) -> None:
        self._delegate = delegate
        self._runner = runner
        self._run_id = run_id
        self._expected_type = expected_type
        self._references = references

    def execute(self, action: Action, state: RunState) -> ExecutionOutcome:
        outcome = self._delegate.execute(action, state)
        artifact = self._artifact_for(action, outcome)
        if artifact is None:
            return outcome
        if isinstance(artifact, AgentArtifactValidationError):
            observation = Observation(
                "runtime_error",
                {"code": artifact.code},
            )
            self._runner.trace.append(
                "artifact_schema_invalid",
                {
                    "run_id": self._run_id,
                    "code": artifact.code,
                },
            )
            return replace(
                outcome,
                status=ExecutionStatus.FAILED,
                feedback=observation,
                error=RuntimeErrorInfo(artifact.code, artifact.code),
                state_delta=replace(
                    outcome.state_delta,
                    status=RunStatus.FAILED,
                    append_observations=(
                        outcome.state_delta.append_observations
                        + (observation,)
                    ),
                ),
            )

        payload = artifact.model_dump(mode="json")
        observation = Observation("agent_artifact", payload)
        self._runner.trace.append(
            "agent_artifact",
            {
                "run_id": self._run_id,
                "kind": artifact.kind,
                "schema_version": artifact.schema_version,
                "producer_run_id": artifact.producer_run_id,
                "references": list(artifact.references),
            },
        )
        return replace(
            outcome,
            state_delta=replace(
                outcome.state_delta,
                append_observations=(
                    outcome.state_delta.append_observations
                    + (observation,)
                ),
                finish_requested=True,
            ),
        )

    def _artifact_for(self, action: Action, outcome: ExecutionOutcome):
        if action.action == "finish":
            summary = action.args.get("summary")
            if not isinstance(summary, str):
                return AgentArtifactValidationError(
                    "artifact_schema_invalid"
                )
            try:
                artifact = parse_agent_artifact(summary)
            except AgentArtifactValidationError as exc:
                return exc
            if not isinstance(artifact, self._expected_type):
                return AgentArtifactValidationError(
                    "artifact_schema_invalid"
                )
            return artifact.model_copy(
                update={
                    "producer_run_id": self._run_id,
                    "references": self._references,
                }
            )

        result = outcome.tool_result
        if (
            self._expected_type is ImplementationArtifact
            and action.action in {"write_file", "replace_file"}
            and result is not None
            and result.ok
            and not result.blocked
        ):
            path = action.args.get("path")
            changed_paths = (path,) if isinstance(path, str) else ()
            return ImplementationArtifact(
                producer_run_id=self._run_id,
                references=self._references,
                changed_paths=changed_paths,
                summary=f"Applied {action.action}.",
            )
        return None


class _WorkflowAgentLoop:
    def __init__(self, factory, request, loop, skill_session) -> None:
        self._factory = factory
        self._request = request
        self._loop = loop
        self._skill_session = skill_session

    def run(self, run_id: str) -> RunState:
        state = self._loop.run(run_id)
        result = AgentRunResult(
            run_id=run_id,
            agent_run_id=self._request.agent_run_id,
            parent_run_id=self._request.parent_run_id,
            definition_id=self._request.definition.agent_id,
            effective_capabilities=self._request.effective_capabilities,
            active_skills=self._skill_session.active_names,
            state=state,
        )
        self._factory.runs.append(result)
        self._factory.runner.trace.append(
            "role_finished",
            {
                "role": result.definition_id,
                "phase": _phase_for_definition(result.definition_id),
                "run_id": result.run_id,
                "status": result.state.status.value,
            },
        )
        return state


class _WorkflowRuntimeFactory:
    def __init__(
        self,
        runner: AgentRunner,
        permission_decisions: list[PermissionDecision],
    ) -> None:
        self.runner = runner
        self.permission_decisions = permission_decisions
        self.runs: list[AgentRunResult] = []

    def create(
        self,
        request,
        *,
        state_store,
        skill_session,
        event_context,
    ):
        task = WorkflowTask.model_validate_json(request.task)
        if task.role != request.definition.agent_id:
            raise ValueError("workflow role does not match AgentDefinition")
        expected_type = {
            "planner": PlanArtifact,
            "implementer": ImplementationArtifact,
            "reviewer": ReviewArtifact,
        }[task.role]
        phase = _phase_for_definition(task.role)
        self.runner.trace.append(
            "role_started",
            {
                "role": task.role,
                "phase": phase,
                "run_id": request.run_id,
            },
        )
        event_sink = _LegacyRunEventSink(
            self.runner.trace,
            self.runner.event_sink,
        )
        legacy_store = _LegacyRunStateStore(self.runner.trace, state_store)

        def context_built(state: RunState, built: ContextBuild) -> None:
            metrics = RunMetrics(
                context_chars_max=max(
                    0,
                    len(built.text) - state.metrics.context_chars_max,
                )
            )
            metrics = self.runner._record_retrieval(metrics, built.metadata)
            metrics = self.runner._record_compression(metrics, built.metadata)
            legacy_store.add_context_metrics(metrics)
            self.runner.trace.append(
                "role_context_built",
                {
                    "step": len(self.runs) + 1,
                    "role": task.role,
                    "phase": phase,
                    "context_chars": len(built.text),
                },
            )

        visible_registry = ToolRegistry(
            definition
            for definition in default_tool_registry().values()
            if definition.name in request.effective_capabilities
        )
        context_builder = LegacyContextBuilder(
            root=self.runner.root,
            strategy=request.definition.context_policy,
            policy=self.runner.policy,
            context_budget_chars=request.budget.context_chars,
            retrieval_config=self.runner.retrieval_config,
            compression_config=self.runner.compression_config,
            tool_registry=visible_registry,
            context_factory=build_context_pack_with_metadata,
            on_build=context_built,
            context_contributors=(
                *self.runner.context_contributors,
                ArtifactContextContributor(
                    instructions=request.definition.instructions,
                    producer_run_id=request.run_id,
                    task=task.task,
                    artifacts=task.artifacts,
                ),
            ),
        )
        hooks = HookBus(event_sink)
        hooks.register_after_tool(
            lambda event: event_sink.emit(
                event.context,
                "ToolCompleted",
                {
                    "action": event.tool_result.action,
                    "ok": event.tool_result.ok,
                    "blocked": event.tool_result.blocked,
                    "code": event.tool_result.code,
                },
                step=event.step,
                phase="tool",
            )
        )
        hooks.register_after_gate(
            lambda event: event_sink.emit(
                event.context,
                "GateCompleted",
                {
                    "passed": event.gate_result.passed,
                    "summary": event.gate_result.summary,
                },
                step=event.step,
                phase="gate",
            )
        )
        pipeline = ActionPipeline(
            _DispatcherRuntime(self.runner.dispatcher),
            hooks,
            _RunnerGovernanceEngine(),
            _WorkflowValidationPolicy(),
            _RunnerGateRunner(self.runner),
            event_sink=event_sink,
        )
        delegate = _RunnerActionExecutor(
            self.runner,
            pipeline,
            event_context,
            self.permission_decisions,
            capabilities=request.effective_capabilities,
            role=task.role,
        )
        executor = _ArtifactActionExecutor(
            delegate,
            runner=self.runner,
            run_id=request.run_id,
            expected_type=expected_type,
            references=tuple(
                artifact.producer_run_id for artifact in task.artifacts
            ),
        )

        def parse_for_legacy(raw: str) -> Action:
            try:
                return parse_action(raw)
            except ActionParseError as exc:
                legacy_store.remember_parse_error(str(exc))
                raise

        loop = AgentLoop(
            context_builder=context_builder,
            llm=_TracingLLM(self.runner.llm, event_sink),
            parse_action=parse_for_legacy,
            action_executor=executor,
            state_store=legacy_store,
            stop_policy=_ArtifactStopPolicy(request.budget.max_steps),
            cancel_token=request.cancel_token,
            event_sink=event_sink,
            event_context=event_context,
        )
        return _WorkflowAgentLoop(self, request, loop, skill_session)


def _phase_for_definition(agent_id: str) -> str:
    return {
        "planner": "plan",
        "implementer": "implement",
        "reviewer": "review",
    }.get(agent_id, "agent")


class _ResumeOnlyRuntimeFactory:
    def create(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("resume-only AgentService cannot create a new run")


class _LegacyApprovalResumeRuntime:
    def __init__(
        self,
        runner: AgentRunner,
        run_id: str,
        state_store: InMemoryRunStateStore,
    ) -> None:
        self.runner = runner
        self.approval_root = runner.root
        self.approval_store = ApprovalStore(runner.approval_queue_file)
        self.state_store = state_store
        self.event_context = RunEventContext(run_id, f"agent-{run_id}")
        self.event_sink = _LegacyRunEventSink(runner.trace, runner.event_sink)
        self.permission_decisions: list[PermissionDecision] = []
        self.last_result: RunResult | None = None

        hooks = HookBus(self.event_sink)
        hooks.register_after_tool(
            lambda event: self.event_sink.emit(
                event.context,
                "ToolCompleted",
                {
                    "action": event.tool_result.action,
                    "ok": event.tool_result.ok,
                    "blocked": event.tool_result.blocked,
                    "code": event.tool_result.code,
                },
                step=event.step,
                phase="tool",
            )
        )
        hooks.register_after_gate(
            lambda event: self.event_sink.emit(
                event.context,
                "GateCompleted",
                {
                    "passed": event.gate_result.passed,
                    "summary": event.gate_result.summary,
                },
                step=event.step,
                phase="gate",
            )
        )
        pipeline = ActionPipeline(
            _DispatcherRuntime(runner.dispatcher),
            hooks,
            _RunnerGovernanceEngine(),
            DefaultValidationPolicy(),
            _RunnerGateRunner(runner),
            event_sink=self.event_sink,
        )
        self.executor = _RunnerActionExecutor(
            runner,
            pipeline,
            self.event_context,
            self.permission_decisions,
        )

    def execute_approval(
        self,
        action: Action,
        state: RunState,
        approval: PendingApproval,
        grant: ApprovalGrant,
        cancel_token: CallbackCancellationToken,
    ) -> ExecutionOutcome:
        cancel_token.check()
        return self.executor.execute_approval(action, state, approval, grant)

    def approval_already_applied(self, approval: PendingApproval) -> bool:
        action = parse_action(json.dumps(approval.action_payload))
        return _target_matches_approved_content(self.runner.root, action)

    def emit_resume_event(self, event_type: str, payload: dict) -> None:
        if (
            event_type == "ApprovalFailed"
            and isinstance(payload.get("code"), str)
            and payload["code"]
        ):
            approval = self.approval_store.read_existing().find(
                str(payload["approval_id"])
            )
            decision = PermissionDecision(
                step=approval.step,
                action=approval.action,
                path=approval.path,
                allowed=False,
                blocked=True,
                reason=str(payload["code"]),
                profile=self.runner.governance_profile,
                rule_family=str(payload["code"]),
            )
            self.permission_decisions.append(decision)
            self.runner.trace.append("permission_decision", decision.to_dict())
        legacy_type = {
            "RunResumed": "resume_started",
            "ApprovalClaimed": "approval_claimed",
            "ApprovalApplied": "approval_applied",
            "ApprovalDenied": "approval_denied",
            "ApprovalFailed": "approval_failed",
        }[event_type]
        self.runner.trace.append(legacy_type, redact(payload))
        if event_type in {"ApprovalApplied", "ApprovalDenied", "ApprovalFailed"}:
            self.runner.trace.append(
                "resume_finished",
                redact(
                    {
                        "approval_id": payload["approval_id"],
                        "status": payload["status"],
                        "queue_revision": payload["queue_revision"],
                    }
                ),
            )

    def run(self, run_id: str) -> RunState:
        self.last_result = self.runner._run_single_agent_loop(
            run_id=run_id,
            backing_store=self.state_store,
            permission_decisions=self.permission_decisions,
            event_context=self.event_context,
            reset_queue=False,
        )
        return self.state_store.get(run_id)


class _LegacyResumeLoader:
    run_id = "legacy-latest"

    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner
        self.runtime: _LegacyApprovalResumeRuntime | None = None

    def load(
        self,
        run_id: str,
        cancel_token: CallbackCancellationToken,
    ) -> AgentResumeHandle:
        if run_id != self.run_id:
            raise ValueError("unknown legacy run")
        cancel_token.check()
        queue = ApprovalStore(self.runner.approval_queue_file).read_existing()
        approval = queue.next_resume_candidate()
        if approval is None:
            raise ValueError("no approved or denied approval to resume")
        state_store = InMemoryRunStateStore()
        state_store.create(
            RunState(
                run_id,
                status=RunStatus.NEEDS_APPROVAL,
                step=approval.step,
                pending_approval_id=approval.id,
            )
        )
        runtime = _LegacyApprovalResumeRuntime(
            self.runner,
            run_id,
            state_store,
        )
        self.runtime = runtime
        definition = AgentDefinition(
            agent_id="legacy-agent",
            instructions="Resume the existing SpecGate run.",
            capability_set=frozenset(self.runner.policy.allowed_actions),
            context_policy=self.runner.context_strategy,
            budget=AgentBudget(
                max_steps=max(1, self.runner.max_steps),
                context_chars=max(1, self.runner.context_budget_chars),
                child_runs=0,
            ),
        )
        return AgentResumeHandle(
            run_id=run_id,
            agent_run_id=f"agent-{run_id}",
            parent_run_id=None,
            definition=definition,
            effective_capabilities=definition.capability_set,
            skill_session=SkillSession(f"agent-{run_id}"),
            state_store=state_store,
            runtime=runtime,
        )


class _RunnerRuntime:
    def __init__(
        self,
        root: Path,
        llm: LLMClient,
        policy: WorkspacePolicy,
        max_steps: int = 5,
        context_strategy: str = "baseline",
        governance_profile: str | None = None,
        governance_config: GovernanceConfig | None = None,
        audit_dir: Path | None = None,
        approval_queue_file: Path | None = None,
        reset_audit: bool = True,
        stop_check: Callable[[], None] | None = None,
        context_budget_chars: int = 12000,
        retrieval_config: RetrievalConfig | None = None,
        compression_config: CompressionConfig | None = None,
        context_contributors: tuple[ContextContributor, ...] = (),
        event_sink: RunEventSink | None = None,
    ):
        self.root = root
        self.llm = llm
        self.policy = policy
        self.max_steps = max_steps
        self.context_strategy = context_strategy
        self.governance_config = governance_config or GovernanceConfig(profile=governance_profile or "strict")
        self.governance_profile = governance_profile if governance_profile is not None else self.governance_config.profile
        snapshot = FileSnapshot.capture(root, policy.allowed_write_paths)
        self.dispatcher = ToolDispatcher(policy, snapshot)
        if audit_dir is None:
            workspace_fs.ensure_workspace_directory(root, "runs/latest")
            self.run_dir = root / "runs" / "latest"
        else:
            audit_path = Path(audit_dir)
            workspace_fs.ensure_workspace_directory(audit_path.parent, audit_path.name)
            self.run_dir = audit_path
        self.approval_queue_file = approval_queue_file or approval_queue_path(root)
        self._stop_check = stop_check or (lambda: None)
        self.context_budget_chars = context_budget_chars
        self.retrieval_config = retrieval_config or RetrievalConfig()
        self.compression_config = compression_config or CompressionConfig()
        self.context_contributors = context_contributors
        self.event_sink = event_sink
        self.trace = TraceStore(self.run_dir / "trace.jsonl", reset=reset_audit)
        if reset_audit:
            self._reset_run_artifacts()

    def run(self, run_id: str | None = None) -> RunResult:
        self._check_stop()
        if self.context_strategy == "multi-agent-isolated":
            return self._run_multi_agent_workflow()
        return self._run_single_agent_loop(run_id=run_id)

    def _run_multi_agent_workflow(self) -> RunResult:
        self._reset_approval_queue()
        permission_decisions: list[PermissionDecision] = []
        definitions = build_agent_definitions(
            context_chars=max(1, self.context_budget_chars)
        )
        by_id = {definition.agent_id: definition for definition in definitions}
        runtime_factory = _WorkflowRuntimeFactory(
            self,
            permission_decisions,
        )
        workspace_fs.ensure_workspace_directory(self.run_dir, "agents")
        service = AgentService(
            audit_root=self.run_dir / "agents",
            workspace_capabilities=frozenset(self.policy.allowed_actions),
            runtime_factory=runtime_factory,
        )
        workflow = SequentialReviewWorkflow(
            agent_service=service,
            planner=by_id["planner"],
            implementer=by_id["implementer"],
            reviewer=by_id["reviewer"],
            budget=WorkflowBudget(
                AgentBudget(
                    max_steps=max(1, self.max_steps),
                    context_chars=(
                        max(1, self.context_budget_chars)
                        * max(1, self.max_steps)
                    ),
                    child_runs=0,
                )
            ),
            cancel_token=CallbackCancellationToken(self._check_stop),
        )
        workflow_result = None
        budget_exhausted = False
        try:
            workflow_result = workflow.run("Execute the configured workspace task.")
        except BudgetExceeded:
            budget_exhausted = True
            self.trace.append(
                "role_step_limit_reached",
                {
                    "step": len(runtime_factory.runs),
                    "max_steps": self.max_steps,
                },
            )
        except _LegacyProviderError as exc:
            raise exc.original from exc.original

        agent_runs = (
            tuple(runtime_factory.runs)
            if workflow_result is None
            else workflow_result.agent_runs
        )
        metrics = self._workflow_metrics(
            agent_runs,
            repair_count=(
                0 if workflow_result is None else workflow_result.repair_count
            ),
            repair_limit_reached=(
                False
                if workflow_result is None
                else workflow_result.repair_limit_reached
            ),
            budget_exhausted=budget_exhausted,
        )
        evidence = build_isolation_evidence(
            strategy=self.context_strategy,
            definitions=definitions,
            agent_runs=agent_runs,
            review_repairs=metrics.review_repairs,
        )
        metrics = self._record_isolation(
            metrics,
            {"isolation": redact(evidence)},
        )
        for execution in evidence["executions"]:
            self.trace.append("role_action", execution)

        if workflow_result is not None and workflow_result.repair_count:
            review = workflow_result.reviews[0]
            self.trace.append(
                "role_repair_requested",
                {
                    "review_repairs": workflow_result.repair_count,
                    "issues": list(redact(review.issues)),
                },
            )
        if workflow_result is not None and workflow_result.repair_limit_reached:
            self.trace.append(
                "role_cycle_limit_reached",
                {"review_repairs": workflow_result.repair_count},
            )

        latest_gate = next(
            (
                run.state.latest_gate
                for run in reversed(agent_runs)
                if run.state.latest_gate is not None
            ),
            None,
        )
        if (
            workflow_result is not None
            and workflow_result.status is RunStatus.NEEDS_APPROVAL
        ):
            approval_id = agent_runs[-1].state.pending_approval_id
            assert approval_id is not None
            approval = ApprovalQueue.read(self.approval_queue_file).find(
                approval_id
            )
            return self._pause_result(
                metrics.steps,
                latest_gate,
                metrics,
                permission_decisions,
                approval,
            )

        runtime_feedback = [
            {
                "step": run.state.step,
                "type": observation.kind,
                **observation.payload,
            }
            for run in agent_runs
            for observation in run.state.observations
        ]
        latest_gate, metrics = self._run_gate_with_feedback(
            metrics.steps,
            metrics,
            runtime_feedback,
        )
        failed = (
            workflow_result is None
            or workflow_result.status is not RunStatus.COMPLETED
            or not workflow_result.accepted
        )
        return self._finish_result(
            metrics.steps,
            latest_gate,
            metrics,
            permission_decisions,
            forced_outcome="failed" if failed else None,
        )

    def _workflow_metrics(
        self,
        agent_runs: tuple[AgentRunResult, ...],
        *,
        repair_count: int,
        repair_limit_reached: bool,
        budget_exhausted: bool,
    ) -> RunMetrics:
        metrics = RunMetrics()
        context_chars_max = 0
        for run in agent_runs:
            metrics = add_run_metrics(metrics, run.state.metrics)
            context_chars_max = max(
                context_chars_max,
                run.state.metrics.context_chars_max,
            )
        role_ids = [run.definition_id for run in agent_runs]
        failed_at_limit = any(
            run.state.status is RunStatus.FAILED
            and run.state.step >= 1
            for run in agent_runs
        )
        return replace(
            metrics,
            context_chars_max=context_chars_max,
            role_runs=len(agent_runs),
            planner_runs=role_ids.count("planner"),
            implementer_runs=role_ids.count("implementer"),
            reviewer_runs=role_ids.count("reviewer"),
            review_repairs=repair_count,
            role_cycle_limit_reached=repair_limit_reached,
            max_steps_reached=(
                budget_exhausted or repair_limit_reached or failed_at_limit
            ),
        )

    def _run_single_agent_loop(
        self,
        *,
        run_id: str | None = None,
        backing_store: InMemoryRunStateStore | None = None,
        permission_decisions: list[PermissionDecision] | None = None,
        event_context: RunEventContext | None = None,
        reset_queue: bool = True,
    ) -> RunResult:
        if reset_queue:
            self._reset_approval_queue()
        if run_id is None:
            run_seed = f"{self.root}:{_utc_now_for_runner()}"
            run_id = (
                "run-"
                + hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:12]
            )
        if event_context is None:
            event_context = RunEventContext(run_id, f"agent-{run_id}")
        event_sink = _LegacyRunEventSink(self.trace, self.event_sink)
        state_store = _LegacyRunStateStore(self.trace, backing_store)
        if backing_store is None:
            state_store.create(RunState(run_id))
        initial_step = state_store.get(run_id).step
        if permission_decisions is None:
            permission_decisions = []

        def context_built(state: RunState, built: ContextBuild) -> None:
            metrics = RunMetrics(
                context_chars_max=max(
                    0,
                    len(built.text) - state.metrics.context_chars_max,
                )
            )
            metrics = self._record_retrieval(metrics, built.metadata)
            metrics = self._record_compression(metrics, built.metadata)
            metrics = self._record_isolation(metrics, built.metadata)
            metrics = replace(
                metrics,
                role_contexts=max(
                    0,
                    metrics.role_contexts - state.metrics.role_contexts,
                ),
                isolated_state_keys=max(
                    0,
                    metrics.isolated_state_keys
                    - state.metrics.isolated_state_keys,
                ),
            )
            state_store.add_context_metrics(metrics)
            self.trace.append(
                "context_built",
                {
                    "step": state.step + 1,
                    "strategy": self.context_strategy,
                    "context_chars": len(built.text),
                },
            )

        context_builder = LegacyContextBuilder(
            root=self.root,
            strategy=self.context_strategy,
            policy=self.policy,
            context_budget_chars=self.context_budget_chars,
            retrieval_config=self.retrieval_config,
            compression_config=self.compression_config,
            context_factory=build_context_pack_with_metadata,
            on_build=context_built,
            context_contributors=self.context_contributors,
        )
        hooks = HookBus(event_sink)
        hooks.register_after_tool(
            lambda event: event_sink.emit(
                event.context,
                "ToolCompleted",
                {
                    "action": event.tool_result.action,
                    "ok": event.tool_result.ok,
                    "blocked": event.tool_result.blocked,
                    "code": event.tool_result.code,
                },
                step=event.step,
                phase="tool",
            )
        )
        hooks.register_after_gate(
            lambda event: event_sink.emit(
                event.context,
                "GateCompleted",
                {
                    "passed": event.gate_result.passed,
                    "summary": event.gate_result.summary,
                },
                step=event.step,
                phase="gate",
            )
        )
        pipeline = ActionPipeline(
            _DispatcherRuntime(self.dispatcher),
            hooks,
            _RunnerGovernanceEngine(),
            DefaultValidationPolicy(),
            _RunnerGateRunner(self),
            event_sink=event_sink,
        )
        executor = _RunnerActionExecutor(
            self,
            pipeline,
            event_context,
            permission_decisions,
        )

        def parse_for_legacy(raw: str) -> Action:
            try:
                return parse_action(raw)
            except ActionParseError as exc:
                state_store.remember_parse_error(str(exc))
                raise

        loop = AgentLoop(
            context_builder=context_builder,
            llm=_TracingLLM(self.llm, event_sink),
            parse_action=parse_for_legacy,
            action_executor=executor,
            state_store=state_store,
            stop_policy=_LegacyStopPolicy(initial_step + self.max_steps),
            cancel_token=CallbackCancellationToken(self._check_stop),
            event_sink=event_sink,
            event_context=event_context,
        )
        try:
            state = loop.run(run_id)
        except _LegacyProviderError as exc:
            raise exc.original from exc.original
        return self._run_result_from_state(
            state,
            permission_decisions,
            event_sink,
            event_context,
        )

    def _run_result_from_state(
        self,
        state: RunState,
        permission_decisions: list[PermissionDecision],
        event_sink: RunEventSink,
        event_context: RunEventContext,
    ) -> RunResult:
        metrics = state.metrics
        latest_gate = state.latest_gate
        if state.status is RunStatus.NEEDS_APPROVAL:
            approval_id = state.pending_approval_id
            assert approval_id is not None
            approval = ApprovalQueue.read(self.approval_queue_file).find(approval_id)
            return self._pause_result(
                state.step,
                latest_gate,
                metrics,
                permission_decisions,
                approval,
            )

        if state.status in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}:
            return RunResult(
                passed=False,
                steps=state.step,
                final_gate=latest_gate,
                context_chars_max=metrics.context_chars_max,
                metrics=metrics,
                permission_decisions=permission_decisions,
                trust=TrustSummary("failed", [state.status.value]),
                profile=self.governance_profile,
                outcome=state.status.value,
                run_id=state.run_id,
            )

        if latest_gate is None:
            runtime_feedback = [
                {"step": state.step, "type": item.kind, **item.payload}
                for item in state.observations
            ]
            latest_gate, metrics = self._run_gate_with_feedback(
                max(state.step, self.max_steps),
                metrics,
                runtime_feedback,
            )
            event_sink.emit(
                event_context,
                "GateCompleted",
                {"passed": latest_gate.passed, "summary": latest_gate.summary},
                step=state.step,
                phase="gate",
            )

        if state.status is RunStatus.FAILED and state.step >= self.max_steps:
            metrics = replace(metrics, max_steps_reached=True)
        forced_outcome = (
            None if state.status is RunStatus.COMPLETED else "failed"
        )
        return self._finish_result(
            state.step,
            latest_gate,
            metrics,
            permission_decisions,
            forced_outcome=forced_outcome,
        )

    def _check_stop(self) -> None:
        self._stop_check()

    def _reset_run_artifacts(self) -> None:
        for name in ("retrieval.json", "compression.json", "isolation.json"):
            workspace_fs.write_workspace_text(
                self.run_dir,
                name,
                "{}",
                encoding="utf-8",
            )

    def _reset_approval_queue(self) -> None:
        ApprovalQueue().write(self.approval_queue_file)

    def _evaluate_gate(self) -> GateResult:
        if "index.html" not in self.policy.allowed_read_paths:
            return GateResult(
                False,
                [],
                [],
                "Gate skipped: artifact inspection is not allowed by WorkspacePolicy",
            )
        checklist_path = (
            self.root / "CHECKLIST.md"
            if "CHECKLIST.md" in self.policy.allowed_read_paths
            else None
        )
        return run_html_gate(self.root / "index.html", checklist_path)

    def _run_gate_with_feedback(
        self,
        step: int,
        metrics: RunMetrics,
        runtime_feedback: list[dict],
    ) -> tuple[GateResult, RunMetrics]:
        if "index.html" not in self.policy.allowed_read_paths:
            gate = GateResult(
                False,
                [],
                [],
                "Gate skipped: artifact inspection is not allowed by WorkspacePolicy",
            )
            metrics = replace(
                metrics,
                gate_runs=metrics.gate_runs + 1,
                gate_failures=metrics.gate_failures + 1,
            )
            event = {
                "step": step,
                "type": "gate_result",
                "passed": gate.passed,
                "summary": gate.summary,
            }
            runtime_feedback.append(redact(event))
            self.trace.append(
                "gate_result",
                {"step": step, "passed": gate.passed, "summary": gate.summary},
            )
            return gate, metrics

        checklist_path = (
            self.root / "CHECKLIST.md"
            if "CHECKLIST.md" in self.policy.allowed_read_paths
            else None
        )
        gate = run_html_gate(self.root / "index.html", checklist_path)
        self._check_stop()
        metrics = replace(
            metrics,
            gate_runs=metrics.gate_runs + 1,
            gate_failures=metrics.gate_failures + (0 if gate.passed else 1),
        )
        runtime_feedback.append(
            redact(
                {
                    "step": step,
                    "type": "gate_result",
                    "passed": gate.passed,
                    "summary": gate.summary,
                }
            )
        )
        self.trace.append(
            "gate_result",
            {"step": step, "passed": gate.passed, "summary": gate.summary},
        )
        return gate, metrics

    def _finish_result(
        self,
        step: int,
        final_gate: GateResult,
        metrics: RunMetrics,
        permission_decisions: list[PermissionDecision],
        forced_outcome: str | None = None,
    ) -> RunResult:
        trust = build_trust_summary(final_gate.passed, metrics)
        self.trace.append(
            "run_summary",
            {
                "profile": self.governance_profile,
                "metrics": metrics.to_dict(),
                "trust": trust.to_dict(),
            },
        )
        queue = ApprovalQueue.read(self.approval_queue_file)
        pending_approval = next(
            (
                approval
                for approval in reversed(queue.approvals)
                if approval.status == "pending"
            ),
            None,
        )
        if forced_outcome is not None:
            outcome = forced_outcome
        elif pending_approval is not None:
            outcome = "needs_approval"
        elif final_gate.passed and not metrics.max_steps_reached and not metrics.role_cycle_limit_reached:
            outcome = "completed"
        else:
            outcome = "failed"
        passed = outcome == "completed" and final_gate.passed
        result = RunResult(
            passed,
            step,
            final_gate,
            metrics.context_chars_max,
            metrics,
            permission_decisions,
            trust,
            self.governance_profile,
            outcome,
            pending_approval.id if pending_approval is not None else None,
        )
        append_memory(self.root, result.passed, result.steps, final_gate.summary)
        return result

    def _pause_result(
        self,
        step: int,
        final_gate: GateResult | None,
        metrics: RunMetrics,
        permission_decisions: list[PermissionDecision],
        approval: PendingApproval,
    ) -> RunResult:
        trust = TrustSummary("warning", ["pending_approvals_present"])
        self.trace.append(
            "run_summary",
            {
                "profile": self.governance_profile,
                "outcome": "needs_approval",
                "metrics": metrics.to_dict(),
                "trust": trust.to_dict(),
            },
        )
        return RunResult(
            passed=False,
            steps=step,
            final_gate=final_gate,
            context_chars_max=metrics.context_chars_max,
            metrics=metrics,
            permission_decisions=permission_decisions,
            trust=trust,
            profile=self.governance_profile,
            outcome="needs_approval",
            pending_approval_id=approval.id,
        )

    def _record_tool_feedback(
        self,
        runtime_feedback: list[dict],
        step: int,
        action_name: str,
        ok: bool,
        blocked: bool,
        message: str,
        data: dict,
    ) -> None:
        runtime_feedback.append(
            redact(
                {
                    "step": step,
                    "type": "tool_result",
                    "action": action_name,
                    "ok": ok,
                    "blocked": blocked,
                    "message": message,
                    "data": data,
                }
            )
        )
        self.trace.append(
            "tool_result",
            {
                "step": step,
                "result": {
                    "ok": ok,
                    "action": action_name,
                    "message": message,
                    "data": data,
                    "blocked": blocked,
                },
            },
        )

    def _record_tool_validation_failure(
        self,
        action: Action,
        step: int,
        metrics: RunMetrics,
        runtime_feedback: list[dict],
    ) -> tuple[RunMetrics, bool]:
        failure = self.dispatcher.prepare(action).failure
        if failure is None or failure.code != "tool_validation_failed":
            return metrics, False

        metrics = replace(
            metrics,
            tool_validation_failures=metrics.tool_validation_failures + 1,
        )
        self._record_tool_feedback(
            runtime_feedback,
            step,
            action.action,
            ok=False,
            blocked=True,
            message=failure.message,
            data=failure.data,
        )
        self.trace.append(
            "tool_validation_failed",
            {
                "step": step,
                "action": action.action,
                "code": failure.code,
                "message": failure.message,
            },
        )
        return metrics, True

    def _record_permission_decision(
        self,
        permission_decisions: list[PermissionDecision],
        step: int,
        action_name: str,
        action_path: str | None,
        ok: bool,
        blocked: bool,
        message: str,
        rule_family: str | None = None,
    ) -> None:
        decision = PermissionDecision(
            step=step,
            action=action_name,
            path=action_path,
            allowed=ok and not blocked,
            blocked=blocked,
            reason=message,
            profile=self.governance_profile,
            rule_family=_permission_rule_family(rule_family, message),
        )
        permission_decisions.append(decision)
        self.trace.append("permission_decision", decision.to_dict())

    def _record_retrieval(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
        if not metadata:
            return metrics
        retrieval = metadata.get("retrieval")
        if not isinstance(retrieval, dict):
            return metrics
        selected_chunks = retrieval.get("selected_chunks", [])
        selected_count = len(selected_chunks) if isinstance(selected_chunks, list) else 0
        candidate_count = retrieval.get("candidate_count", 0)
        used_chars = retrieval.get("used_chars", 0)
        metrics = replace(
            metrics,
            retrieval_queries=metrics.retrieval_queries + 1,
            retrieved_chunks=metrics.retrieved_chunks + selected_count,
            retrieval_candidate_chunks=metrics.retrieval_candidate_chunks
            + (candidate_count if isinstance(candidate_count, int) else 0),
            retrieval_context_chars=metrics.retrieval_context_chars
            + (used_chars if isinstance(used_chars, int) else 0),
        )
        workspace_fs.write_workspace_text(
            self.run_dir,
            "retrieval.json",
            json.dumps(retrieval, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.trace.append(
            "retrieval_result",
            {
                "selected_count": selected_count,
                "candidate_count": candidate_count,
                "used_chars": used_chars,
            },
        )
        return metrics

    def _record_compression(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
        if not metadata:
            return metrics
        compression = metadata.get("compression")
        if not isinstance(compression, dict):
            return metrics
        original_chars = compression.get("original_chars", 0)
        compressed_chars = compression.get("compressed_chars", 0)
        cleared_tool_results = compression.get("cleared_tool_results", 0)
        metrics = replace(
            metrics,
            compression_original_chars=metrics.compression_original_chars
            + (original_chars if isinstance(original_chars, int) else 0),
            compression_compressed_chars=metrics.compression_compressed_chars
            + (compressed_chars if isinstance(compressed_chars, int) else 0),
            cleared_tool_results=metrics.cleared_tool_results
            + (cleared_tool_results if isinstance(cleared_tool_results, int) else 0),
        )
        workspace_fs.write_workspace_text(
            self.run_dir,
            "compression.json",
            json.dumps(compression, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.trace.append(
            "compression_result",
            {
                "original_chars": original_chars,
                "compressed_chars": compressed_chars,
                "cleared_tool_results": cleared_tool_results,
            },
        )
        return metrics

    def _record_isolation(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
        if not metadata:
            return metrics
        isolation = metadata.get("isolation")
        if not isinstance(isolation, dict):
            return metrics
        role_contexts = isolation.get("role_contexts", 0)
        isolated_state_keys = isolation.get("isolated_state_keys", 0)
        metrics = replace(
            metrics,
            role_contexts=role_contexts if isinstance(role_contexts, int) else 0,
            isolated_state_keys=isolated_state_keys if isinstance(isolated_state_keys, int) else 0,
        )
        workspace_fs.write_workspace_text(
            self.run_dir,
            "isolation.json",
            json.dumps(isolation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.trace.append(
            "isolation_result",
            {
                "role_contexts": role_contexts,
                "isolated_state_keys": isolated_state_keys,
            },
        )
        return metrics

    def resume_from_approval(self) -> RunResult:
        self._check_stop()
        queue = ApprovalStore(self.approval_queue_file).read_existing()
        approval = queue.next_resume_candidate()
        if approval is None:
            raise ValueError("no approved or denied approval to resume")
        decision_status = "denied" if approval.status == "denied" else "approved"
        loader = _LegacyResumeLoader(self)
        service = AgentService(
            audit_root=self.run_dir,
            workspace_capabilities=frozenset(self.policy.allowed_actions),
            runtime_factory=_ResumeOnlyRuntimeFactory(),
            resume_loader=loader,
        )
        service.resume(
            loader.run_id,
            ApprovalDecision(
                approval.id,
                decision_status,
                queue.revision,
                approval.decision_reason,
            ),
            CallbackCancellationToken(self._check_stop),
        )
        if loader.runtime is None or loader.runtime.last_result is None:
            raise RuntimeError("approval resume did not produce a run result")
        return loader.runtime.last_result


class _ConfiguredRunLoop:
    def __init__(self, runtime: _RunnerRuntime, state_store) -> None:
        self._runtime = runtime
        self._state_store = state_store

    def run(self, run_id: str) -> RunState:
        result = self._runtime.run(run_id=run_id)
        state = self._state_store.get(run_id)
        status = {
            "completed": RunStatus.COMPLETED,
            "needs_approval": RunStatus.NEEDS_APPROVAL,
            "failed": RunStatus.FAILED,
            "cancelled": RunStatus.CANCELLED,
            "timed_out": RunStatus.TIMED_OUT,
        }[result.outcome]
        payload = {
            "passed": result.passed,
            "profile": result.profile,
            "outcome": result.outcome,
            "pending_approval_id": result.pending_approval_id,
            "permission_decisions": [
                item.to_dict() for item in (result.permission_decisions or [])
            ],
            "trust": None if result.trust is None else result.trust.to_dict(),
        }
        return self._state_store.apply(
            run_id,
            state.revision,
            StateDelta(
                status=status,
                step=result.steps,
                append_observations=(Observation("run_result", payload),),
                latest_gate=result.final_gate,
                pending_approval_id=result.pending_approval_id,
                finish_requested=status is RunStatus.COMPLETED,
                metrics=result.metrics or RunMetrics(),
            ),
        )


class _ConfiguredRuntimeFactory:
    def __init__(
        self,
        *,
        root: Path,
        llm: LLMClient,
        policy: WorkspacePolicy,
        audit_dir: Path,
        approval_queue_file: Path,
        runtime_config,
        cancel_token,
        reset_audit: bool = True,
        event_sink: RunEventSink | None = None,
    ) -> None:
        self.cancel_token = cancel_token
        self.runtime = _RunnerRuntime(
            root,
            llm,
            policy,
            max_steps=runtime_config.max_steps,
            context_strategy=runtime_config.context_strategy,
            governance_profile=runtime_config.governance_profile,
            audit_dir=audit_dir,
            approval_queue_file=approval_queue_file,
            stop_check=cancel_token.check,
            context_budget_chars=runtime_config.context_budget_chars,
            retrieval_config=RetrievalConfig(
                top_k=runtime_config.retrieval_top_k,
                budget_chars=runtime_config.retrieval_budget_chars,
            ),
            compression_config=CompressionConfig(
                max_tool_result_chars=(
                    runtime_config.compression_max_tool_result_chars
                )
            ),
            reset_audit=reset_audit,
            event_sink=event_sink,
        )

    @classmethod
    def from_runtime(cls, runtime: _RunnerRuntime, cancel_token):
        factory = cls.__new__(cls)
        factory.cancel_token = cancel_token
        factory.runtime = runtime
        return factory

    def create(
        self,
        request,
        *,
        state_store,
        skill_session,
        event_context,
    ) -> _ConfiguredRunLoop:
        del request, skill_session, event_context
        return _ConfiguredRunLoop(self.runtime, state_store)


def _service_for_configured_runtime(
    runtime: _RunnerRuntime,
    runtime_config,
    cancel_token,
    id_factory: Callable[[], str] | None = None,
) -> AgentService:
    workspace_fs.ensure_workspace_directory(runtime.run_dir, "agent-state")
    runtime_factory = _ConfiguredRuntimeFactory.from_runtime(
        runtime,
        cancel_token,
    )
    definition = AgentDefinition(
        agent_id="default-agent",
        instructions="Execute the configured workspace task.",
        capability_set=frozenset(runtime.policy.allowed_actions),
        context_policy=runtime_config.context_strategy,
        budget=AgentBudget(
            max_steps=runtime_config.max_steps,
            context_chars=runtime_config.context_budget_chars,
            child_runs=0,
        ),
    )
    service = AgentService(
        audit_root=runtime.run_dir / "agent-state",
        workspace_capabilities=frozenset(runtime.policy.allowed_actions),
        runtime_factory=runtime_factory,
        id_factory=id_factory,
    )
    service._specgate_runtime_factory = runtime_factory
    service._specgate_default_definition = definition
    service._specgate_cancel_token = cancel_token
    return service


def _configured_runtime(service: AgentService) -> _RunnerRuntime:
    factory = getattr(service, "_specgate_runtime_factory", None)
    if not isinstance(factory, _ConfiguredRuntimeFactory):
        raise TypeError("AgentService is not configured for the Runner facade")
    return factory.runtime


def configure_agent_service(
    service: AgentService,
    *,
    governance_config: GovernanceConfig | None = None,
    retrieval_config: RetrievalConfig | None = None,
    compression_config: CompressionConfig | None = None,
) -> AgentService:
    runtime = _configured_runtime(service)
    if governance_config is not None:
        runtime.governance_config = governance_config
    if retrieval_config is not None:
        runtime.retrieval_config = retrieval_config
    if compression_config is not None:
        runtime.compression_config = compression_config
    return service


def _trust_from_payload(payload: object) -> TrustSummary | None:
    if not isinstance(payload, dict):
        return None
    return TrustSummary(
        str(payload.get("status", "failed")),
        list(payload.get("reasons", [])),
    )


def _request_summary(task: str) -> str:
    single_line = " ".join(task.split())
    return str(redact(single_line[:160]))


def _run_configured_service(
    service: AgentService,
    task: str | None = None,
) -> RunResult:
    definition = getattr(service, "_specgate_default_definition", None)
    token = getattr(service, "_specgate_cancel_token", None)
    if definition is None or token is None:
        raise TypeError("AgentService is missing its default run configuration")
    resolved_task = DEFAULT_AGENT_TASK if task is None else task
    runtime = _configured_runtime(service)
    runtime.context_contributors = (
        () if task is None else (UserRequestContextContributor(task),)
    )
    if task is not None:
        runtime.trace.append(
            "user_request_received",
            {
                "summary": _request_summary(task),
                "request_chars": len(task),
            },
        )
    result = service.run(definition, resolved_task, cancel_token=token)
    payload = next(
        item.payload
        for item in reversed(result.state.observations)
        if item.kind == "run_result"
    )
    decisions = [
        PermissionDecision(**item)
        for item in payload.get("permission_decisions", [])
    ]
    outcome = str(payload.get("outcome", result.state.status.value))
    return RunResult(
        passed=bool(payload.get("passed", False)),
        steps=result.state.step,
        final_gate=result.state.latest_gate,
        context_chars_max=result.state.metrics.context_chars_max,
        metrics=result.state.metrics,
        permission_decisions=decisions,
        trust=_trust_from_payload(payload.get("trust")),
        profile=str(payload.get("profile", "strict")),
        outcome=outcome,
        pending_approval_id=result.state.pending_approval_id,
        run_id=result.run_id,
    )


def _resume_configured_service(service: AgentService) -> RunResult:
    return _configured_runtime(service).resume_from_approval()


class AgentRunner:
    """Backward-compatible facade over the configured Agent runtime."""

    def __init__(
        self,
        root: Path | None = None,
        llm: LLMClient | None = None,
        policy: WorkspacePolicy | None = None,
        max_steps: int = 5,
        context_strategy: str = "baseline",
        governance_profile: str | None = None,
        governance_config: GovernanceConfig | None = None,
        audit_dir: Path | None = None,
        approval_queue_file: Path | None = None,
        reset_audit: bool = True,
        stop_check: Callable[[], None] | None = None,
        context_budget_chars: int = 12000,
        retrieval_config: RetrievalConfig | None = None,
        compression_config: CompressionConfig | None = None,
        agent_service: AgentService | None = None,
        id_factory: Callable[[], str] | None = None,
        event_sink: RunEventSink | None = None,
    ) -> None:
        if agent_service is None:
            if root is None or llm is None or policy is None:
                raise TypeError("root, llm, and policy are required")
            from specgate.agent_service import build_agent_service
            from specgate.runtime_config import RunRuntimeConfig

            profile = governance_profile or (
                governance_config.profile if governance_config is not None else "strict"
            )
            resolved_audit = audit_dir or root / "runs" / "latest"
            resolved_approval = approval_queue_file or approval_queue_path(root)
            token = CallbackCancellationToken(stop_check or (lambda: None))
            retrieval = retrieval_config or RetrievalConfig()
            compression = compression_config or CompressionConfig()
            runtime_config = RunRuntimeConfig(
                governance_profile=profile,
                context_strategy=context_strategy,
                max_steps=max_steps,
                context_budget_chars=context_budget_chars,
                retrieval_top_k=retrieval.top_k,
                retrieval_budget_chars=retrieval.budget_chars,
                compression_max_tool_result_chars=compression.max_tool_result_chars,
            )
            if reset_audit:
                agent_service = build_agent_service(
                    root=root,
                    llm=llm,
                    policy=policy,
                    audit_dir=resolved_audit,
                    approval_queue_file=resolved_approval,
                    runtime_config=runtime_config,
                    cancel_token=token,
                    id_factory=id_factory,
                    event_sink=event_sink,
                )
                runtime = _configured_runtime(agent_service)
                runtime.retrieval_config = retrieval
                runtime.compression_config = compression
                if governance_config is not None:
                    runtime.governance_config = governance_config
            else:
                runtime = _RunnerRuntime(
                    root,
                    llm,
                    policy,
                    max_steps=max_steps,
                    context_strategy=context_strategy,
                    governance_profile=governance_profile,
                    governance_config=governance_config,
                    audit_dir=resolved_audit,
                    approval_queue_file=resolved_approval,
                    reset_audit=False,
                    stop_check=stop_check,
                    context_budget_chars=context_budget_chars,
                    retrieval_config=retrieval,
                    compression_config=compression,
                    event_sink=event_sink,
                )
                agent_service = _service_for_configured_runtime(
                    runtime,
                    runtime_config,
                    token,
                    id_factory,
                )
        object.__setattr__(self, "_service", agent_service)

    def run(self, task: str | None = None) -> RunResult:
        return _run_configured_service(self._service, task)

    def resume_from_approval(self) -> RunResult:
        return _resume_configured_service(self._service)

    def __getattr__(self, name: str):
        return getattr(_configured_runtime(self._service), name)

    def __setattr__(self, name: str, value) -> None:
        service = self.__dict__.get("_service")
        runtime = None if service is None else _configured_runtime(service)
        if runtime is not None and hasattr(runtime, name):
            setattr(runtime, name, value)
            return
        object.__setattr__(self, name, value)



def _target_matches_approved_content(root: Path, action: Action) -> bool:
    if action.action not in {"write_file", "replace_file"}:
        return False
    path = action.args.get("path")
    content = action.args.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
        return False
    try:
        current = capture_target_state(root, path)
    except (OSError, ValueError):
        return False
    if current is None:
        return False
    return current == {
        "path": current["path"],
        "exists": True,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
