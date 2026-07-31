import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from specgate.agent_service import (
    AgentBudget,
    AgentDefinition,
    AgentService,
    BudgetExceeded,
    DelegationDenied,
    DelegationPolicy,
    effective_child_capabilities,
)
from specgate.run_state import RunStatus, StateDelta


class CompletingLoop:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def run(self, run_id):
        self.calls.append(run_id)
        state = self.store.get(run_id)
        return self.store.apply(
            run_id,
            state.revision,
            StateDelta(status=RunStatus.COMPLETED),
        )


class RecordingRuntimeFactory:
    def __init__(self):
        self.requests = []
        self.sessions = []
        self.stores = []
        self.event_contexts = []
        self.loops = []

    def create(
        self,
        request,
        *,
        state_store,
        skill_session,
        event_context,
    ):
        self.requests.append(request)
        self.sessions.append(skill_session)
        self.stores.append(state_store)
        self.event_contexts.append(event_context)
        loop = CompletingLoop(state_store)
        self.loops.append(loop)
        return loop


def definition(
    agent_id="implementer",
    *,
    capabilities=frozenset({"read_file", "write_file"}),
    budget=AgentBudget(max_steps=8, context_chars=4000, child_runs=0),
    delegation_policy=None,
):
    return AgentDefinition(
        agent_id=agent_id,
        instructions=f"Instructions for {agent_id}",
        capability_set=capabilities,
        context_policy="default",
        budget=budget,
        delegation_policy=delegation_policy,
    )


class AgentDefinitionTests(unittest.TestCase):
    def test_child_capabilities_are_three_way_intersection(self):
        effective = effective_child_capabilities(
            child=frozenset({"read_file", "write_file"}),
            parent=frozenset({"read_file"}),
            workspace=frozenset({"read_file", "list_files"}),
        )

        self.assertEqual(effective, frozenset({"read_file"}))

    def test_models_are_frozen_and_validate_positive_limits(self):
        selected = definition()

        with self.assertRaises(FrozenInstanceError):
            selected.agent_id = "changed"
        with self.assertRaises(ValueError):
            AgentBudget(max_steps=0, context_chars=10, child_runs=0)
        with self.assertRaises(ValueError):
            AgentBudget(max_steps=1, context_chars=0, child_runs=0)
        with self.assertRaises(ValueError):
            AgentBudget(max_steps=1, context_chars=10, child_runs=-1)
        with self.assertRaises(ValueError):
            DelegationPolicy(max_depth=0, max_children=1)
        with self.assertRaises(ValueError):
            DelegationPolicy(max_depth=1, max_children=0)

    def test_definition_rejects_unsafe_identity_and_non_frozen_capabilities(self):
        with self.assertRaises(ValueError):
            definition(agent_id="../reviewer")
        with self.assertRaises(TypeError):
            definition(capabilities={"read_file"})


class AgentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.audit_root = Path(self.temporary.name)
        self.factory = RecordingRuntimeFactory()
        identifiers = iter(("run-1", "run-2", "run-3", "run-4"))
        self.service = AgentService(
            audit_root=self.audit_root,
            workspace_capabilities=frozenset(
                {"read_file", "list_files", "load_skill"}
            ),
            runtime_factory=self.factory,
            id_factory=lambda: next(identifiers),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_each_run_has_distinct_identity_state_store_and_skill_session(self):
        selected = definition(
            capabilities=frozenset({"read_file", "write_file", "load_skill"})
        )

        first = self.service.run(selected, "first task")
        second = self.service.run(selected, "second task")

        self.assertEqual(first.run_id, "run-1")
        self.assertEqual(second.run_id, "run-2")
        self.assertNotEqual(first.agent_run_id, second.agent_run_id)
        self.assertIsNot(self.factory.sessions[0], self.factory.sessions[1])
        self.assertEqual(
            self.factory.sessions[0].agent_run_id,
            first.agent_run_id,
        )
        self.assertEqual(self.factory.sessions[0].active_names, ())
        self.assertIsNot(self.factory.stores[0], self.factory.stores[1])
        self.assertTrue((self.audit_root / "run-1" / "state.json").is_file())
        self.assertTrue((self.audit_root / "run-2" / "state.json").is_file())
        self.assertEqual(self.factory.requests[0].task, "first task")
        self.assertEqual(
            self.factory.requests[0].effective_capabilities,
            frozenset({"read_file", "load_skill"}),
        )
        self.assertEqual(self.factory.loops[0].calls, ["run-1"])
        self.assertEqual(first.state.status, RunStatus.COMPLETED)

    def test_state_file_does_not_persist_task_instructions_or_credentials(self):
        secret = "sk-agent-service-secret-1234567890"
        selected = AgentDefinition(
            agent_id="secure-agent",
            instructions=f"Never persist {secret}",
            capability_set=frozenset({"read_file"}),
            context_policy="default",
            budget=AgentBudget(2, 1000, 0),
        )

        result = self.service.run(selected, f"task contains {secret}")
        raw = (self.audit_root / result.run_id / "state.json").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(secret, raw)
        self.assertNotIn("Never persist", raw)
        self.assertNotIn("task contains", raw)

    def test_parent_without_delegation_policy_cannot_create_child(self):
        parent = self.service.run(definition(), "parent")

        with self.assertRaises(DelegationDenied):
            self.service.run(
                definition(agent_id="reviewer"),
                "child",
                parent_run_id=parent.run_id,
            )

        self.assertEqual(len(self.factory.requests), 1)

    def test_child_uses_parent_and_workspace_capability_intersection(self):
        parent = self.service.run(
            definition(
                capabilities=frozenset({"read_file", "write_file"}),
                budget=AgentBudget(8, 4000, 1),
                delegation_policy=DelegationPolicy(max_depth=1, max_children=1),
            ),
            "parent",
        )

        child = self.service.run(
            definition(
                agent_id="reviewer",
                capabilities=frozenset({"read_file", "list_files"}),
                budget=AgentBudget(4, 2000, 0),
            ),
            "child",
            parent_run_id=parent.run_id,
        )

        request = self.factory.requests[-1]
        self.assertEqual(request.effective_capabilities, frozenset({"read_file"}))
        self.assertEqual(child.parent_run_id, parent.run_id)
        self.assertEqual(
            self.factory.event_contexts[-1].parent_run_id,
            parent.run_id,
        )

    def test_child_budget_cannot_exceed_parent_reservation(self):
        parent = self.service.run(
            definition(
                budget=AgentBudget(5, 2000, 1),
                delegation_policy=DelegationPolicy(max_depth=1, max_children=1),
            ),
            "parent",
        )

        with self.assertRaises(BudgetExceeded):
            self.service.run(
                definition(
                    agent_id="reviewer",
                    budget=AgentBudget(6, 1000, 0),
                ),
                "child",
                parent_run_id=parent.run_id,
            )

    def test_max_children_and_inherited_depth_fail_closed(self):
        parent = self.service.run(
            definition(
                budget=AgentBudget(8, 4000, 2),
                delegation_policy=DelegationPolicy(max_depth=1, max_children=1),
            ),
            "parent",
        )
        child = self.service.run(
            definition(
                agent_id="reviewer",
                budget=AgentBudget(4, 2000, 1),
                delegation_policy=DelegationPolicy(max_depth=10, max_children=1),
            ),
            "child",
            parent_run_id=parent.run_id,
        )

        with self.assertRaises(DelegationDenied):
            self.service.run(
                definition(agent_id="nested"),
                "grandchild",
                parent_run_id=child.run_id,
            )
        with self.assertRaises(DelegationDenied):
            self.service.run(
                definition(agent_id="second-child"),
                "second child",
                parent_run_id=parent.run_id,
            )


if __name__ == "__main__":
    unittest.main()
