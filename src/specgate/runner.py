from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specgate.actions import ActionParseError, parse_action
from specgate.context import build_context_pack
from specgate.gate import GateResult, run_html_gate
from specgate.llm import LLMClient
from specgate.policy import WorkspacePolicy
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore


@dataclass(frozen=True)
class RunResult:
    passed: bool
    steps: int
    final_gate: GateResult | None


class AgentRunner:
    def __init__(self, root: Path, llm: LLMClient, policy: WorkspacePolicy, max_steps: int = 5):
        self.root = root
        self.llm = llm
        self.policy = policy
        self.max_steps = max_steps
        self.dispatcher = ToolDispatcher(policy)
        self.trace = TraceStore(root / "runs" / "latest" / "trace.jsonl")

    def run(self) -> RunResult:
        latest_gate: GateResult | None = None
        for step in range(1, self.max_steps + 1):
            context = build_context_pack(self.root, latest_gate)
            raw = self.llm.complete(context)
            self.trace.append("llm_response", {"step": step, "text": raw})

            try:
                action = parse_action(raw)
            except ActionParseError as exc:
                self.trace.append("parse_error", {"step": step, "error": str(exc)})
                continue

            tool_result = self.dispatcher.dispatch(action)
            self.trace.append("tool_result", {"step": step, "result": tool_result.__dict__})

            if action.action in {"write_file", "replace_file"} and not tool_result.blocked:
                latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                self.trace.append(
                    "gate_result",
                    {"step": step, "passed": latest_gate.passed, "summary": latest_gate.summary},
                )

            if action.action == "finish":
                if latest_gate is None:
                    latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                return RunResult(latest_gate.passed, step, latest_gate)

        if latest_gate is None:
            latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
        return RunResult(latest_gate.passed, self.max_steps, latest_gate)
