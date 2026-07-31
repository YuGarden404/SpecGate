from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
from threading import Lock
from typing import Protocol
from uuid import uuid4

import specgate.workspace_fs as workspace_fs
from specgate.run_control import CancellationToken
from specgate.run_state import FileRunStateStore, RunState, RunStateStore
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
class _NeverCancelledToken:
    def check(self) -> None:
        return None

    def remaining_seconds(self) -> float:
        return float("inf")


@dataclass
class _RunRecord:
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
    ) -> None:
        if type(workspace_capabilities) is not frozenset:
            raise TypeError("workspace_capabilities must be a frozenset")
        self._audit_root = Path(audit_root)
        self._workspace_capabilities = workspace_capabilities
        self._runtime_factory = runtime_factory
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._state_store_factory = state_store_factory
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
        return AgentRunResult(
            run_id=run_id,
            agent_run_id=agent_run_id,
            parent_run_id=parent_run_id,
            definition_id=definition.agent_id,
            effective_capabilities=effective,
            active_skills=skill_session.active_names,
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
