from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from threading import Lock
from typing import Any, Protocol

from specgate.gate import GateResult
from specgate.metrics import RunMetrics, add_run_metrics


class RunStatus(str, Enum):
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Observation:
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunState:
    run_id: str
    revision: int = 0
    status: RunStatus = RunStatus.RUNNING
    step: int = 0
    observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    finish_requested: bool = False
    metrics: RunMetrics = field(default_factory=RunMetrics)


@dataclass(frozen=True)
class StateDelta:
    status: RunStatus | None = None
    step: int | None = None
    append_observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    clear_pending_approval: bool = False
    finish_requested: bool | None = None
    metrics: RunMetrics = field(default_factory=RunMetrics)


class RunStateConflict(RuntimeError):
    pass


class RunStateStore(Protocol):
    def create(self, state: RunState) -> RunState: ...

    def get(self, run_id: str) -> RunState: ...

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState: ...


class InMemoryRunStateStore:
    def __init__(self) -> None:
        self._states: dict[str, RunState] = {}
        self._lock = Lock()

    def create(self, state: RunState) -> RunState:
        with self._lock:
            if state.run_id in self._states:
                raise RunStateConflict(f"run already exists: {state.run_id}")
            owned = deepcopy(state)
            self._states[state.run_id] = owned
            return deepcopy(owned)

    def get(self, run_id: str) -> RunState:
        with self._lock:
            return deepcopy(self._states[run_id])

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState:
        with self._lock:
            current = self._states[run_id]
            if current.revision != expected_revision:
                raise RunStateConflict(
                    "stale run state: "
                    f"expected {expected_revision}, actual {current.revision}"
                )
            updated = replace(
                current,
                revision=current.revision + 1,
                status=current.status if delta.status is None else delta.status,
                step=current.step if delta.step is None else delta.step,
                observations=current.observations + delta.append_observations,
                latest_gate=(
                    current.latest_gate
                    if delta.latest_gate is None
                    else delta.latest_gate
                ),
                pending_approval_id=(
                    None
                    if delta.clear_pending_approval
                    else (
                        current.pending_approval_id
                        if delta.pending_approval_id is None
                        else delta.pending_approval_id
                    )
                ),
                finish_requested=(
                    current.finish_requested
                    if delta.finish_requested is None
                    else delta.finish_requested
                ),
                metrics=add_run_metrics(current.metrics, delta.metrics),
            )
            owned = deepcopy(updated)
            self._states[run_id] = owned
            return deepcopy(owned)
