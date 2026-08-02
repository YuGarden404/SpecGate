import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from pydantic import BaseModel

from specgate.action_pipeline import (
    ActionPipeline,
    ExecutionStatus,
    PipelineExecutionContext,
)
from specgate.actions import Action
from specgate.approvals import (
    ApprovalGrant,
    GovernanceConfig,
    PendingApproval,
    approval_action_digest,
)
from specgate.gate import GateContext, GateResult, HtmlGateRunner
from specgate.governance import GovernanceDecision, GovernanceDecisionKind
from specgate.hooks import BeforeToolDecision
from specgate.policy import WorkspacePolicy
from specgate.run_state import RunStateConflict, RunStatus
from specgate.runtime_events import RunEventContext
from specgate.tool_handlers import ToolExecutionContext
from specgate.tool_registry import (
    PermissionClass,
    SideEffectClass,
    ToolDefinition,
    ToolMetadata,
    ToolRegistry,
)
from specgate.tool_runtime import ToolResult, ToolRuntime
from specgate.validation import DefaultValidationPolicy
from tests.shell_support import RecordingSink


class EmptyArgs(BaseModel):
    pass


class RequiredArgs(BaseModel):
    required: str


class PayloadResult(BaseModel):
    value: str = "ok"


class PathContentArgs(BaseModel):
    path: str
    content: str


class RecordingHandler:
    def __init__(self, calls, result=None):
        self.calls = calls
        self.result = {"value": "ok"} if result is None else result

    def execute(self, args, context):
        self.calls.append("handler")
        return self.result


class RecordingHooks:
    def __init__(self, calls, decision=None):
        self.calls = calls
        self.decision = decision or BeforeToolDecision.continue_()

    def before_tool(self, event):
        self.calls.append("before_tool")
        return self.decision

    def after_tool(self, event):
        self.calls.append("after_tool")

    def after_gate(self, event):
        self.calls.append("after_gate")


class RecordingGovernance:
    def __init__(self, calls, decision=None):
        self.calls = calls
        self.decision = decision or GovernanceDecision(
            GovernanceDecisionKind.ALLOW,
            "safe",
            "safe action",
            "none",
        )

    def evaluate(self, call, *, capabilities, policy, config):
        self.calls.append("governance")
        return self.decision


class RecordingGate:
    def __init__(self, calls, result=None):
        self.calls = calls
        self.result = result or GateResult(True, [], [], "passed")

    def run(self, context):
        self.calls.append("gate")
        return self.result


class RecordingApprovalRequester:
    def __init__(self):
        self.requests = []

    def request(self, action, *, step, reason):
        self.requests.append((action, step, reason))
        return PendingApproval(
            id="approval-1",
            step=step,
            action=action.action,
            path=None,
            risk_level="review",
            reason=reason,
            profile="review",
        )


class ActionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.calls = []
        self.policy = WorkspacePolicy(
            self.root,
            {"write_file", "read_file", "finish", "control"},
            {"index.html", "CHECKLIST.md"},
            {"index.html"},
        )
        self.execution_context = PipelineExecutionContext(
            event_context=RunEventContext("run-1", "agent-1"),
            step=3,
            capabilities=frozenset(self.policy.allowed_actions),
            policy=self.policy,
            governance_config=GovernanceConfig(profile="strict"),
            tool_context=ToolExecutionContext(self.policy, None),
            gate_context=GateContext(self.root, self.policy),
        )

    def _definition(self, name, side_effect, handler=None):
        return ToolDefinition(
            ToolMetadata(name, "test tool"),
            PermissionClass.CONTROL,
            side_effect,
            EmptyArgs,
            PayloadResult,
            handler or RecordingHandler(self.calls),
        )

    def _pipeline(
        self,
        definition,
        *,
        hooks=None,
        governance=None,
        gate=None,
        runtime=None,
        event_sink=None,
    ):
        return ActionPipeline(
            runtime or ToolRuntime(ToolRegistry([definition])),
            hooks or RecordingHooks(self.calls),
            governance or RecordingGovernance(self.calls),
            DefaultValidationPolicy(),
            gate or RecordingGate(self.calls),
            event_sink=event_sink,
        )

    def _execute(self, definition, **pipeline_kwargs):
        pipeline = self._pipeline(definition, **pipeline_kwargs)
        return pipeline.execute(Action("1", definition.name, {}), self.execution_context)

    def test_pipeline_order_for_write(self):
        outcome = self._execute(
            self._definition("write_file", SideEffectClass.WORKSPACE_WRITE)
        )

        self.assertEqual(
            self.calls,
            [
                "before_tool",
                "governance",
                "handler",
                "after_tool",
                "gate",
                "after_gate",
            ],
        )
        self.assertEqual(outcome.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(outcome.gate_result.passed)

    def test_pipeline_emits_governance_allowed_before_tool_execution(self):
        class OrderedSink(RecordingSink):
            def emit(self, *args, **kwargs):
                self.calls.append("governance_event")
                super().emit(*args, **kwargs)

        sink = OrderedSink()
        sink.calls = self.calls
        definition = self._definition(
            "write_file",
            SideEffectClass.WORKSPACE_WRITE,
        )

        self._pipeline(definition, event_sink=sink).execute(
            Action("1", definition.name, {}),
            self.execution_context,
        )

        event = next(
            item for item in sink.events if item[1] == "GovernanceEvaluated"
        )
        self.assertEqual(event[2]["decision"], "allow")
        self.assertEqual(event[2]["action"], "write_file")
        self.assertLess(
            self.calls.index("governance_event"),
            self.calls.index("handler"),
        )

    def test_governance_events_expose_only_safe_fields_for_all_decisions(self):
        decisions = (
            GovernanceDecision(
                GovernanceDecisionKind.ALLOW,
                "safe",
                "safe action",
                "none",
            ),
            GovernanceDecision(
                GovernanceDecisionKind.BLOCK,
                "capability",
                "capability denied",
                "capability",
            ),
            GovernanceDecision(
                GovernanceDecisionKind.REQUIRE_APPROVAL,
                "review",
                "review required",
                "risk",
            ),
        )
        for decision in decisions:
            with self.subTest(decision=decision.kind.value):
                self.calls.clear()
                sink = RecordingSink()
                requester = RecordingApprovalRequester()
                context = self._context_with_requester(requester)
                definition = ToolDefinition(
                    ToolMetadata("write_file", "test tool"),
                    PermissionClass.CONTROL,
                    SideEffectClass.WORKSPACE_WRITE,
                    PathContentArgs,
                    PayloadResult,
                    RecordingHandler(self.calls),
                )
                action = Action(
                    "1",
                    "write_file",
                    {
                        "path": "index.html",
                        "content": "sk-secret-content-1234567890",
                    },
                )

                self._pipeline(
                    definition,
                    governance=RecordingGovernance(self.calls, decision),
                    event_sink=sink,
                ).execute(action, context)

                event = next(
                    item
                    for item in sink.events
                    if item[1] == "GovernanceEvaluated"
                )
                self.assertEqual(
                    set(event[2]),
                    {"action", "path", "decision", "code", "rule_family"},
                )
                self.assertEqual(event[2]["path"], "index.html")
                self.assertNotIn("content", str(event[2]))
                self.assertNotIn("sk-secret", str(event[2]))

    def test_approval_event_omits_action_payload_and_content(self):
        sink = RecordingSink()
        requester = RecordingApprovalRequester()
        context = self._context_with_requester(requester)
        definition = ToolDefinition(
            ToolMetadata("write_file", "test tool"),
            PermissionClass.CONTROL,
            SideEffectClass.WORKSPACE_WRITE,
            PathContentArgs,
            PayloadResult,
            RecordingHandler(self.calls),
        )
        action = Action(
            "1",
            "write_file",
            {
                "path": "index.html",
                "content": "sk-secret-content-1234567890",
            },
        )
        decision = GovernanceDecision(
            GovernanceDecisionKind.REQUIRE_APPROVAL,
            "review",
            "review required sk-approval-secret-1234567890",
            "risk",
        )

        self._pipeline(
            definition,
            governance=RecordingGovernance(self.calls, decision),
            event_sink=sink,
        ).execute(action, context)

        event = next(item for item in sink.events if item[1] == "ApprovalRequested")
        self.assertEqual(event[2]["approval_id"], "approval-1")
        self.assertEqual(event[2]["action"], "write_file")
        self.assertEqual(event[2]["path"], None)
        self.assertNotIn("action_payload", event[2])
        self.assertNotIn("content", str(event[2]))
        self.assertNotIn("sk-secret", str(event[2]))
        self.assertNotIn("sk-approval-secret", str(event[2]))

    def test_before_tool_block_skips_governance_and_handler(self):
        hooks = RecordingHooks(
            self.calls,
            BeforeToolDecision.block("project_policy", "blocked by hook"),
        )

        outcome = self._execute(
            self._definition("write_file", SideEffectClass.WORKSPACE_WRITE),
            hooks=hooks,
        )

        self.assertEqual(self.calls, ["before_tool"])
        self.assertEqual(outcome.status, ExecutionStatus.BLOCKED)
        self.assertEqual(outcome.error.code, "project_policy")

    def test_before_tool_approval_skips_governance_and_handler(self):
        requester = RecordingApprovalRequester()
        sink = RecordingSink()
        context = self._context_with_requester(requester)
        hooks = RecordingHooks(
            self.calls,
            BeforeToolDecision.require_approval("review", "review hook"),
        )
        definition = self._definition("write_file", SideEffectClass.WORKSPACE_WRITE)

        outcome = self._pipeline(
            definition,
            hooks=hooks,
            event_sink=sink,
        ).execute(
            Action("1", definition.name, {}), context
        )

        self.assertEqual(self.calls, ["before_tool"])
        self.assertEqual(outcome.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(outcome.approval_request.id, "approval-1")
        self.assertEqual(outcome.state_delta.status, RunStatus.NEEDS_APPROVAL)
        self.assertEqual(outcome.state_delta.pending_approval_id, "approval-1")
        approval_event = next(
            item for item in sink.events if item[1] == "ApprovalRequested"
        )
        self.assertEqual(approval_event[2]["approval_id"], "approval-1")
        self.assertNotIn("action_payload", approval_event[2])

    def test_governance_block_and_approval_skip_handler(self):
        cases = (
            (
                GovernanceDecision(
                    GovernanceDecisionKind.BLOCK,
                    "capability",
                    "capability denied",
                    "capability",
                ),
                ExecutionStatus.BLOCKED,
            ),
            (
                GovernanceDecision(
                    GovernanceDecisionKind.REQUIRE_APPROVAL,
                    "review",
                    "review governance",
                    "none",
                ),
                ExecutionStatus.APPROVAL_REQUIRED,
            ),
        )
        for decision, expected_status in cases:
            with self.subTest(kind=decision.kind):
                self.calls.clear()
                requester = RecordingApprovalRequester()
                context = self._context_with_requester(requester)
                definition = self._definition(
                    "write_file", SideEffectClass.WORKSPACE_WRITE
                )
                pipeline = self._pipeline(
                    definition,
                    governance=RecordingGovernance(self.calls, decision),
                )

                outcome = pipeline.execute(Action("1", definition.name, {}), context)

                self.assertEqual(self.calls, ["before_tool", "governance"])
                self.assertEqual(outcome.status, expected_status)

    def test_matching_grant_rechecks_governance_then_executes_handler_once(self):
        action = Action("1", "write_file", {})
        approval = PendingApproval(
            id="approval-1",
            step=3,
            action=action.action,
            path=None,
            risk_level="review",
            reason="review governance",
            profile="review",
            status="applying",
            action_payload={
                "schema_version": action.schema_version,
                "action": action.action,
                "args": action.args,
            },
        )
        grant = ApprovalGrant(
            approval.id,
            approval_action_digest(approval.action_payload),
            2,
        )
        context = self._context_with_requester(
            RecordingApprovalRequester(),
            approved_request=approval,
            approval_grant=grant,
        )
        decision = GovernanceDecision(
            GovernanceDecisionKind.REQUIRE_APPROVAL,
            "review",
            approval.reason,
            "none",
        )
        definition = self._definition(
            "write_file", SideEffectClass.WORKSPACE_WRITE
        )

        outcome = self._pipeline(
            definition,
            governance=RecordingGovernance(self.calls, decision),
        ).execute(action, context)

        self.assertEqual(
            self.calls,
            ["before_tool", "governance", "handler", "after_tool", "gate", "after_gate"],
        )
        self.assertEqual(outcome.status, ExecutionStatus.SUCCEEDED)

    def test_grant_cannot_bypass_new_block_or_a_different_approval_request(self):
        action = Action("1", "write_file", {})
        approval = PendingApproval(
            id="approval-1",
            step=3,
            action=action.action,
            path=None,
            risk_level="review",
            reason="original review",
            profile="review",
            status="applying",
            action_payload={
                "schema_version": action.schema_version,
                "action": action.action,
                "args": {"different": "payload"},
            },
        )
        context = self._context_with_requester(
            RecordingApprovalRequester(),
            approved_request=approval,
            approval_grant=ApprovalGrant(
                approval.id,
                approval_action_digest(approval.action_payload),
                2,
            ),
        )
        definition = self._definition(
            "write_file", SideEffectClass.WORKSPACE_WRITE
        )

        blocked = self._pipeline(
            definition,
            hooks=RecordingHooks(
                self.calls,
                BeforeToolDecision.block("new_block", "new hook block"),
            ),
        ).execute(action, context)

        self.assertEqual(blocked.status, ExecutionStatus.BLOCKED)
        self.assertEqual(self.calls, ["before_tool"])

        self.calls.clear()
        requester = RecordingApprovalRequester()
        changed = self._pipeline(
            definition,
            governance=RecordingGovernance(
                self.calls,
                GovernanceDecision(
                    GovernanceDecisionKind.REQUIRE_APPROVAL,
                    "review",
                    approval.reason,
                    "none",
                ),
            ),
        ).execute(
            action,
            self._context_with_requester(
                requester,
                approved_request=approval,
                approval_grant=context.approval_grant,
            ),
        )

        self.assertEqual(changed.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(self.calls, ["before_tool", "governance"])
        self.assertEqual(len(requester.requests), 1)

    def test_grant_is_consumed_once_and_does_not_bypass_gate(self):
        action = Action("1", "write_file", {})
        approval = PendingApproval(
            id="approval-1",
            step=3,
            action=action.action,
            path=None,
            risk_level="review",
            reason="same review",
            profile="review",
            status="applying",
            action_payload={
                "schema_version": action.schema_version,
                "action": action.action,
                "args": action.args,
            },
        )
        grant = ApprovalGrant(
            approval.id,
            approval_action_digest(approval.action_payload),
            2,
        )
        requester = RecordingApprovalRequester()
        context = self._context_with_requester(
            requester,
            approved_request=approval,
            approval_grant=grant,
        )
        definition = self._definition(
            "write_file", SideEffectClass.WORKSPACE_WRITE
        )
        approval_decision = GovernanceDecision(
            GovernanceDecisionKind.REQUIRE_APPROVAL,
            "review",
            approval.reason,
            "none",
        )
        hooks = RecordingHooks(
            self.calls,
            BeforeToolDecision.require_approval("review", approval.reason),
        )

        second_request = self._pipeline(
            definition,
            hooks=hooks,
            governance=RecordingGovernance(self.calls, approval_decision),
        ).execute(action, context)

        self.assertEqual(second_request.status, ExecutionStatus.APPROVAL_REQUIRED)
        self.assertEqual(self.calls, ["before_tool", "governance"])
        self.assertEqual(len(requester.requests), 1)

        self.calls.clear()
        gate_failure = GateResult(False, [], [], "still invalid")
        gate_outcome = self._pipeline(
            definition,
            governance=RecordingGovernance(self.calls, approval_decision),
            gate=RecordingGate(self.calls, gate_failure),
        ).execute(action, context)

        self.assertEqual(gate_outcome.status, ExecutionStatus.FAILED)
        self.assertEqual(gate_outcome.error.code, "gate_failed")
        self.assertIn("handler", self.calls)
        self.assertIn("gate", self.calls)

    def test_read_action_skips_gate(self):
        outcome = self._execute(
            self._definition("read_file", SideEffectClass.NONE)
        )

        self.assertEqual(
            self.calls,
            ["before_tool", "governance", "handler", "after_tool"],
        )
        self.assertEqual(outcome.status, ExecutionStatus.SUCCEEDED)
        self.assertIsNone(outcome.gate_result)

    def test_successful_finish_runs_gate_and_requests_finish(self):
        outcome = self._execute(
            self._definition("finish", SideEffectClass.RUN_CONTROL)
        )

        self.assertIn("gate", self.calls)
        self.assertTrue(outcome.state_delta.finish_requested)

    def test_non_finish_run_control_does_not_request_finish(self):
        outcome = self._execute(
            self._definition("control", SideEffectClass.RUN_CONTROL)
        )

        self.assertIn("gate", self.calls)
        self.assertIsNone(outcome.state_delta.finish_requested)

    def test_gate_failure_returns_repair_feedback_without_suspension(self):
        gate_result = GateResult(False, [], [], "repair index.html")
        outcome = self._execute(
            self._definition("finish", SideEffectClass.RUN_CONTROL),
            gate=RecordingGate(self.calls, gate_result),
        )

        self.assertEqual(outcome.status, ExecutionStatus.FAILED)
        self.assertEqual(outcome.gate_result, gate_result)
        self.assertEqual(outcome.feedback.kind, "gate_result")
        self.assertIn("repair index.html", str(outcome.feedback.payload))
        self.assertIsNone(outcome.state_delta.status)
        self.assertIsNone(outcome.state_delta.pending_approval_id)
        self.assertIsNone(outcome.state_delta.finish_requested)

    def test_preparation_validation_and_handler_failures_are_structured(self):
        unknown = self._pipeline(
            self._definition("unused", SideEffectClass.NONE),
            runtime=ToolRuntime(ToolRegistry()),
        ).execute(Action("1", "missing", {}), self.execution_context)

        self.assertEqual(unknown.status, ExecutionStatus.BLOCKED)
        self.assertEqual(unknown.error.code, "unknown_tool")
        self.assertEqual(self.calls, [])

        invalid_definition = ToolDefinition(
            ToolMetadata("invalid", "test tool"),
            PermissionClass.CONTROL,
            SideEffectClass.NONE,
            RequiredArgs,
            PayloadResult,
            RecordingHandler(self.calls),
        )
        invalid = self._pipeline(invalid_definition).execute(
            Action("1", "invalid", {}), self.execution_context
        )

        self.assertEqual(invalid.status, ExecutionStatus.BLOCKED)
        self.assertEqual(invalid.error.code, "tool_validation_failed")
        self.assertEqual(self.calls, [])

        self.calls.clear()
        definition = self._definition("read_file", SideEffectClass.NONE)
        runtime = mock.create_autospec(ToolRuntime, instance=True)
        runtime.prepare.return_value = ToolRuntime(ToolRegistry([definition])).prepare(
            Action("1", "read_file", {})
        )
        runtime.execute_prepared.return_value = ToolResult.failure(
            "read_file", "tool_execution_failed", message="read failed"
        )
        outcome = self._pipeline(definition, runtime=runtime).execute(
            Action("1", "read_file", {}), self.execution_context
        )

        self.assertEqual(outcome.status, ExecutionStatus.FAILED)
        self.assertEqual(outcome.error.code, "tool_execution_failed")
        self.assertEqual(self.calls, ["before_tool", "governance", "after_tool"])

    def test_state_conflicts_assertions_and_unknown_errors_propagate(self):
        definition = self._definition("read_file", SideEffectClass.NONE)
        exceptions = (
            RunStateConflict("stale state"),
            AssertionError("broken invariant"),
            RuntimeError("program error"),
        )
        for error in exceptions:
            with self.subTest(error=type(error).__name__):
                runtime = mock.create_autospec(ToolRuntime, instance=True)
                runtime.prepare.side_effect = error
                pipeline = self._pipeline(definition, runtime=runtime)

                with self.assertRaises(type(error)):
                    pipeline.execute(
                        Action("1", "read_file", {}), self.execution_context
                    )

    def test_unknown_hook_and_governance_decisions_do_not_expand_permissions(self):
        definition = self._definition("read_file", SideEffectClass.NONE)
        invalid_hook = RecordingHooks(
            self.calls,
            BeforeToolDecision("allow_override"),
        )
        invalid_governance = RecordingGovernance(
            self.calls,
            GovernanceDecision(
                "allow_override",
                "invalid",
                "invalid governance decision",
                "governance",
            ),
        )

        with self.assertRaises(AssertionError):
            self._pipeline(definition, hooks=invalid_hook).execute(
                Action("1", "read_file", {}), self.execution_context
            )
        self.assertEqual(self.calls, ["before_tool"])

        self.calls.clear()
        with self.assertRaises(AssertionError):
            self._pipeline(definition, governance=invalid_governance).execute(
                Action("1", "read_file", {}), self.execution_context
            )
        self.assertEqual(self.calls, ["before_tool", "governance"])

    def test_every_observation_is_redacted_before_state_delta(self):
        secret = "sk-secret-pipeline-1234567890"
        gate_result = GateResult(False, [], [], f"repair {secret}")
        definition = self._definition(
            "write_file",
            SideEffectClass.WORKSPACE_WRITE,
            RecordingHandler(self.calls, {"value": secret}),
        )

        outcome = self._execute(
            definition,
            gate=RecordingGate(self.calls, gate_result),
        )

        self.assertGreaterEqual(len(outcome.state_delta.append_observations), 2)
        for observation in outcome.state_delta.append_observations:
            self.assertNotIn(secret, str(observation.payload))
        self.assertNotIn(secret, str(outcome.feedback.payload))

    def test_execution_context_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.execution_context.step = 4

    def test_execution_context_rejects_a_different_tool_policy(self):
        other_policy = WorkspacePolicy(
            self.root / "other",
            set(self.policy.allowed_actions),
            set(self.policy.allowed_read_paths),
            set(self.policy.allowed_write_paths),
        )

        with self.assertRaises(ValueError):
            PipelineExecutionContext(
                event_context=self.execution_context.event_context,
                step=self.execution_context.step,
                capabilities=self.execution_context.capabilities,
                policy=self.policy,
                governance_config=self.execution_context.governance_config,
                tool_context=ToolExecutionContext(other_policy, None),
                gate_context=self.execution_context.gate_context,
            )

    def test_execution_context_rejects_a_different_gate_policy(self):
        other_policy = WorkspacePolicy(
            self.root,
            set(self.policy.allowed_actions),
            {"different.html"},
            set(self.policy.allowed_write_paths),
        )

        with self.assertRaises(ValueError):
            PipelineExecutionContext(
                event_context=self.execution_context.event_context,
                step=self.execution_context.step,
                capabilities=self.execution_context.capabilities,
                policy=self.policy,
                governance_config=self.execution_context.governance_config,
                tool_context=self.execution_context.tool_context,
                gate_context=GateContext(self.root, other_policy),
            )

    def _context_with_requester(
        self,
        requester,
        *,
        approved_request=None,
        approval_grant=None,
    ):
        return PipelineExecutionContext(
            event_context=self.execution_context.event_context,
            step=self.execution_context.step,
            capabilities=self.execution_context.capabilities,
            policy=self.execution_context.policy,
            governance_config=self.execution_context.governance_config,
            tool_context=self.execution_context.tool_context,
            gate_context=self.execution_context.gate_context,
            approval_requester=requester,
            approved_request=approved_request,
            approval_grant=approval_grant,
        )


class ValidationPolicyTests(unittest.TestCase):
    def test_validation_depends_only_on_side_effect_class(self):
        policy = DefaultValidationPolicy()
        for side_effect, expected in (
            (SideEffectClass.NONE, False),
            (SideEffectClass.WORKSPACE_WRITE, True),
            (SideEffectClass.RUN_CONTROL, True),
        ):
            with self.subTest(side_effect=side_effect):
                definition = ToolDefinition(
                    ToolMetadata("arbitrary_name", "test"),
                    PermissionClass.CONTROL,
                    side_effect,
                    EmptyArgs,
                    PayloadResult,
                    RecordingHandler([]),
                )
                call = ToolRuntime(ToolRegistry([definition])).prepare(
                    Action("1", "arbitrary_name", {})
                ).call

                self.assertEqual(
                    policy.should_validate(
                        call, ToolResult.success("arbitrary_name", {"value": "ok"})
                    ),
                    expected,
                )


class HtmlGateRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_unreadable_artifact_returns_failed_result_without_gate_call(self):
        policy = WorkspacePolicy(self.root, set(), {"CHECKLIST.md"}, set())

        with mock.patch("specgate.gate.run_html_gate") as run_gate:
            result = HtmlGateRunner().run(GateContext(self.root, policy))

        self.assertFalse(result.passed)
        self.assertEqual(result.issues[0].code, "artifact_not_readable")
        run_gate.assert_not_called()

    def test_gate_context_rejects_a_root_outside_its_policy(self):
        policy = WorkspacePolicy(
            self.root,
            set(),
            {"index.html", "CHECKLIST.md"},
            set(),
        )

        with self.assertRaises(ValueError):
            GateContext(self.root / "outside", policy)

    def test_only_policy_readable_checklist_is_passed_to_existing_gate(self):
        passing = GateResult(True, [], [], "passed")
        readable_policy = WorkspacePolicy(
            self.root, set(), {"index.html", "CHECKLIST.md"}, set()
        )
        unreadable_policy = WorkspacePolicy(
            self.root, set(), {"index.html"}, set()
        )

        with mock.patch("specgate.gate.run_html_gate", return_value=passing) as run_gate:
            HtmlGateRunner().run(GateContext(self.root, readable_policy))
            HtmlGateRunner().run(GateContext(self.root, unreadable_policy))

        self.assertEqual(
            run_gate.call_args_list,
            [
                mock.call(self.root / "index.html", self.root / "CHECKLIST.md"),
                mock.call(self.root / "index.html", None),
            ],
        )


if __name__ == "__main__":
    unittest.main()
