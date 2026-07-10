from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunMetrics:
    steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    successful_tool_calls: int = 0
    blocked_actions: int = 0
    finish_actions: int = 0
    max_steps_reached: bool = False


@dataclass(frozen=True)
class PermissionDecision:
    step: int
    action: str
    path: str | None
    allowed: bool
    blocked: bool
    reason: str
    profile: str
    rule_family: str


@dataclass(frozen=True)
class TrustSummary:
    status: str
    reasons: list[str] = field(default_factory=list)


def classify_rule_family(reason: str) -> str:
    lowered = reason.lower()
    if "unknown action" in lowered:
        return "action"
    if "path escapes" in lowered or "path must" in lowered or "missing required path" in lowered:
        return "path"
    if "not allowed" in lowered:
        return "allowlist"
    if "changed since run started" in lowered:
        return "snapshot"
    if "unknown tool" in lowered:
        return "tool"
    return "none"


def build_trust_summary(gate_passed: bool, metrics: RunMetrics) -> TrustSummary:
    reasons: list[str] = []

    if not gate_passed:
        reasons.append("gate_failed")
    if metrics.max_steps_reached:
        reasons.append("max_steps_reached")
    if reasons:
        return TrustSummary("failed", reasons)

    if metrics.blocked_actions:
        reasons.append("blocked_actions_present")
    if metrics.finish_actions != 1:
        reasons.append("missing_clean_finish")
    if reasons:
        return TrustSummary("warning", reasons)

    return TrustSummary("trusted", ["clean_finish"])
