from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from specgate.actions import Action, ActionParseError, parse_action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    approval_queue_path,
    capture_target_state,
    classify_action_risk,
    preview_args,
    target_state_matches,
)
from specgate.context import build_context_pack_with_metadata, build_role_context_pack_with_metadata
from specgate.gate import GateResult, run_html_gate
from specgate.isolation import RoleExecution, action_allowed_for_role, build_isolation_evidence, role_context_for
from specgate.llm import LLMClient
from specgate.memory import append_memory
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary, build_trust_summary, classify_rule_family
from specgate.multi_agent import MultiAgentState, phase_for_role, summary_requests_repair
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore, redact


def _utc_now_for_runner() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique_approval_id(queue: ApprovalQueue, step: int) -> str:
    base = f"approval-step-{step}"
    existing = {approval.id for approval in queue.approvals}
    if base not in existing:
        return base

    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


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


class AgentRunner:
    def __init__(
        self,
        root: Path,
        llm: LLMClient,
        policy: WorkspacePolicy,
        max_steps: int = 5,
        context_strategy: str = "baseline",
        governance_profile: str | None = None,
        governance_config: GovernanceConfig | None = None,
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
        self.run_dir = root / "runs" / "latest"
        self.trace = TraceStore(self.run_dir / "trace.jsonl", reset=True)
        self._reset_run_artifacts()

    def run(self) -> RunResult:
        if self.context_strategy == "multi-agent-isolated":
            return self._run_multi_agent_loop(reset_queue=True)
        return self._run_loop(reset_queue=True)

    def _reset_run_artifacts(self) -> None:
        for name in ("retrieval.json", "compression.json", "isolation.json"):
            path = self.run_dir / name
            if path.exists():
                path.unlink()

    def _reset_approval_queue(self) -> None:
        queue_path = approval_queue_path(self.root)
        if queue_path.exists():
            queue_path.unlink()

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
        passed = final_gate.passed and not metrics.max_steps_reached and not metrics.role_cycle_limit_reached
        result = RunResult(
            passed,
            step,
            final_gate,
            metrics.context_chars_max,
            metrics,
            permission_decisions,
            trust,
            self.governance_profile,
        )
        append_memory(self.root, result.passed, result.steps, final_gate.summary)
        return result

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

    def _record_permission_decision(
        self,
        permission_decisions: list[PermissionDecision],
        step: int,
        action_name: str,
        action_path: str | None,
        ok: bool,
        blocked: bool,
        message: str,
    ) -> None:
        decision = PermissionDecision(
            step=step,
            action=action_name,
            path=action_path,
            allowed=ok and not blocked,
            blocked=blocked,
            reason=message,
            profile=self.governance_profile,
            rule_family=classify_rule_family(message),
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
        (self.run_dir / "retrieval.json").write_text(
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
        (self.run_dir / "compression.json").write_text(
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
        (self.run_dir / "isolation.json").write_text(
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

    def _execute_agent_action(
        self,
        step: int,
        action: Action,
        metrics: RunMetrics,
        runtime_feedback: list[dict],
        permission_decisions: list[PermissionDecision],
        latest_gate: GateResult | None,
    ) -> tuple[GateResult | None, RunMetrics]:
        action_path_value = action.args.get("path")
        action_path = action_path_value if isinstance(action_path_value, str) else None
        risk = classify_action_risk(action, self.policy, self.governance_config)
        queue_path = approval_queue_path(self.root)
        if risk.level == "review" and self.governance_profile == "review":
            queue = ApprovalQueue.read(queue_path)
            approval = PendingApproval(
                id=_unique_approval_id(queue, step),
                step=step,
                action=action.action,
                path=action_path,
                risk_level=risk.level,
                reason=risk.reason,
                profile=self.governance_profile,
                arguments_preview=preview_args(action.args),
                action_payload={
                    "schema_version": action.schema_version,
                    "action": action.action,
                    "args": action.args,
                },
                target_state=capture_target_state(self.root, action_path),
            )
            queue.append(approval).write(queue_path)
            self._record_permission_decision(
                permission_decisions,
                step,
                action.action,
                action_path,
                ok=False,
                blocked=False,
                message=risk.reason,
            )
            metrics = replace(
                metrics,
                approval_requests=metrics.approval_requests + 1,
                pending_approvals=metrics.pending_approvals + 1,
            )
            event = {
                "step": step,
                "type": "approval_requested",
                "approval": approval.to_dict(),
            }
            runtime_feedback.append(redact(event))
            self.trace.append("approval_requested", redact(event))
            return latest_gate, metrics

        if risk.level in {"review", "blocked"}:
            metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
            self._record_permission_decision(
                permission_decisions,
                step,
                action.action,
                action_path,
                ok=False,
                blocked=True,
                message=risk.reason,
            )
            self._record_tool_feedback(
                runtime_feedback,
                step,
                action.action,
                ok=False,
                blocked=True,
                message=risk.reason,
                data={"risk": risk.to_dict()},
            )
            return latest_gate, metrics

        tool_result = self.dispatcher.dispatch(action)
        metrics = replace(
            metrics,
            tool_calls=metrics.tool_calls + 1,
            successful_tool_calls=metrics.successful_tool_calls + (1 if tool_result.ok else 0),
            blocked_actions=metrics.blocked_actions + (1 if tool_result.blocked else 0),
            finish_actions=metrics.finish_actions + (1 if action.action == "finish" else 0),
        )
        self._record_permission_decision(
            permission_decisions,
            step=step,
            action_name=action.action,
            action_path=action_path,
            ok=tool_result.ok,
            blocked=tool_result.blocked,
            message=tool_result.message,
        )
        runtime_feedback.append(
            redact(
                {
                    "step": step,
                    "type": "tool_result",
                    "action": tool_result.action,
                    "ok": tool_result.ok,
                    "blocked": tool_result.blocked,
                    "message": tool_result.message,
                    "data": tool_result.data,
                }
            )
        )
        self.trace.append("tool_result", {"step": step, "result": tool_result.__dict__})

        if action.action in {"write_file", "replace_file"} and not tool_result.blocked:
            latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
        return latest_gate, metrics

    def _run_multi_agent_role_once(
        self,
        step: int,
        role: str,
        state: MultiAgentState,
        latest_gate: GateResult | None,
        metrics: RunMetrics,
        runtime_feedback: list[dict],
        permission_decisions: list[PermissionDecision],
    ) -> tuple[GateResult | None, RunMetrics, bool]:
        phase = phase_for_role(role)
        role_context = role_context_for(role)
        self.trace.append("role_started", {"step": step, "role": role, "phase": phase})
        context, context_metadata = build_role_context_pack_with_metadata(
            self.root,
            role=role,
            shared_state=state.to_shared_state(),
            latest_gate=latest_gate,
            runtime_feedback=runtime_feedback,
            strategy=self.context_strategy,
            policy=self.policy,
        )
        metrics = self._record_retrieval(metrics, context_metadata)
        metrics = self._record_compression(metrics, context_metadata)
        context_chars = len(context)
        metrics = replace(
            metrics,
            steps=step,
            context_chars_max=max(metrics.context_chars_max, context_chars),
            role_runs=metrics.role_runs + 1,
            planner_runs=metrics.planner_runs + (1 if role == "planner" else 0),
            implementer_runs=metrics.implementer_runs + (1 if role == "implementer" else 0),
            reviewer_runs=metrics.reviewer_runs + (1 if role == "reviewer" else 0),
        )
        self.trace.append(
            "role_context_built",
            {"step": step, "role": role, "phase": phase, "context_chars": context_chars},
        )
        raw = self.llm.complete(context)
        metrics = replace(metrics, llm_calls=metrics.llm_calls + 1)
        self.trace.append("llm_response", {"step": step, "role": role, "phase": phase, "text": raw})

        try:
            action = parse_action(raw)
        except ActionParseError as exc:
            metrics = replace(metrics, parse_errors=metrics.parse_errors + 1)
            event = {"step": step, "role": role, "phase": phase, "type": "parse_error", "error": str(exc)}
            runtime_feedback.append(redact(event))
            self.trace.append("parse_error", event)
            return latest_gate, metrics, False

        summary_value = action.args.get("summary", "")
        summary = summary_value if isinstance(summary_value, str) else ""
        allowed_by_role = action_allowed_for_role(role, action.action)
        execution = RoleExecution(
            role=role,
            phase=phase,
            context_chars=context_chars,
            visible_sections=role_context.visible_sections,
            allowed_actions=role_context.allowed_actions,
            attempted_action=action.action,
            action_allowed_by_role=allowed_by_role,
            blocked_reason=None if allowed_by_role else f"role {role} cannot perform {action.action}",
            summary=summary or None,
        )
        state.executions.append(execution)
        self.trace.append("role_action", execution.to_dict())

        if not allowed_by_role:
            metrics = replace(metrics, role_blocked_actions=metrics.role_blocked_actions + 1)
            self.trace.append("role_action_blocked", execution.to_dict())
            runtime_feedback.append(redact({"step": step, "type": "role_action_blocked", **execution.to_dict()}))
            return latest_gate, metrics, False

        if role == "planner" and action.action == "finish":
            state.plan = summary
            metrics = replace(metrics, finish_actions=metrics.finish_actions + 1)
            self.trace.append("role_finished", execution.to_dict())
            return latest_gate, metrics, True

        if role == "reviewer" and action.action == "finish":
            state.review_notes = summary
            state.repair_requested = summary_requests_repair(summary)
            metrics = replace(metrics, finish_actions=metrics.finish_actions + 1)
            self.trace.append("role_finished", execution.to_dict())
            return latest_gate, metrics, True

        if role == "implementer":
            latest_gate, metrics = self._execute_agent_action(
                step,
                action,
                metrics,
                runtime_feedback,
                permission_decisions,
                latest_gate,
            )
            self.trace.append("role_finished", execution.to_dict())
            return latest_gate, metrics, True

        return latest_gate, metrics, False

    def _run_multi_agent_loop(self, reset_queue: bool) -> RunResult:
        if reset_queue:
            self._reset_approval_queue()

        runtime_feedback: list[dict] = []
        permission_decisions: list[PermissionDecision] = []
        metrics = RunMetrics()
        latest_gate: GateResult | None = None
        state = MultiAgentState()
        max_role_cycles = 2
        step = 0

        def finish_with_isolation(final_step: int, final_metrics: RunMetrics) -> RunResult:
            nonlocal latest_gate
            if latest_gate is None:
                latest_gate, final_metrics = self._run_gate_with_feedback(final_step, final_metrics, runtime_feedback)
            evidence = build_isolation_evidence(
                strategy=self.context_strategy,
                executions=state.executions,
                review_repairs=state.review_repairs,
            )
            final_metrics = self._record_isolation(final_metrics, {"isolation": redact(evidence)})
            return self._finish_result(final_step, latest_gate, final_metrics, permission_decisions)

        def run_role_if_budget(role: str) -> bool:
            nonlocal latest_gate, metrics, step
            if step >= self.max_steps:
                metrics = replace(metrics, max_steps_reached=True)
                self.trace.append(
                    "role_step_limit_reached",
                    {"step": step, "max_steps": self.max_steps, "next_role": role},
                )
                return False
            step += 1
            latest_gate, metrics, role_completed = self._run_multi_agent_role_once(
                step,
                role,
                state,
                latest_gate,
                metrics,
                runtime_feedback,
                permission_decisions,
            )
            return role_completed

        run_role_if_budget("planner")

        while True:
            run_role_if_budget("implementer")
            if metrics.max_steps_reached:
                return finish_with_isolation(step, metrics)

            state.repair_requested = False
            reviewer_completed = run_role_if_budget("reviewer")
            if metrics.max_steps_reached:
                return finish_with_isolation(step, metrics)
            if not reviewer_completed:
                metrics = replace(metrics, max_steps_reached=True)
                self.trace.append("reviewer_failed", {"step": step})
                return finish_with_isolation(step, metrics)

            if not state.repair_requested:
                return finish_with_isolation(step, metrics)

            if state.review_repairs >= max_role_cycles - 1:
                metrics = replace(metrics, role_cycle_limit_reached=True, max_steps_reached=True)
                self.trace.append("role_cycle_limit_reached", {"review_repairs": state.review_repairs})
                return finish_with_isolation(step, metrics)

            state.review_repairs += 1
            metrics = replace(metrics, review_repairs=state.review_repairs)
            self.trace.append(
                "role_repair_requested",
                {"review_repairs": state.review_repairs, "review_notes": redact(state.review_notes)},
            )
            state.repair_requested = False

    def _run_loop(
        self,
        reset_queue: bool,
        initial_runtime_feedback: list[dict] | None = None,
        initial_metrics: RunMetrics | None = None,
        initial_permission_decisions: list[PermissionDecision] | None = None,
        latest_gate: GateResult | None = None,
    ) -> RunResult:
        queue_path = approval_queue_path(self.root)
        if reset_queue:
            self._reset_approval_queue()

        runtime_feedback: list[dict] = list(initial_runtime_feedback or [])
        metrics = initial_metrics or RunMetrics()
        context_chars_max = metrics.context_chars_max
        permission_decisions: list[PermissionDecision] = list(initial_permission_decisions or [])

        for step in range(1, self.max_steps + 1):
            context, context_metadata = build_context_pack_with_metadata(
                self.root,
                latest_gate,
                runtime_feedback,
                strategy=self.context_strategy,
                policy=self.policy,
            )
            metrics = self._record_retrieval(metrics, context_metadata)
            metrics = self._record_compression(metrics, context_metadata)
            metrics = self._record_isolation(metrics, context_metadata)
            context_chars = len(context)
            context_chars_max = max(context_chars_max, context_chars)
            metrics = replace(metrics, steps=step, context_chars_max=context_chars_max)
            self.trace.append(
                "context_built",
                {"step": step, "strategy": self.context_strategy, "context_chars": context_chars},
            )
            raw = self.llm.complete(context)
            metrics = replace(metrics, llm_calls=metrics.llm_calls + 1)
            self.trace.append("llm_response", {"step": step, "text": raw})

            try:
                action = parse_action(raw)
            except ActionParseError as exc:
                metrics = replace(metrics, parse_errors=metrics.parse_errors + 1)
                event = {"step": step, "type": "parse_error", "error": str(exc)}
                runtime_feedback.append(redact(event))
                self.trace.append("parse_error", event)
                continue

            action_path_value = action.args.get("path")
            action_path = action_path_value if isinstance(action_path_value, str) else None
            risk = classify_action_risk(action, self.policy, self.governance_config)
            if risk.level == "review" and self.governance_profile == "review":
                queue = ApprovalQueue.read(queue_path)
                approval = PendingApproval(
                    id=_unique_approval_id(queue, step),
                    step=step,
                    action=action.action,
                    path=action_path,
                    risk_level=risk.level,
                    reason=risk.reason,
                    profile=self.governance_profile,
                    arguments_preview=preview_args(action.args),
                    action_payload={
                        "schema_version": action.schema_version,
                        "action": action.action,
                        "args": action.args,
                    },
                    target_state=capture_target_state(self.root, action_path),
                )
                queue.append(approval).write(queue_path)
                self._record_permission_decision(
                    permission_decisions,
                    step,
                    action.action,
                    action_path,
                    ok=False,
                    blocked=False,
                    message=risk.reason,
                )
                metrics = replace(
                    metrics,
                    approval_requests=metrics.approval_requests + 1,
                    pending_approvals=metrics.pending_approvals + 1,
                )
                event = {
                    "step": step,
                    "type": "approval_requested",
                    "approval": approval.to_dict(),
                }
                runtime_feedback.append(redact(event))
                self.trace.append("approval_requested", redact(event))
                continue

            if risk.level in {"review", "blocked"}:
                metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
                self._record_permission_decision(
                    permission_decisions,
                    step,
                    action.action,
                    action_path,
                    ok=False,
                    blocked=True,
                    message=risk.reason,
                )
                self._record_tool_feedback(
                    runtime_feedback,
                    step,
                    action.action,
                    ok=False,
                    blocked=True,
                    message=risk.reason,
                    data={"risk": risk.to_dict()},
                )
                continue

            tool_result = self.dispatcher.dispatch(action)
            metrics = replace(
                metrics,
                tool_calls=metrics.tool_calls + 1,
                successful_tool_calls=metrics.successful_tool_calls + (1 if tool_result.ok else 0),
                blocked_actions=metrics.blocked_actions + (1 if tool_result.blocked else 0),
                finish_actions=metrics.finish_actions + (1 if action.action == "finish" else 0),
            )
            action_path_value = action.args.get("path")
            action_path = action_path_value if isinstance(action_path_value, str) else None
            self._record_permission_decision(
                permission_decisions,
                step=step,
                action_name=action.action,
                action_path=action_path,
                ok=tool_result.ok,
                blocked=tool_result.blocked,
                message=tool_result.message,
            )
            runtime_feedback.append(
                redact(
                    {
                        "step": step,
                        "type": "tool_result",
                        "action": tool_result.action,
                        "ok": tool_result.ok,
                        "blocked": tool_result.blocked,
                        "message": tool_result.message,
                        "data": tool_result.data,
                    }
                )
            )
            self.trace.append("tool_result", {"step": step, "result": tool_result.__dict__})

            if action.action in {"write_file", "replace_file"} and not tool_result.blocked:
                latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)

            if action.action == "finish":
                if latest_gate is None:
                    latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
                return self._finish_result(step, latest_gate, metrics, permission_decisions)

        if latest_gate is None:
            latest_gate, metrics = self._run_gate_with_feedback(self.max_steps, metrics, runtime_feedback)
        metrics = replace(metrics, max_steps_reached=True)
        return self._finish_result(self.max_steps, latest_gate, metrics, permission_decisions)

    def resume_from_approval(self) -> RunResult:
        queue_path = approval_queue_path(self.root)
        queue = ApprovalQueue.read(queue_path)
        approval = queue.next_resume_candidate()
        if approval is None:
            raise ValueError("no approved or denied approval to resume")

        runtime_feedback: list[dict] = []
        permission_decisions: list[PermissionDecision] = []
        metrics = RunMetrics()
        started = {
            "approval_id": approval.id,
            "status": approval.status,
            "action": approval.action,
            "path": approval.path,
        }
        self.trace.append("resume_started", redact(started))

        if approval.status == "denied":
            metrics = replace(metrics, denied_approvals=1)
            reason = approval.decision_reason or "human denied"
            event = {
                "type": "approval_denied",
                "approval_id": approval.id,
                "action": approval.action,
                "path": approval.path,
                "reason": reason,
            }
            redacted_event = redact(event)
            runtime_feedback.append(redacted_event)
            self.trace.append("approval_denied", redacted_event)
            ApprovalQueue.read(queue_path).resolve(
                approval.id,
                "rejected",
                resolved_at=_utc_now_for_runner(),
                reason=reason,
            ).write(queue_path)
            self.trace.append(
                "resume_finished",
                redact({"approval_id": approval.id, "status": "rejected"}),
            )
            return self._run_loop(
                reset_queue=False,
                initial_runtime_feedback=runtime_feedback,
                initial_metrics=metrics,
                initial_permission_decisions=permission_decisions,
            )

        if not target_state_matches(self.root, approval.target_state):
            reason = f"target file changed since approval request: {approval.path}"
            metrics = replace(
                metrics,
                approved_approvals=1,
                failed_approvals=1,
                blocked_actions=1,
            )
            decision = PermissionDecision(
                step=approval.step,
                action=approval.action,
                path=approval.path,
                allowed=False,
                blocked=True,
                reason=reason,
                profile=self.governance_profile,
                rule_family=classify_rule_family(reason),
            )
            permission_decisions.append(decision)
            self.trace.append("permission_decision", decision.to_dict())
            event = {
                "type": "approval_failed",
                "approval_id": approval.id,
                "action": approval.action,
                "path": approval.path,
                "reason": reason,
            }
            redacted_event = redact(event)
            runtime_feedback.append(redacted_event)
            self.trace.append("approval_failed", redacted_event)
            ApprovalQueue.read(queue_path).resolve(
                approval.id,
                "failed",
                resolved_at=_utc_now_for_runner(),
                reason=reason,
            ).write(queue_path)
            self.trace.append(
                "resume_finished",
                redact({"approval_id": approval.id, "status": "failed"}),
            )
            return self._run_loop(
                reset_queue=False,
                initial_runtime_feedback=runtime_feedback,
                initial_metrics=metrics,
                initial_permission_decisions=permission_decisions,
            )

        action = parse_action(json.dumps(approval.action_payload))
        action_path_value = action.args.get("path")
        action_path = action_path_value if isinstance(action_path_value, str) else None
        risk = classify_action_risk(action, self.policy, self.governance_config)
        if risk.level == "blocked":
            metrics = replace(
                metrics,
                approved_approvals=1,
                failed_approvals=1,
                blocked_actions=1,
            )
            decision = PermissionDecision(
                step=approval.step,
                action=action.action,
                path=action_path,
                allowed=False,
                blocked=True,
                reason=risk.reason,
                profile=self.governance_profile,
                rule_family=classify_rule_family(risk.reason),
            )
            permission_decisions.append(decision)
            self.trace.append("permission_decision", decision.to_dict())
            event = {
                "type": "approval_failed",
                "approval_id": approval.id,
                "action": action.action,
                "path": action_path,
                "reason": risk.reason,
            }
            redacted_event = redact(event)
            runtime_feedback.append(redacted_event)
            self.trace.append("approval_failed", redacted_event)
            ApprovalQueue.read(queue_path).resolve(
                approval.id,
                "failed",
                resolved_at=_utc_now_for_runner(),
                reason=risk.reason,
            ).write(queue_path)
            self.trace.append(
                "resume_finished",
                redact({"approval_id": approval.id, "status": "failed"}),
            )
            return self._run_loop(
                reset_queue=False,
                initial_runtime_feedback=runtime_feedback,
                initial_metrics=metrics,
                initial_permission_decisions=permission_decisions,
            )

        tool_result = self.dispatcher.dispatch(action)
        status = "applied" if tool_result.ok and not tool_result.blocked else "failed"
        metrics = replace(
            metrics,
            approved_approvals=1,
            applied_approvals=1 if status == "applied" else 0,
            failed_approvals=1 if status == "failed" else 0,
            tool_calls=1,
            successful_tool_calls=1 if tool_result.ok else 0,
            blocked_actions=1 if tool_result.blocked else 0,
            finish_actions=1 if action.action == "finish" else 0,
        )
        decision = PermissionDecision(
            step=approval.step,
            action=action.action,
            path=action_path,
            allowed=tool_result.ok and not tool_result.blocked,
            blocked=tool_result.blocked,
            reason=tool_result.message,
            profile=self.governance_profile,
            rule_family=classify_rule_family(tool_result.message),
        )
        permission_decisions.append(decision)
        self.trace.append("permission_decision", decision.to_dict())
        event_type = "approval_applied" if status == "applied" else "approval_failed"
        event = {
            "type": event_type,
            "approval_id": approval.id,
            "action": action.action,
            "path": action_path,
            "ok": tool_result.ok,
            "blocked": tool_result.blocked,
            "message": tool_result.message,
            "data": tool_result.data,
        }
        redacted_event = redact(event)
        runtime_feedback.append(redacted_event)
        self.trace.append(event_type, redacted_event)
        ApprovalQueue.read(queue_path).resolve(
            approval.id,
            status,
            resolved_at=_utc_now_for_runner(),
            reason=None if status == "applied" else tool_result.message,
        ).write(queue_path)
        self.trace.append(
            "resume_finished",
            redact({"approval_id": approval.id, "status": status}),
        )
        return self._run_loop(
            reset_queue=False,
            initial_runtime_feedback=runtime_feedback,
            initial_metrics=metrics,
            initial_permission_decisions=permission_decisions,
        )
