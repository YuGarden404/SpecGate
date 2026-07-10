from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from specgate.actions import ActionParseError, parse_action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    approval_queue_path,
    classify_action_risk,
    preview_args,
)
from specgate.context import build_context_pack_with_metadata
from specgate.gate import GateResult, run_html_gate
from specgate.llm import LLMClient
from specgate.memory import append_memory
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary, build_trust_summary, classify_rule_family
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore, redact


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
        retrieval_path = self.run_dir / "retrieval.json"
        if retrieval_path.exists():
            retrieval_path.unlink()
        compression_path = self.run_dir / "compression.json"
        if compression_path.exists():
            compression_path.unlink()
        isolation_path = self.run_dir / "isolation.json"
        if isolation_path.exists():
            isolation_path.unlink()

    def run(self) -> RunResult:
        queue_path = approval_queue_path(self.root)
        if queue_path.exists():
            queue_path.unlink()

        latest_gate: GateResult | None = None
        runtime_feedback: list[dict] = []
        context_chars_max = 0
        metrics = RunMetrics()
        permission_decisions: list[PermissionDecision] = []

        def run_gate(step: int) -> GateResult:
            nonlocal metrics
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
                return gate
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
            return gate

        def finish_result(step: int, final_gate: GateResult, current_metrics: RunMetrics) -> RunResult:
            trust = build_trust_summary(final_gate.passed, current_metrics)
            self.trace.append(
                "run_summary",
                {
                    "profile": self.governance_profile,
                    "metrics": current_metrics.to_dict(),
                    "trust": trust.to_dict(),
                },
            )
            result = RunResult(
                final_gate.passed,
                step,
                final_gate,
                current_metrics.context_chars_max,
                current_metrics,
                permission_decisions,
                trust,
                self.governance_profile,
            )
            append_memory(self.root, result.passed, result.steps, final_gate.summary)
            return result

        def record_tool_feedback(
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

        def record_permission_decision(
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

        def record_retrieval(metadata: dict | None) -> None:
            nonlocal metrics
            if not metadata:
                return
            retrieval = metadata.get("retrieval")
            if not isinstance(retrieval, dict):
                return
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

        def record_compression(metadata: dict | None) -> None:
            nonlocal metrics
            if not metadata:
                return
            compression = metadata.get("compression")
            if not isinstance(compression, dict):
                return
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

        def record_isolation(metadata: dict | None) -> None:
            nonlocal metrics
            if not metadata:
                return
            isolation = metadata.get("isolation")
            if not isinstance(isolation, dict):
                return
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

        for step in range(1, self.max_steps + 1):
            context, context_metadata = build_context_pack_with_metadata(
                self.root,
                latest_gate,
                runtime_feedback,
                strategy=self.context_strategy,
                policy=self.policy,
            )
            record_retrieval(context_metadata)
            record_compression(context_metadata)
            record_isolation(context_metadata)
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
                approval = PendingApproval(
                    id=f"approval-step-{step}",
                    step=step,
                    action=action.action,
                    path=action_path,
                    risk_level=risk.level,
                    reason=risk.reason,
                    profile=self.governance_profile,
                    arguments_preview=preview_args(action.args),
                )
                queue = ApprovalQueue.read(queue_path).append(approval)
                queue.write(queue_path)
                record_permission_decision(
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
                self.trace.append("approval_requested", event)
                continue

            if risk.level in {"review", "blocked"}:
                metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
                record_permission_decision(
                    step,
                    action.action,
                    action_path,
                    ok=False,
                    blocked=True,
                    message=risk.reason,
                )
                record_tool_feedback(
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
            record_permission_decision(
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
                latest_gate = run_gate(step)

            if action.action == "finish":
                if latest_gate is None:
                    latest_gate = run_gate(step)
                return finish_result(step, latest_gate, metrics)

        if latest_gate is None:
            latest_gate = run_gate(self.max_steps)
        metrics = replace(metrics, max_steps_reached=True)
        return finish_result(self.max_steps, latest_gate, metrics)
