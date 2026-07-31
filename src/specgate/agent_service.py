from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock
from typing import Protocol
from uuid import uuid4

import specgate.workspace_fs as workspace_fs
from specgate.action_pipeline import ExecutionOutcome, ExecutionStatus
from specgate.actions import Action, parse_action
from specgate.approvals import (
    ApprovalDecision,
    ApprovalGrant,
    ApprovalStore,
    PendingApproval,
    approval_action_digest,
    target_state_matches,
)
from specgate.metrics import RunMetrics, add_run_metrics
from specgate.run_control import CancellationToken
from specgate.run_state import (
    FileRunStateStore,
    Observation,
    RunState,
    RunStateStore,
    RunStatus,
    StateDelta,
)
from specgate.runtime_events import RunEventContext
from specgate.skill_registry import SkillSession


CapabilitySet = frozenset[str]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DelegationDenied(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentBudget:
    max_steps: int
    context_chars: int
    child_runs: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_steps, "max_steps")
        _require_positive_int(self.context_chars, "context_chars")
        _require_non_negative_int(self.child_runs, "child_runs")


@dataclass(frozen=True)
class DelegationPolicy:
    max_depth: int
    max_children: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_depth, "max_depth")
        _require_positive_int(self.max_children, "max_children")


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    instructions: str
    capability_set: CapabilitySet
    context_policy: str
    budget: AgentBudget
    delegation_policy: DelegationPolicy | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.agent_id, "agent_id")
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be a non-empty string")
        if type(self.capability_set) is not frozenset:
            raise TypeError("capability_set must be a frozenset")
        if not all(isinstance(item, str) and item for item in self.capability_set):
            raise ValueError("capability_set entries must be non-empty strings")
        if not isinstance(self.context_policy, str) or not self.context_policy:
            raise ValueError("context_policy must be a non-empty string")


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    agent_run_id: str
    definition: AgentDefinition
    task: str
    parent_run_id: str | None
    effective_capabilities: CapabilitySet
    budget: AgentBudget
    cancel_token: CancellationToken


@dataclass(frozen=True)
class AgentRunResult:
    run_id: str
    agent_run_id: str
    parent_run_id: str | None
    definition_id: str
    effective_capabilities: CapabilitySet
    active_skills: tuple[str, ...]
    state: RunState


class AgentRunLoop(Protocol):
    def run(self, run_id: str) -> RunState: ...


class AgentApprovalRuntime(Protocol):
    approval_root: Path
    approval_store: ApprovalStore

    def execute_approval(
        self,
        action: Action,
        state: RunState,
        approval: PendingApproval,
        grant: ApprovalGrant,
        cancel_token: CancellationToken,
    ) -> ExecutionOutcome: ...


class AgentRuntimeFactory(Protocol):
    def create(
        self,
        request: AgentRunRequest,
        *,
        state_store: RunStateStore,
        skill_session: SkillSession,
        event_context: RunEventContext,
    ) -> AgentRunLoop: ...


@dataclass(frozen=True)
class AgentResumeHandle:
    run_id: str
    agent_run_id: str
    parent_run_id: str | None
    definition: AgentDefinition
    effective_capabilities: CapabilitySet
    skill_session: SkillSession
    state_store: RunStateStore
    runtime: AgentRunLoop

    def __post_init__(self) -> None:
        _require_safe_id(self.run_id, "run_id")
        _require_safe_id(self.agent_run_id, "agent_run_id")
        if self.parent_run_id is not None:
            _require_safe_id(self.parent_run_id, "parent_run_id")
        if type(self.effective_capabilities) is not frozenset:
            raise TypeError("effective_capabilities must be a frozenset")


class AgentResumeLoader(Protocol):
    def load(
        self,
        run_id: str,
        cancel_token: CancellationToken,
    ) -> AgentResumeHandle: ...


@dataclass(frozen=True)
class _NeverCancelledToken:
    def check(self) -> None:
        return None

    def remaining_seconds(self) -> float:
        return float("inf")


@dataclass
class _RunRecord:
    run_id: str
    agent_run_id: str
    parent_run_id: str | None
    definition: AgentDefinition
    effective_capabilities: CapabilitySet
    depth: int
    max_depth: int
    child_count: int
    skill_session: SkillSession
    state_store: RunStateStore
    loop: AgentRunLoop


class AgentService:
    def __init__(
        self,
        *,
        audit_root: Path,
        workspace_capabilities: CapabilitySet,
        runtime_factory: AgentRuntimeFactory,
        id_factory: Callable[[], str] | None = None,
        state_store_factory: Callable[[Path], RunStateStore] = FileRunStateStore,
        resume_loader: AgentResumeLoader | None = None,
    ) -> None:
        if type(workspace_capabilities) is not frozenset:
            raise TypeError("workspace_capabilities must be a frozenset")
        self._audit_root = Path(audit_root)
        self._workspace_capabilities = workspace_capabilities
        self._runtime_factory = runtime_factory
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._state_store_factory = state_store_factory
        self._resume_loader = resume_loader
        self._records: dict[str, _RunRecord] = {}
        self._lock = Lock()

    def run(
        self,
        definition: AgentDefinition,
        task: str,
        parent_run_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> AgentRunResult:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        return self._run_new_agent(
            definition,
            task,
            parent_run_id,
            cancel_token,
        )

    def resume(
        self,
        run_id: str,
        decision: ApprovalDecision,
        cancel_token: CancellationToken | None = None,
    ) -> AgentRunResult:
        return self._resume_agent(run_id, decision, cancel_token)

    def _run_new_agent(
        self,
        definition: AgentDefinition,
        task: str,
        parent_run_id: str | None,
        cancel_token: CancellationToken | None,
    ) -> AgentRunResult:
        with self._lock:
            effective, depth, max_depth = self._resolve_run_scope(
                definition,
                parent_run_id,
            )
            run_id = self._id_factory()
            _require_safe_id(run_id, "run_id")
            if run_id in self._records:
                raise RuntimeError("duplicate run identity")
            agent_run_id = f"{definition.agent_id}-{run_id}"

        workspace_fs.ensure_workspace_directory(self._audit_root, run_id)
        run_root = self._audit_root / run_id
        state_store = self._state_store_factory(run_root)
        state_store.create(RunState(run_id))
        skill_session = SkillSession(agent_run_id=agent_run_id)
        resolved_token = cancel_token or _NeverCancelledToken()
        request = AgentRunRequest(
            run_id=run_id,
            agent_run_id=agent_run_id,
            definition=definition,
            task=task,
            parent_run_id=parent_run_id,
            effective_capabilities=effective,
            budget=definition.budget,
            cancel_token=resolved_token,
        )
        event_context = RunEventContext(
            run_id,
            agent_run_id,
            parent_run_id,
        )
        loop = self._runtime_factory.create(
            request,
            state_store=state_store,
            skill_session=skill_session,
            event_context=event_context,
        )
        record = _RunRecord(
            run_id=run_id,
            agent_run_id=agent_run_id,
            parent_run_id=parent_run_id,
            definition=definition,
            effective_capabilities=effective,
            depth=depth,
            max_depth=max_depth,
            child_count=0,
            skill_session=skill_session,
            state_store=state_store,
            loop=loop,
        )
        with self._lock:
            if run_id in self._records:
                raise RuntimeError("duplicate run identity")
            self._records[run_id] = record

        state = loop.run(run_id)
        return self._result(record, state)

    def _resume_agent(
        self,
        run_id: str,
        decision: ApprovalDecision,
        cancel_token: CancellationToken | None,
    ) -> AgentRunResult:
        token = cancel_token or _NeverCancelledToken()
        token.check()
        record = self._record_for_resume(run_id, token)
        state = record.state_store.get(run_id)
        if (
            state.status is not RunStatus.NEEDS_APPROVAL
            or state.pending_approval_id != decision.approval_id
        ):
            raise ValueError("run is not waiting for this approval")

        runtime = _approval_runtime(record.loop)
        queue = runtime.approval_store.read_existing()
        approval = queue.find(decision.approval_id)
        _emit_resume_event(
            runtime,
            "RunResumed",
            {
                "approval_id": approval.id,
                "status": approval.status,
                "action": approval.action,
                "path": approval.path,
                "queue_revision": queue.revision,
            },
        )
        if approval.status == "pending":
            queue = runtime.approval_store.decide(
                approval.id,
                decision.status,
                expected_revision=decision.expected_revision,
                decided_at=_utc_now(),
                reason=decision.reason,
            )
            approval = queue.find(approval.id)
        elif (
            (
                approval.status == decision.status
                or (
                    approval.status == "applying"
                    and decision.status == "approved"
                )
            )
            and queue.revision == decision.expected_revision
        ):
            pass
        else:
            runtime.approval_store.decide(
                approval.id,
                decision.status,
                expected_revision=decision.expected_revision,
                decided_at=_utc_now(),
                reason=decision.reason,
            )
            raise AssertionError("unreachable approval decision")

        if decision.status == "denied":
            queue = runtime.approval_store.transition(
                approval.id,
                "rejected",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
                reason=decision.reason or approval.decision_reason or "human denied",
            )
            _emit_resume_event(
                runtime,
                "ApprovalDenied",
                {
                    "approval_id": approval.id,
                    "action": approval.action,
                    "path": approval.path,
                    "reason": decision.reason
                    or approval.decision_reason
                    or "human denied",
                    "status": "rejected",
                    "queue_revision": queue.revision,
                },
            )
            updated = self._apply_resolution(
                record,
                state,
                StateDelta(
                    append_observations=(
                        Observation(
                            "approval_denied",
                            {"approval_id": approval.id, "code": "approval_denied"},
                        ),
                    ),
                    metrics=RunMetrics(denied_approvals=1),
                ),
            )
            return self._result(record, record.loop.run(updated.run_id))

        target_matches = target_state_matches(
            runtime.approval_root,
            approval.target_state,
        )
        if (
            approval.status == "applying"
            and not target_matches
            and _approval_already_applied(runtime, approval)
        ):
            queue = runtime.approval_store.transition(
                approval.id,
                "applied",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
            )
            _emit_resume_event(
                runtime,
                "ApprovalApplied",
                {
                    "approval_id": approval.id,
                    "action": approval.action,
                    "path": approval.path,
                    "recovered_without_reapply": True,
                    "status": "applied",
                    "queue_revision": queue.revision,
                },
            )
            updated = self._apply_resolution(
                record,
                state,
                StateDelta(
                    append_observations=(
                        Observation(
                            "approval_applied",
                            {
                                "approval_id": approval.id,
                                "code": "approval_already_applied",
                            },
                        ),
                    ),
                    metrics=RunMetrics(
                        approved_approvals=1,
                        applied_approvals=1,
                    ),
                ),
            )
            return self._result(record, record.loop.run(updated.run_id))

        if not target_matches:
            reason = "approval_target_changed"
            queue = runtime.approval_store.transition(
                approval.id,
                "failed",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
                reason=reason,
            )
            _emit_resume_event(
                runtime,
                "ApprovalFailed",
                {
                    "approval_id": approval.id,
                    "action": approval.action,
                    "path": approval.path,
                    "code": reason,
                    "status": "failed",
                    "queue_revision": queue.revision,
                },
            )
            updated = self._apply_resolution(
                record,
                state,
                StateDelta(
                    append_observations=(
                        Observation(
                            "approval_failed",
                            {"approval_id": approval.id, "code": reason},
                        ),
                    ),
                    metrics=RunMetrics(
                        approved_approvals=1,
                        failed_approvals=1,
                        blocked_actions=1,
                    ),
                ),
            )
            return self._result(record, record.loop.run(updated.run_id))

        action = _approval_action(approval)
        if approval.status == "approved":
            queue = runtime.approval_store.transition(
                approval.id,
                "applying",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
            )
            approval = queue.find(approval.id)
            _emit_resume_event(
                runtime,
                "ApprovalClaimed",
                {
                    "approval_id": approval.id,
                    "status": approval.status,
                    "queue_revision": queue.revision,
                },
            )
        grant = ApprovalGrant(
            approval.id,
            approval_action_digest(approval.action_payload),
            queue.revision,
        )
        token.check()
        try:
            outcome = runtime.execute_approval(
                action,
                state,
                approval,
                grant,
                token,
            )
        except Exception:
            runtime.approval_store.transition(
                approval.id,
                "failed",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
                reason="approval_execution_failed",
            )
            record.state_store.apply(
                run_id,
                state.revision,
                StateDelta(
                    status=RunStatus.FAILED,
                    clear_pending_approval=True,
                    append_observations=(
                        Observation(
                            "approval_failed",
                            {
                                "approval_id": approval.id,
                                "code": "approval_execution_failed",
                            },
                        ),
                    ),
                ),
            )
            raise

        if outcome.status is ExecutionStatus.APPROVAL_REQUIRED:
            next_approval = outcome.approval_request
            if next_approval is None or next_approval.id == approval.id:
                raise RuntimeError("approval revalidation did not create a new request")
            queue = runtime.approval_store.read_existing()
            queue = runtime.approval_store.transition(
                approval.id,
                "failed",
                expected_revision=queue.revision,
                resolved_at=_utc_now(),
                reason="approval_revalidation_required",
            )
            _emit_resume_event(
                runtime,
                "ApprovalFailed",
                {
                    "approval_id": approval.id,
                    "action": approval.action,
                    "path": approval.path,
                    "status": "failed",
                    "code": "approval_revalidation_required",
                    "queue_revision": queue.revision,
                },
            )
            updated = record.state_store.apply(
                run_id,
                state.revision,
                replace(
                    outcome.state_delta,
                    metrics=add_run_metrics(
                        outcome.state_delta.metrics,
                        RunMetrics(
                            approved_approvals=1,
                            failed_approvals=1,
                        ),
                    ),
                ),
            )
            return self._result(record, record.loop.run(updated.run_id))

        terminal = (
            "applied"
            if outcome.status is ExecutionStatus.SUCCEEDED
            else "failed"
        )
        queue = runtime.approval_store.transition(
            approval.id,
            terminal,
            expected_revision=queue.revision,
            resolved_at=_utc_now(),
            reason=(
                None
                if terminal == "applied"
                else _outcome_error_code(outcome)
            ),
        )
        _emit_resume_event(
            runtime,
            "ApprovalApplied" if terminal == "applied" else "ApprovalFailed",
            {
                "approval_id": approval.id,
                "action": approval.action,
                "path": approval.path,
                "status": terminal,
                "code": None if terminal == "applied" else _outcome_error_code(outcome),
                "queue_revision": queue.revision,
            },
        )
        approval_metrics = RunMetrics(
            approved_approvals=1,
            applied_approvals=1 if terminal == "applied" else 0,
            failed_approvals=1 if terminal == "failed" else 0,
        )
        updated = self._apply_resolution(
            record,
            state,
            replace(
                outcome.state_delta,
                metrics=add_run_metrics(
                    outcome.state_delta.metrics,
                    approval_metrics,
                ),
            ),
        )
        return self._result(record, record.loop.run(updated.run_id))

    def _record_for_resume(
        self,
        run_id: str,
        cancel_token: CancellationToken,
    ) -> _RunRecord:
        with self._lock:
            existing = self._records.get(run_id)
        if existing is not None:
            return existing
        if self._resume_loader is None:
            raise ValueError("run is not available for resume")
        handle = self._resume_loader.load(run_id, cancel_token)
        if handle.run_id != run_id:
            raise ValueError("resume loader returned a different run")
        if not handle.effective_capabilities <= self._workspace_capabilities:
            raise ValueError("resume handle exceeds workspace capabilities")
        policy = handle.definition.delegation_policy
        record = _RunRecord(
            run_id=handle.run_id,
            agent_run_id=handle.agent_run_id,
            parent_run_id=handle.parent_run_id,
            definition=handle.definition,
            effective_capabilities=handle.effective_capabilities,
            depth=0,
            max_depth=0 if policy is None else policy.max_depth,
            child_count=0,
            skill_session=handle.skill_session,
            state_store=handle.state_store,
            loop=handle.runtime,
        )
        with self._lock:
            return self._records.setdefault(run_id, record)

    def _apply_resolution(
        self,
        record: _RunRecord,
        state: RunState,
        delta: StateDelta,
    ) -> RunState:
        return record.state_store.apply(
            record.run_id,
            state.revision,
            replace(
                delta,
                status=RunStatus.RUNNING,
                clear_pending_approval=True,
            ),
        )

    def _result(self, record: _RunRecord, state: RunState) -> AgentRunResult:
        return AgentRunResult(
            run_id=record.run_id,
            agent_run_id=record.agent_run_id,
            parent_run_id=record.parent_run_id,
            definition_id=record.definition.agent_id,
            effective_capabilities=record.effective_capabilities,
            active_skills=record.skill_session.active_names,
            state=state,
        )

    def _resolve_run_scope(
        self,
        definition: AgentDefinition,
        parent_run_id: str | None,
    ) -> tuple[CapabilitySet, int, int]:
        if parent_run_id is None:
            policy = definition.delegation_policy
            max_depth = 0 if policy is None else policy.max_depth
            return (
                definition.capability_set & self._workspace_capabilities,
                0,
                max_depth,
            )

        try:
            parent = self._records[parent_run_id]
        except KeyError as exc:
            raise DelegationDenied("parent run is not available") from exc
        policy = parent.definition.delegation_policy
        if policy is None:
            raise DelegationDenied("parent agent does not allow delegation")
        depth = parent.depth + 1
        if depth > parent.max_depth:
            raise DelegationDenied("delegation depth exceeded")
        if parent.child_count >= policy.max_children:
            raise DelegationDenied("delegation child limit exceeded")
        if parent.child_count >= parent.definition.budget.child_runs:
            raise BudgetExceeded("child run budget exhausted")
        _require_budget_within(definition.budget, parent.definition.budget)
        parent.child_count += 1
        child_policy = definition.delegation_policy
        child_max_depth = parent.max_depth
        if child_policy is not None:
            child_max_depth = min(
                child_max_depth,
                depth + child_policy.max_depth,
            )
        return (
            effective_child_capabilities(
                child=definition.capability_set,
                parent=parent.effective_capabilities,
                workspace=self._workspace_capabilities,
            ),
            depth,
            child_max_depth,
        )


def effective_child_capabilities(
    *,
    child: CapabilitySet,
    parent: CapabilitySet,
    workspace: CapabilitySet,
) -> CapabilitySet:
    return child & parent & workspace


def _approval_runtime(loop: AgentRunLoop) -> AgentApprovalRuntime:
    if (
        not isinstance(getattr(loop, "approval_root", None), Path)
        or not isinstance(getattr(loop, "approval_store", None), ApprovalStore)
        or not callable(getattr(loop, "execute_approval", None))
    ):
        raise RuntimeError("run runtime does not support approval resume")
    return loop  # type: ignore[return-value]


def _approval_action(approval: PendingApproval) -> Action:
    return parse_action(
        json.dumps(approval.action_payload, ensure_ascii=False)
    )


def _outcome_error_code(outcome: ExecutionOutcome) -> str:
    if outcome.error is not None and outcome.error.code:
        return outcome.error.code
    return "approval_execution_failed"


def _approval_already_applied(
    runtime: AgentApprovalRuntime,
    approval: PendingApproval,
) -> bool:
    checker = getattr(runtime, "approval_already_applied", None)
    return bool(callable(checker) and checker(approval))


def _emit_resume_event(
    runtime: AgentApprovalRuntime,
    event_type: str,
    payload: dict[str, object],
) -> None:
    emitter = getattr(runtime, "emit_resume_event", None)
    if callable(emitter):
        emitter(event_type, payload)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_budget_within(requested: AgentBudget, reserved: AgentBudget) -> None:
    if (
        requested.max_steps > reserved.max_steps
        or requested.context_chars > reserved.context_chars
        or requested.child_runs > reserved.child_runs
    ):
        raise BudgetExceeded("child budget exceeds parent reservation")


def _require_safe_id(value: str, label: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe non-empty identifier")


def _require_positive_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def _require_non_negative_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
