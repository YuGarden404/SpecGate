from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from specgate.agent_service import (
    AgentBudget,
    AgentDefinition,
    AgentRunResult,
    BudgetExceeded,
)
from specgate.artifacts import (
    AgentArtifactValidationError,
    Artifact,
    ImplementationArtifact,
    NonEmptyString,
    PlanArtifact,
    ReviewArtifact,
    parse_agent_artifact,
)
from specgate.run_control import CancellationToken
from specgate.run_state import RunStatus


class BudgetReservationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowBudgetBalance:
    max_steps: int
    context_chars: int
    child_runs: int


class WorkflowBudget:
    def __init__(self, total: AgentBudget) -> None:
        if not isinstance(total, AgentBudget):
            raise TypeError("total must be an AgentBudget")
        self._max_steps = total.max_steps
        self._context_chars = total.context_chars
        self._child_runs = total.child_runs
        self._lock = Lock()

    @property
    def remaining(self) -> WorkflowBudgetBalance:
        with self._lock:
            return WorkflowBudgetBalance(
                self._max_steps,
                self._context_chars,
                self._child_runs,
            )

    def reserve(self, requested: AgentBudget) -> BudgetReservation:
        if not isinstance(requested, AgentBudget):
            raise TypeError("requested must be an AgentBudget")
        with self._lock:
            if (
                requested.max_steps > self._max_steps
                or requested.context_chars > self._context_chars
                or requested.child_runs > self._child_runs
            ):
                raise BudgetExceeded("workflow budget exhausted")
            self._max_steps -= requested.max_steps
            self._context_chars -= requested.context_chars
            self._child_runs -= requested.child_runs
            return BudgetReservation(self, requested)

    def _release(
        self,
        reservation: BudgetReservation,
        used: AgentBudget,
    ) -> None:
        if not isinstance(used, AgentBudget):
            raise TypeError("used must be an AgentBudget")
        with self._lock:
            if reservation._released:
                raise BudgetReservationError("budget reservation already released")
            requested = reservation.requested
            if (
                used.max_steps > requested.max_steps
                or used.context_chars > requested.context_chars
                or used.child_runs > requested.child_runs
            ):
                raise BudgetReservationError(
                    "used budget exceeds the reservation"
                )
            self._max_steps += requested.max_steps - used.max_steps
            self._context_chars += requested.context_chars - used.context_chars
            self._child_runs += requested.child_runs - used.child_runs
            reservation._released = True


class BudgetReservation:
    def __init__(
        self,
        budget: WorkflowBudget,
        requested: AgentBudget,
    ) -> None:
        self._budget = budget
        self.requested = requested
        self._released = False

    def release(self, used: AgentBudget) -> None:
        self._budget._release(self, used)


class WorkflowTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    role: Literal["planner", "implementer", "reviewer"]
    task: NonEmptyString
    artifacts: tuple[Artifact, ...] = ()


class AgentServiceRuntime(Protocol):
    def run(
        self,
        definition: AgentDefinition,
        task: str,
        parent_run_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> AgentRunResult: ...


@dataclass(frozen=True)
class SequentialReviewResult:
    status: RunStatus
    plan: PlanArtifact | None = None
    implementations: tuple[ImplementationArtifact, ...] = ()
    reviews: tuple[ReviewArtifact, ...] = ()
    agent_runs: tuple[AgentRunResult, ...] = ()
    repair_count: int = 0
    repair_limit_reached: bool = False

    @property
    def accepted(self) -> bool:
        return bool(
            self.status is RunStatus.COMPLETED
            and self.reviews
            and self.reviews[-1].accepted
            and not self.reviews[-1].repair_required
        )


class SequentialReviewWorkflow:
    def __init__(
        self,
        *,
        agent_service: AgentServiceRuntime,
        planner: AgentDefinition,
        implementer: AgentDefinition,
        reviewer: AgentDefinition,
        budget: WorkflowBudget,
        cancel_token: CancellationToken,
    ) -> None:
        self._agent_service = agent_service
        self._planner = planner
        self._implementer = implementer
        self._reviewer = reviewer
        self._budget = budget
        self._cancel_token = cancel_token

    def run(self, task: str) -> SequentialReviewResult:
        plan: PlanArtifact | None = None
        implementations: list[ImplementationArtifact] = []
        reviews: list[ReviewArtifact] = []
        runs: list[AgentRunResult] = []

        planner_run = self._run_agent(self._planner, "planner", task, ())
        runs.append(planner_run)
        if planner_run.state.status is not RunStatus.COMPLETED:
            return _workflow_result(planner_run.state.status, plan, implementations, reviews, runs)
        plan = _artifact_from_result(planner_run, PlanArtifact)

        implementer_run = self._run_agent(
            self._implementer,
            "implementer",
            task,
            (plan,),
        )
        runs.append(implementer_run)
        if implementer_run.state.status is not RunStatus.COMPLETED:
            return _workflow_result(implementer_run.state.status, plan, implementations, reviews, runs)
        implementation = _artifact_from_result(
            implementer_run,
            ImplementationArtifact,
        )
        implementations.append(implementation)

        reviewer_run = self._run_agent(
            self._reviewer,
            "reviewer",
            task,
            (plan, implementation),
        )
        runs.append(reviewer_run)
        if reviewer_run.state.status is not RunStatus.COMPLETED:
            return _workflow_result(reviewer_run.state.status, plan, implementations, reviews, runs)
        review = _artifact_from_result(reviewer_run, ReviewArtifact)
        reviews.append(review)
        if not review.repair_required:
            return _workflow_result(RunStatus.COMPLETED, plan, implementations, reviews, runs)

        repair_run = self._run_agent(
            self._implementer,
            "implementer",
            task,
            (plan, implementation, review),
        )
        runs.append(repair_run)
        if repair_run.state.status is not RunStatus.COMPLETED:
            return _workflow_result(
                repair_run.state.status,
                plan,
                implementations,
                reviews,
                runs,
                repair_count=1,
            )
        repair = _artifact_from_result(repair_run, ImplementationArtifact)
        implementations.append(repair)

        final_reviewer_run = self._run_agent(
            self._reviewer,
            "reviewer",
            task,
            (plan, implementation, review, repair),
        )
        runs.append(final_reviewer_run)
        if final_reviewer_run.state.status is not RunStatus.COMPLETED:
            return _workflow_result(
                final_reviewer_run.state.status,
                plan,
                implementations,
                reviews,
                runs,
                repair_count=1,
            )
        final_review = _artifact_from_result(final_reviewer_run, ReviewArtifact)
        reviews.append(final_review)
        return _workflow_result(
            RunStatus.FAILED if final_review.repair_required else RunStatus.COMPLETED,
            plan,
            implementations,
            reviews,
            runs,
            repair_count=1,
            repair_limit_reached=final_review.repair_required,
        )

    def _run_agent(
        self,
        definition: AgentDefinition,
        role: Literal["planner", "implementer", "reviewer"],
        task: str,
        artifacts: tuple[Artifact, ...],
    ) -> AgentRunResult:
        self._cancel_token.check()
        reservation = self._budget.reserve(definition.budget)
        envelope = WorkflowTask(role=role, task=task, artifacts=artifacts)
        try:
            result = self._agent_service.run(
                definition,
                envelope.model_dump_json(),
                cancel_token=self._cancel_token,
            )
        except Exception:
            reservation.release(definition.budget)
            raise
        reservation.release(_used_budget(result, definition.budget))
        return result


def _artifact_from_result(
    result: AgentRunResult,
    expected_type: type[PlanArtifact]
    | type[ImplementationArtifact]
    | type[ReviewArtifact],
) -> PlanArtifact | ImplementationArtifact | ReviewArtifact:
    payloads = [
        observation.payload
        for observation in result.state.observations
        if observation.kind == "agent_artifact"
    ]
    if len(payloads) != 1:
        raise AgentArtifactValidationError("artifact_schema_invalid")
    artifact = parse_agent_artifact(payloads[0])
    if not isinstance(artifact, expected_type):
        raise AgentArtifactValidationError("artifact_schema_invalid")
    if artifact.producer_run_id != result.run_id:
        raise AgentArtifactValidationError("artifact_schema_invalid")
    return artifact


def _used_budget(
    result: AgentRunResult,
    reserved: AgentBudget,
) -> AgentBudget:
    state = result.state
    steps = max(1, state.step, state.metrics.steps)
    context_chars = max(1, state.metrics.context_chars_max)
    return AgentBudget(
        max_steps=steps,
        context_chars=context_chars,
        child_runs=reserved.child_runs,
    )


def _workflow_result(
    status: RunStatus,
    plan: PlanArtifact | None,
    implementations: list[ImplementationArtifact],
    reviews: list[ReviewArtifact],
    runs: list[AgentRunResult],
    *,
    repair_count: int = 0,
    repair_limit_reached: bool = False,
) -> SequentialReviewResult:
    return SequentialReviewResult(
        status=status,
        plan=plan,
        implementations=tuple(implementations),
        reviews=tuple(reviews),
        agent_runs=tuple(runs),
        repair_count=repair_count,
        repair_limit_reached=repair_limit_reached,
    )
