from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specgate.actions import ActionParseError, parse_action
from specgate.context import build_context_pack
from specgate.gate import GateResult, run_html_gate
from specgate.llm import LLMClient
from specgate.memory import append_memory
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


class AgentRunner:
    def __init__(
        self,
        root: Path,
        llm: LLMClient,
        policy: WorkspacePolicy,
        max_steps: int = 5,
        context_strategy: str = "baseline",
    ):
        self.root = root
        self.llm = llm
        self.policy = policy
        self.max_steps = max_steps
        self.context_strategy = context_strategy
        snapshot = FileSnapshot.capture(root, policy.allowed_write_paths)
        self.dispatcher = ToolDispatcher(policy, snapshot)
        self.trace = TraceStore(root / "runs" / "latest" / "trace.jsonl", reset=True)

    def run(self) -> RunResult:
        latest_gate: GateResult | None = None
        runtime_feedback: list[dict] = []
        context_chars_max = 0
        for step in range(1, self.max_steps + 1):
            context = build_context_pack(
                self.root,
                latest_gate,
                runtime_feedback,
                strategy=self.context_strategy,
            )
            context_chars = len(context)
            context_chars_max = max(context_chars_max, context_chars)
            self.trace.append(
                "context_built",
                {"step": step, "strategy": self.context_strategy, "context_chars": context_chars},
            )
            raw = self.llm.complete(context)
            self.trace.append("llm_response", {"step": step, "text": raw})

            try:
                action = parse_action(raw)
            except ActionParseError as exc:
                event = {"step": step, "type": "parse_error", "error": str(exc)}
                runtime_feedback.append(event)
                self.trace.append("parse_error", event)
                continue

            tool_result = self.dispatcher.dispatch(action)
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
                latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                runtime_feedback.append(
                    {
                        "step": step,
                        "type": "gate_result",
                        "passed": latest_gate.passed,
                        "summary": latest_gate.summary,
                    }
                )
                self.trace.append(
                    "gate_result",
                    {"step": step, "passed": latest_gate.passed, "summary": latest_gate.summary},
                )

            if action.action == "finish":
                if latest_gate is None:
                    latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                result = RunResult(latest_gate.passed, step, latest_gate, context_chars_max)
                append_memory(self.root, result.passed, result.steps, latest_gate.summary)
                return result

        if latest_gate is None:
            latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
        result = RunResult(latest_gate.passed, self.max_steps, latest_gate, context_chars_max)
        append_memory(self.root, result.passed, result.steps, latest_gate.summary)
        return result
