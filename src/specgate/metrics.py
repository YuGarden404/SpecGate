from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RunMetrics:
    steps: int = 0
    context_chars_max: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    successful_tool_calls: int = 0
    blocked_actions: int = 0
    parse_errors: int = 0
    gate_runs: int = 0
    gate_failures: int = 0
    finish_actions: int = 0
    approval_requests: int = 0
    pending_approvals: int = 0
    retrieval_queries: int = 0
    retrieved_chunks: int = 0
    retrieval_candidate_chunks: int = 0
    retrieval_context_chars: int = 0
    max_steps_reached: bool = False

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionDecision:
    step: int
    action: str
    path: str | None
    allowed: bool
    blocked: bool
    reason: str
    profile: str = "strict"
    rule_family: str = "none"

    def to_dict(self) -> dict[str, int | str | bool | None]:
        return asdict(self)


@dataclass(frozen=True)
class TrustSummary:
    status: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, str | list[str]]:
        return asdict(self)


def classify_rule_family(reason: str) -> str:
    lowered = reason.lower()
    if "unknown action" in lowered or "unimplemented action" in lowered:
        return "action"
    if "path escapes" in lowered or "path must" in lowered or "missing required path" in lowered:
        return "path"
    if "write path not allowed" in lowered or "read path not allowed" in lowered:
        return "allowlist"
    if "changed since run started" in lowered or "snapshot" in lowered:
        return "snapshot"
    if "unknown tool" in lowered or "tool" in lowered:
        return "tool"
    return "none"


def build_trust_summary(final_gate_passed: bool, metrics: RunMetrics) -> TrustSummary:
    """Build final trust status.

    gate_failures is historical repair evidence; final_gate_passed is the final artifact verdict.
    """
    reasons: list[str] = []

    if not final_gate_passed:
        reasons.append("gate_failed")
    if metrics.max_steps_reached:
        reasons.append("max_steps_reached")
    if metrics.finish_actions == 0:
        reasons.append("missing_finish")
    if reasons:
        return TrustSummary("failed", reasons)

    if metrics.blocked_actions:
        reasons.append("blocked_actions_present")
    if metrics.parse_errors:
        reasons.append("parse_errors_present")
    if metrics.pending_approvals:
        reasons.append("pending_approvals_present")
    if reasons:
        return TrustSummary("warning", reasons)

    return TrustSummary("trusted", ["clean_finish"])
