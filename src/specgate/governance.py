from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from specgate.actions import Action
from specgate.approvals import (
    ActionRisk,
    GovernanceConfig,
    classify_action_risk,
)
from specgate.policy import WorkspacePolicy, check_action
from specgate.tool_runtime import PreparedToolCall


class GovernanceDecisionKind(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class GovernanceDecision:
    kind: GovernanceDecisionKind
    code: str
    reason: str
    rule_family: str
    risk: ActionRisk | None = None


class GovernanceEngine:
    def evaluate(
        self,
        call: PreparedToolCall,
        *,
        capabilities: frozenset[str],
        policy: WorkspacePolicy,
        config: GovernanceConfig,
    ) -> GovernanceDecision:
        action_name = call.definition.name
        if action_name not in capabilities:
            return GovernanceDecision(
                GovernanceDecisionKind.BLOCK,
                "capability",
                f"capability not granted: {action_name}",
                "capability",
            )

        action = Action(
            "1",
            action_name,
            call.args.model_dump(mode="python"),
        )
        guardrail = check_action(action, policy)
        if not guardrail.allowed:
            return GovernanceDecision(
                GovernanceDecisionKind.BLOCK,
                guardrail.rule_family,
                guardrail.reason,
                guardrail.rule_family,
            )

        risk = classify_action_risk(action, policy, config)
        if risk.level == "blocked":
            kind = GovernanceDecisionKind.BLOCK
        elif risk.level == "review":
            kind = (
                GovernanceDecisionKind.REQUIRE_APPROVAL
                if config.profile == "review"
                else GovernanceDecisionKind.BLOCK
            )
        elif risk.level == "safe":
            kind = GovernanceDecisionKind.ALLOW
        else:
            return GovernanceDecision(
                GovernanceDecisionKind.BLOCK,
                "invalid_risk",
                "governance returned an unknown risk level",
                "governance",
                risk,
            )
        code = risk.rule_family if risk.rule_family != "none" else risk.level
        return GovernanceDecision(
            kind,
            code,
            risk.reason,
            risk.rule_family,
            risk,
        )
