import tempfile
import unittest
from dataclasses import FrozenInstanceError
import inspect
from pathlib import Path

from specgate.agent_service import (
    AgentBudget,
    AgentDefinition,
    AgentResumeHandle,
    AgentService,
    AgentServiceFactory,
    BudgetExceeded,
    DelegationDenied,
    DelegationPolicy,
    build_agent_service,
    build_resumable_agent_service,
    effective_child_capabilities,
)
from specgate.action_pipeline import ExecutionOutcome, ExecutionStatus, RuntimeErrorInfo
from specgate.actions import Action
from specgate.approvals import (
    ApprovalConflictError,
    ApprovalDecision,
    ApprovalGrant,
    ApprovalQueue,
    ApprovalStore,
    PendingApproval,
    approval_action_digest,
    capture_target_state,
)
from specgate.run_state import Observation, RunStatus, StateDelta
from specgate.skill_registry import SkillSession
from specgate.tool_runtime import ToolResult


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


class AgentServiceFactoryContractTests(unittest.TestCase):
    def test_build_has_one_keyword_only_composition_contract(self):
        for builder in (AgentServiceFactory.build, AgentServiceFactory.build_resumable):
            with self.subTest(builder=builder.__name__):
                signature = inspect.signature(builder)

                self.assertEqual(
                    list(signature.parameters),
                    [
                        "self",
                        "root",
                        "llm",
                        "policy",
                        "audit_dir",
                        "approval_queue_file",
                        "runtime_config",
                        "cancel_token",
                        "id_factory",
                    ],
                )
                for name in list(signature.parameters)[1:]:
                    self.assertIs(
                        signature.parameters[name].kind,
                        inspect.Parameter.KEYWORD_ONLY,
                    )

    def test_public_build_helpers_accept_optional_id_factory(self):
        for builder in (build_agent_service, build_resumable_agent_service):
            with self.subTest(builder=builder.__name__):
                parameter = inspect.signature(builder).parameters["id_factory"]
                self.assertIsNone(parameter.default)
                self.assertIs(
                    parameter.kind,
                    inspect.Parameter.KEYWORD_ONLY,
                )


class ApprovalRuntimeLoop:
    def __init__(self, root, store, mode="success"):
        self.approval_root = root
        self.approval_store = ApprovalStore(root / "pending_approvals.json")
        self.store = store
        self.mode = mode
        self.run_calls = 0
        self.approval_calls = []
        self.handler_calls = 0
        self.events = []

    def run(self, run_id):
        self.run_calls += 1
        state = self.store.get(run_id)
        if self.run_calls == 1:
            return self.store.apply(
                run_id,
                state.revision,
                StateDelta(
                    status=RunStatus.NEEDS_APPROVAL,
                    step=1,
                    pending_approval_id="approval-1",
                ),
            )
        if state.status is RunStatus.NEEDS_APPROVAL:
            return state
        return self.store.apply(
            run_id,
            state.revision,
            StateDelta(status=RunStatus.COMPLETED),
        )

    def execute_approval(
        self,
        action,
        state,
        approval,
        grant,
        cancel_token,
    ):
        cancel_token.check()
        queue = self.approval_store.read_existing()
        self.assert_grant(action, approval, grant, queue)
        self.approval_calls.append((action, state, approval, grant))
        if self.mode == "reapproval":
            next_approval = PendingApproval(
                id="approval-2",
                step=approval.step,
                action=action.action,
                path=approval.path,
                risk_level="review",
                reason="new review requirement",
                profile="review",
                action_payload=approval.action_payload,
                target_state=approval.target_state,
            )
            updated_queue = self.approval_store.append(
                next_approval,
                expected_revision=queue.revision,
            )
            del updated_queue
            observation = Observation(
                "approval_required",
                {"approval_id": next_approval.id, "code": "new_review"},
            )
            return ExecutionOutcome(
                ExecutionStatus.APPROVAL_REQUIRED,
                StateDelta(
                    status=RunStatus.NEEDS_APPROVAL,
                    pending_approval_id=next_approval.id,
                    append_observations=(observation,),
                ),
                approval_request=next_approval,
                feedback=observation,
            )
        if self.mode == "blocked":
            observation = Observation(
                "tool_result",
                {"code": "new_governance_block", "blocked": True},
            )
            return ExecutionOutcome(
                ExecutionStatus.BLOCKED,
                StateDelta(append_observations=(observation,)),
                feedback=observation,
                error=RuntimeErrorInfo(
                    "new_governance_block",
                    "new governance rule blocked the action",
                ),
            )
        self.handler_calls += 1
        result = ToolResult.success(action.action, {"applied": True})
        return ExecutionOutcome(
            ExecutionStatus.SUCCEEDED,
            StateDelta(
                append_observations=(
                    Observation(
                        "tool_result",
                        {"action": action.action, "ok": True},
                    ),
                )
            ),
            tool_result=result,
        )

    def assert_grant(self, action, approval, grant, queue):
        self_payload = {
            "schema_version": action.schema_version,
            "action": action.action,
            "args": action.args,
        }
        if queue.find(approval.id).status != "applying":
            raise AssertionError("approval was not claimed before execution")
        if grant.queue_revision != queue.revision:
            raise AssertionError("grant revision is not bound to applying queue")
        if grant.action_digest != approval_action_digest(self_payload):
            raise AssertionError("grant action digest does not match replayed action")

    def emit_resume_event(self, event_type, payload):
        self.events.append((event_type, payload))


class ApprovalRuntimeFactory:
    def __init__(self, audit_root, workspace_root, mode="success"):
        self.audit_root = audit_root
        self.workspace_root = workspace_root
        self.mode = mode
        self.loops = []

    def create(
        self,
        request,
        *,
        state_store,
        skill_session,
        event_context,
    ):
        del skill_session, event_context
        run_root = self.audit_root / request.run_id
        action = Action(
            "1",
            "write_file",
            {"path": "target.txt", "content": "approved"},
        )
        approval = PendingApproval(
            id="approval-1",
            step=1,
            action=action.action,
            path="target.txt",
            risk_level="review",
            reason="write_file requires review",
            profile="review",
            action_payload={
                "schema_version": action.schema_version,
                "action": action.action,
                "args": action.args,
            },
            target_state=capture_target_state(
                self.workspace_root,
                "target.txt",
            ),
        )
        ApprovalQueue([approval]).write(run_root / "pending_approvals.json")
        loop = ApprovalRuntimeLoop(self.workspace_root, state_store, self.mode)
        loop.approval_store = ApprovalStore(run_root / "pending_approvals.json")
        self.loops.append(loop)
        return loop


class StaticResumeLoader:
    def __init__(self, handle):
        self.handle = handle
        self.calls = []

    def load(self, run_id, cancel_token):
        cancel_token.check()
        self.calls.append(run_id)
        return self.handle


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


class ApprovalResumeModelTests(unittest.TestCase):
    def test_decision_and_grant_are_frozen_and_validate_identity(self):
        decision = ApprovalDecision("approval-1", "approved", 3, "reviewed")
        grant = ApprovalGrant("approval-1", "a" * 64, 4)

        self.assertEqual(decision.expected_revision, 3)
        self.assertEqual(grant.queue_revision, 4)
        with self.assertRaises(FrozenInstanceError):
            decision.status = "denied"
        with self.assertRaises(FrozenInstanceError):
            grant.queue_revision = 5
        with self.assertRaises(ValueError):
            ApprovalDecision("../approval", "approved", 0)
        with self.assertRaises(ValueError):
            ApprovalDecision("approval-1", "pending", 0)
        with self.assertRaises(ValueError):
            ApprovalDecision("approval-1", "approved", -1)
        with self.assertRaises(ValueError):
            ApprovalGrant("approval-1", "not-a-digest", 0)


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


class AgentServiceResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.audit_root = self.root / "audit"
        self.workspace_root = self.root / "workspace"
        self.audit_root.mkdir()
        self.workspace_root.mkdir()
        (self.workspace_root / "target.txt").write_text(
            "original",
            encoding="utf-8",
        )

    def _service(self, mode="success"):
        factory = ApprovalRuntimeFactory(
            self.audit_root,
            self.workspace_root,
            mode,
        )
        service = AgentService(
            audit_root=self.audit_root,
            workspace_capabilities=frozenset({"write_file"}),
            runtime_factory=factory,
            id_factory=lambda: "run-approval",
        )
        return service, factory

    def test_approved_decision_applies_once_and_continues_same_loop(self):
        service, factory = self._service()
        suspended = service.run(
            definition(capabilities=frozenset({"write_file"})),
            "write target",
        )

        resumed = service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "approved", 0, "reviewed"),
        )

        loop = factory.loops[0]
        queue = loop.approval_store.read_existing()
        self.assertEqual(resumed.run_id, suspended.run_id)
        self.assertEqual(resumed.agent_run_id, suspended.agent_run_id)
        self.assertEqual(resumed.state.status, RunStatus.COMPLETED)
        self.assertIsNone(resumed.state.pending_approval_id)
        self.assertEqual(queue.find("approval-1").status, "applied")
        self.assertEqual(queue.revision, 3)
        self.assertEqual(loop.run_calls, 2)
        self.assertEqual(loop.handler_calls, 1)
        self.assertEqual(
            [event_type for event_type, _ in loop.events],
            ["RunResumed", "ApprovalClaimed", "ApprovalApplied"],
        )

        with self.assertRaises((ApprovalConflictError, ValueError)):
            service.resume(
                suspended.run_id,
                ApprovalDecision("approval-1", "approved", 0),
            )
        self.assertEqual(loop.handler_calls, 1)

    def test_denied_decision_never_executes_handler(self):
        service, factory = self._service()
        suspended = service.run(definition(capabilities=frozenset({"write_file"})), "write")

        resumed = service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "denied", 0, "too broad"),
        )

        loop = factory.loops[0]
        queue = loop.approval_store.read_existing()
        self.assertEqual(resumed.state.status, RunStatus.COMPLETED)
        self.assertEqual(queue.find("approval-1").status, "rejected")
        self.assertEqual(queue.revision, 2)
        self.assertEqual(loop.approval_calls, [])
        self.assertEqual(loop.handler_calls, 0)

    def test_stale_revision_and_target_change_fail_closed(self):
        service, factory = self._service()
        suspended = service.run(definition(capabilities=frozenset({"write_file"})), "write")
        loop = factory.loops[0]

        with self.assertRaises(ApprovalConflictError):
            service.resume(
                suspended.run_id,
                ApprovalDecision("approval-1", "approved", 9),
            )
        self.assertEqual(loop.handler_calls, 0)
        self.assertEqual(loop.approval_store.read_existing().revision, 0)

        (self.workspace_root / "target.txt").write_text(
            "changed externally",
            encoding="utf-8",
        )
        resumed = service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "approved", 0),
        )

        queue = loop.approval_store.read_existing()
        self.assertEqual(queue.find("approval-1").status, "failed")
        self.assertEqual(loop.handler_calls, 0)
        self.assertTrue(
            any(
                item.payload.get("code") == "approval_target_changed"
                for item in resumed.state.observations
            )
        )

    def test_new_governance_block_overrides_old_approval(self):
        service, factory = self._service(mode="blocked")
        suspended = service.run(definition(capabilities=frozenset({"write_file"})), "write")

        resumed = service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "approved", 0),
        )

        loop = factory.loops[0]
        self.assertEqual(
            loop.approval_store.read_existing().find("approval-1").status,
            "failed",
        )
        self.assertEqual(loop.handler_calls, 0)
        self.assertEqual(resumed.state.status, RunStatus.COMPLETED)
        self.assertTrue(
            any(
                item.payload.get("code") == "new_governance_block"
                for item in resumed.state.observations
            )
        )

    def test_resume_loader_restores_a_run_when_service_memory_is_empty(self):
        first_service, factory = self._service()
        selected = definition(capabilities=frozenset({"write_file"}))
        suspended = first_service.run(selected, "write")
        first_loop = factory.loops[0]
        handle = AgentResumeHandle(
            run_id=suspended.run_id,
            agent_run_id=suspended.agent_run_id,
            parent_run_id=suspended.parent_run_id,
            definition=selected,
            effective_capabilities=suspended.effective_capabilities,
            skill_session=SkillSession(suspended.agent_run_id),
            state_store=first_loop.store,
            runtime=first_loop,
        )
        loader = StaticResumeLoader(handle)
        restored_service = AgentService(
            audit_root=self.audit_root,
            workspace_capabilities=frozenset({"write_file"}),
            runtime_factory=ApprovalRuntimeFactory(
                self.audit_root,
                self.workspace_root,
            ),
            resume_loader=loader,
        )

        resumed = restored_service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "approved", 0),
        )

        self.assertEqual(loader.calls, [suspended.run_id])
        self.assertEqual(resumed.state.status, RunStatus.COMPLETED)
        self.assertEqual(first_loop.handler_calls, 1)

    def test_different_reapproval_replaces_pending_id_without_handler(self):
        service, factory = self._service(mode="reapproval")
        suspended = service.run(
            definition(capabilities=frozenset({"write_file"})),
            "write",
        )

        resumed = service.resume(
            suspended.run_id,
            ApprovalDecision("approval-1", "approved", 0),
        )

        loop = factory.loops[0]
        queue = loop.approval_store.read_existing()
        self.assertEqual(queue.find("approval-1").status, "failed")
        self.assertEqual(queue.find("approval-2").status, "pending")
        self.assertEqual(resumed.state.status, RunStatus.NEEDS_APPROVAL)
        self.assertEqual(resumed.state.pending_approval_id, "approval-2")
        self.assertEqual(loop.handler_calls, 0)


if __name__ == "__main__":
    unittest.main()
