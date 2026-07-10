from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from specgate.actions import ActionParseError, parse_action
from specgate.context import build_context_pack
from specgate.gate import GateResult, run_html_gate
from specgate.llm import LLMClient
from specgate.memory import append_memory
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary, build_trust_summary, classify_rule_family
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore


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
        governance_profile: str = "strict",
    ):
        self.root = root
        self.llm = llm
        self.policy = policy
        self.max_steps = max_steps
        self.context_strategy = context_strategy
        self.governance_profile = governance_profile
        snapshot = FileSnapshot.capture(root, policy.allowed_write_paths)
        self.dispatcher = ToolDispatcher(policy, snapshot)
        self.trace = TraceStore(root / "runs" / "latest" / "trace.jsonl", reset=True)

    def run(self) -> RunResult:
        latest_gate: GateResult | None = None
        runtime_feedback: list[dict] = []
        context_chars_max = 0
        metrics = RunMetrics()
        permission_decisions: list[PermissionDecision] = []

        def run_gate(step: int) -> GateResult:
            nonlocal metrics
            gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
            metrics = replace(
                metrics,
                gate_runs=metrics.gate_runs + 1,
                gate_failures=metrics.gate_failures + (0 if gate.passed else 1),
            )
            runtime_feedback.append(
                {
                    "step": step,
                    "type": "gate_result",
                    "passed": gate.passed,
                    "summary": gate.summary,
                }
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

        for step in range(1, self.max_steps + 1):
            context = build_context_pack(
                self.root,
                latest_gate,
                runtime_feedback,
                strategy=self.context_strategy,
            )
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
                runtime_feedback.append(event)
                self.trace.append("parse_error", event)
                continue

            tool_result = self.dispatcher.dispatch(action)
            metrics = replace(
                metrics,
                tool_calls=metrics.tool_calls + 1,
                successful_tool_calls=metrics.successful_tool_calls + (1 if tool_result.ok else 0),
                blocked_actions=metrics.blocked_actions + (1 if tool_result.blocked else 0),
                finish_actions=metrics.finish_actions + (1 if action.action == "finish" else 0),
            )
            action_path = action.args.get("path")
            decision = PermissionDecision(
                step=step,
                action=action.action,
                path=action_path if isinstance(action_path, str) else None,
                allowed=tool_result.ok and not tool_result.blocked,
                blocked=tool_result.blocked,
                reason=tool_result.message,
                profile=self.governance_profile,
                rule_family=classify_rule_family(tool_result.message),
            )
            permission_decisions.append(decision)
            self.trace.append("permission_decision", decision.to_dict())
            runtime_feedback.append(
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
