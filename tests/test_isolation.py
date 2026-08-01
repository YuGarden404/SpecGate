import unittest

from specgate.agent_service import AgentBudget, AgentDefinition, AgentRunResult
from specgate.artifacts import PlanArtifact
from specgate.isolation import (
    RoleContext,
    RoleExecution,
    action_allowed_for_role,
    build_isolation_evidence,
    build_role_contexts,
    filter_state_for_role,
)
from specgate.metrics import RunMetrics
from specgate.multi_agent import build_agent_definitions
from specgate.run_state import Observation, RunState, RunStatus


class IsolationTests(unittest.TestCase):
    def test_filter_state_for_role_hides_unlisted_state_keys(self):
        state = {
            "task": "build dashboard",
            "plan": "step 1",
            "draft_patch": "<html>draft</html>",
            "review_notes": "missing search",
        }

        visible = filter_state_for_role("reviewer", state)

        self.assertIn("task", visible)
        self.assertIn("review_notes", visible)
        self.assertNotIn("draft_patch", visible)

    def test_filter_state_for_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            filter_state_for_role("unknown", {"task": "x"})

    def test_build_role_contexts_defines_planner_implementer_reviewer(self):
        contexts = build_role_contexts()

        self.assertTrue(all(isinstance(context, RoleContext) for context in contexts))
        roles = [context.role for context in contexts]
        self.assertEqual(roles, ["planner", "implementer", "reviewer"])
        reviewer = next(context for context in contexts if context.role == "reviewer")
        self.assertNotIn("draft_patch", reviewer.state_keys)
        self.assertIn("review_notes", reviewer.state_keys)
        self.assertIn("finish", reviewer.allowed_actions)


class IsolationCapabilityTests(unittest.TestCase):
    def test_agent_definitions_are_the_only_role_capability_source(self):
        definitions = build_agent_definitions(context_chars=1200)
        by_id = {definition.agent_id: definition for definition in definitions}

        self.assertEqual(
            by_id["planner"].capability_set,
            frozenset({"read_file", "list_files", "finish"}),
        )
        self.assertEqual(
            by_id["reviewer"].capability_set,
            frozenset({"read_file", "list_files", "finish"}),
        )
        self.assertEqual(
            by_id["implementer"].capability_set,
            frozenset(
                {
                    "read_file",
                    "list_files",
                    "write_file",
                    "replace_file",
                    "finish",
                }
            ),
        )
        self.assertTrue(all(item.budget.max_steps == 1 for item in definitions))

    def test_workflow_evidence_uses_definition_and_typed_agent_result(self):
        definition = AgentDefinition(
            agent_id="planner",
            instructions="Plan the task.",
            capability_set=frozenset({"read_file", "finish"}),
            context_policy="multi-agent-isolated",
            budget=AgentBudget(1, 1000, 0),
        )
        artifact = PlanArtifact(
            producer_run_id="planner-run",
            steps=("Inspect",),
        )
        run = AgentRunResult(
            run_id="planner-run",
            agent_run_id="planner-planner-run",
            parent_run_id=None,
            definition_id="planner",
            effective_capabilities=definition.capability_set,
            active_skills=(),
            state=RunState(
                "planner-run",
                status=RunStatus.COMPLETED,
                step=1,
                observations=(
                    Observation(
                        "tool_result",
                        {"action": "finish", "ok": True, "blocked": False},
                    ),
                    Observation(
                        "agent_artifact",
                        artifact.model_dump(mode="json"),
                    ),
                ),
                metrics=RunMetrics(context_chars_max=321),
            ),
        )

        evidence = build_isolation_evidence(
            strategy="multi-agent-isolated",
            definitions=(definition,),
            agent_runs=(run,),
        )

        self.assertEqual(evidence["roles"][0]["allowed_actions"], ["finish", "read_file"])
        self.assertEqual(evidence["executions"][0]["summary"], "Inspect")
        self.assertEqual(evidence["executions"][0]["context_chars"], 321)

    def test_planner_and_reviewer_cannot_write_files(self):
        self.assertFalse(action_allowed_for_role("planner", "write_file"))
        self.assertFalse(action_allowed_for_role("planner", "replace_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "write_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "replace_file"))

    def test_implementer_can_write_files(self):
        self.assertTrue(action_allowed_for_role("implementer", "write_file"))
        self.assertTrue(action_allowed_for_role("implementer", "replace_file"))
        self.assertTrue(action_allowed_for_role("implementer", "finish"))

    def test_action_allowed_for_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            action_allowed_for_role("auditor", "finish")

    def test_role_execution_to_dict_is_serializable(self):
        execution = RoleExecution(
            role="planner",
            phase="plan",
            context_chars=123,
            visible_sections=("Task", "Checklist"),
            allowed_actions=("read_file", "finish"),
            attempted_action="finish",
            action_allowed_by_role=True,
            blocked_reason=None,
            summary="Plan the page",
        )

        self.assertEqual(
            execution.to_dict(),
            {
                "role": "planner",
                "phase": "plan",
                "context_chars": 123,
                "visible_sections": ["Task", "Checklist"],
                "allowed_actions": ["read_file", "finish"],
                "attempted_action": "finish",
                "action_allowed_by_role": True,
                "blocked_reason": None,
                "summary": "Plan the page",
            },
        )

    def test_build_isolation_evidence_includes_executions(self):
        execution = RoleExecution(
            role="reviewer",
            phase="review",
            context_chars=321,
            visible_sections=("Final Artifact",),
            allowed_actions=("finish",),
            attempted_action="write_file",
            action_allowed_by_role=False,
            blocked_reason="role reviewer cannot perform write_file",
            summary=None,
        )

        evidence = build_isolation_evidence(
            strategy="multi-agent-isolated",
            executions=[execution],
            review_repairs=1,
        )

        self.assertEqual(evidence["strategy"], "multi-agent-isolated")
        self.assertEqual(evidence["role_runs"], 1)
        self.assertEqual(evidence["role_blocked_actions"], 1)
        self.assertEqual(evidence["review_repairs"], 1)
        self.assertEqual(evidence["executions"][0]["role"], "reviewer")


if __name__ == "__main__":
    unittest.main()
