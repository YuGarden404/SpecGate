import json
import threading
import unittest

from specgate.agent_service import (
    AgentBudget,
    AgentDefinition,
    AgentRunResult,
    BudgetExceeded,
)
from specgate.artifacts import (
    ImplementationArtifact,
    PlanArtifact,
    ReviewArtifact,
)
from specgate.metrics import RunMetrics
from specgate.run_state import Observation, RunState, RunStatus
from specgate.workflows import (
    BudgetReservationError,
    SequentialReviewWorkflow,
    WorkflowBudget,
    WorkflowTask,
)


def definition(agent_id, budget=None):
    return AgentDefinition(
        agent_id=agent_id,
        instructions=f"Instructions for {agent_id}",
        capability_set=frozenset({"read_file", "finish"}),
        context_policy="multi-agent-isolated",
        budget=budget or AgentBudget(2, 100, 0),
    )


def completed_result(artifact, *, steps=1, context_chars=20):
    run_id = artifact.producer_run_id
    state = RunState(
        run_id=run_id,
        status=RunStatus.COMPLETED,
        step=steps,
        observations=(
            Observation("agent_artifact", artifact.model_dump(mode="json")),
        ),
        metrics=RunMetrics(steps=steps, context_chars_max=context_chars),
    )
    return AgentRunResult(
        run_id=run_id,
        agent_run_id=f"agent-{run_id}",
        parent_run_id=None,
        definition_id=run_id.split("-", 1)[0],
        effective_capabilities=frozenset({"read_file", "finish"}),
        active_skills=(),
        state=state,
    )


def non_terminal_artifact_result(status):
    return AgentRunResult(
        run_id="implementer-paused",
        agent_run_id="agent-implementer-paused",
        parent_run_id=None,
        definition_id="implementer",
        effective_capabilities=frozenset({"read_file", "finish"}),
        active_skills=(),
        state=RunState(
            run_id="implementer-paused",
            status=status,
            step=1,
            metrics=RunMetrics(steps=1, context_chars_max=10),
        ),
    )


class RecordingCancellationToken:
    def __init__(self):
        self.checks = 0

    def check(self):
        self.checks += 1

    def remaining_seconds(self):
        return 60.0


class RecordingAgentService:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(
        self,
        selected_definition,
        task,
        parent_run_id=None,
        cancel_token=None,
    ):
        self.calls.append(
            (selected_definition, task, parent_run_id, cancel_token)
        )
        return self.results.pop(0)


class WorkflowBudgetTests(unittest.TestCase):
    def test_release_returns_only_unused_budget_and_rejects_duplicates(self):
        budget = WorkflowBudget(AgentBudget(10, 1000, 2))
        reservation = budget.reserve(AgentBudget(4, 400, 1))

        self.assertEqual(budget.remaining.max_steps, 6)
        self.assertEqual(budget.remaining.context_chars, 600)
        self.assertEqual(budget.remaining.child_runs, 1)

        reservation.release(AgentBudget(2, 150, 1))

        self.assertEqual(budget.remaining.max_steps, 8)
        self.assertEqual(budget.remaining.context_chars, 850)
        self.assertEqual(budget.remaining.child_runs, 1)
        with self.assertRaises(BudgetReservationError):
            reservation.release(AgentBudget(1, 1, 0))

    def test_reservation_is_atomic_when_capacity_is_contended(self):
        budget = WorkflowBudget(AgentBudget(7, 700, 0))
        barrier = threading.Barrier(3)
        outcomes = []

        def reserve():
            barrier.wait()
            try:
                budget.reserve(AgentBudget(5, 500, 0))
            except BudgetExceeded:
                outcomes.append("rejected")
            else:
                outcomes.append("reserved")

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["reserved", "rejected"])
        self.assertEqual(budget.remaining.max_steps, 2)
        self.assertEqual(budget.remaining.context_chars, 200)


class SequentialReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.planner = definition("planner")
        self.implementer = definition("implementer")
        self.reviewer = definition("reviewer")
        self.token = RecordingCancellationToken()

    def workflow(self, results, budget=None):
        service = RecordingAgentService(results)
        workflow = SequentialReviewWorkflow(
            agent_service=service,
            planner=self.planner,
            implementer=self.implementer,
            reviewer=self.reviewer,
            budget=budget or WorkflowBudget(AgentBudget(20, 2000, 0)),
            cancel_token=self.token,
        )
        return workflow, service

    def test_runs_roles_in_order_and_passes_typed_artifacts(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        implementation = ImplementationArtifact(
            producer_run_id="implementer-run",
            references=("planner-run",),
            changed_paths=("index.html",),
            summary="Built page.",
        )
        review = ReviewArtifact(
            producer_run_id="reviewer-run",
            references=("implementer-run",),
            accepted=True,
            repair_required=False,
        )
        workflow, service = self.workflow(
            [
                completed_result(plan),
                completed_result(implementation),
                completed_result(review),
            ]
        )

        result = workflow.run("Build the page")

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(
            [call[0].agent_id for call in service.calls],
            ["planner", "implementer", "reviewer"],
        )
        inputs = [WorkflowTask.model_validate_json(call[1]) for call in service.calls]
        self.assertEqual(inputs[0].artifacts, ())
        self.assertEqual(inputs[1].artifacts, (plan,))
        self.assertEqual(inputs[2].artifacts, (plan, implementation))

    def test_review_flag_alone_controls_single_repair_and_rereview(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        first_implementation = ImplementationArtifact(
            producer_run_id="implementer-run-1",
            changed_paths=("index.html",),
            summary="First pass.",
        )
        first_review = ReviewArtifact(
            producer_run_id="reviewer-run-1",
            accepted=False,
            repair_required=True,
            issues=("Needs repair.",),
        )
        repair = ImplementationArtifact(
            producer_run_id="implementer-run-2",
            references=("reviewer-run-1",),
            changed_paths=("index.html",),
            summary="Repaired.",
        )
        final_review = ReviewArtifact(
            producer_run_id="reviewer-run-2",
            accepted=True,
            repair_required=False,
        )
        workflow, service = self.workflow(
            [
                completed_result(plan),
                completed_result(first_implementation),
                completed_result(first_review),
                completed_result(repair),
                completed_result(final_review),
            ]
        )

        result = workflow.run("Build the page")

        self.assertTrue(result.accepted)
        self.assertEqual(result.repair_count, 1)
        self.assertEqual(
            [call[0].agent_id for call in service.calls],
            ["planner", "implementer", "reviewer", "implementer", "reviewer"],
        )

    def test_repair_words_do_not_start_repair_without_typed_flag(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        implementation = ImplementationArtifact(
            producer_run_id="implementer-run",
            changed_paths=(),
            summary="No change.",
        )
        review = ReviewArtifact(
            producer_run_id="reviewer-run",
            accepted=True,
            repair_required=False,
            issues=("Quoted request_repair text",),
        )
        workflow, service = self.workflow(
            [
                completed_result(plan),
                completed_result(implementation),
                completed_result(review),
            ]
        )

        result = workflow.run("Inspect only")

        self.assertTrue(result.accepted)
        self.assertEqual(len(service.calls), 3)

    def test_budget_exhaustion_does_not_start_next_agent(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        workflow, service = self.workflow(
            [completed_result(plan, steps=2, context_chars=100)],
            budget=WorkflowBudget(AgentBudget(3, 150, 0)),
        )

        with self.assertRaises(BudgetExceeded):
            workflow.run("Build the page")

        self.assertEqual(len(service.calls), 1)

    def test_same_cancellation_token_is_propagated_to_every_agent(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        implementation = ImplementationArtifact(
            producer_run_id="implementer-run",
            changed_paths=(),
            summary="Done.",
        )
        review = ReviewArtifact(
            producer_run_id="reviewer-run",
            accepted=True,
            repair_required=False,
        )
        workflow, service = self.workflow(
            [
                completed_result(plan),
                completed_result(implementation),
                completed_result(review),
            ]
        )

        workflow.run("Build the page")

        self.assertGreaterEqual(self.token.checks, 3)
        self.assertTrue(all(call[3] is self.token for call in service.calls))

    def test_suspended_agent_stops_workflow_without_starting_reviewer(self):
        plan = PlanArtifact(producer_run_id="planner-run", steps=("build",))
        workflow, service = self.workflow(
            [
                completed_result(plan),
                non_terminal_artifact_result(RunStatus.NEEDS_APPROVAL),
            ]
        )

        result = workflow.run("Build the page")

        self.assertEqual(result.status, RunStatus.NEEDS_APPROVAL)
        self.assertFalse(result.accepted)
        self.assertEqual(len(service.calls), 2)


if __name__ == "__main__":
    unittest.main()
