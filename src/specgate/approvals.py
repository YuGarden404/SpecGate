from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import json
from pathlib import Path
from typing import Any

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action

try:
    from specgate.security import redact_text
except ImportError:

    def redact_text(text: str) -> str:
        return text


VALID_GOVERNANCE_PROFILES = ("strict", "demo", "review")


@dataclass
class GovernanceConfig:
    profile: str = "strict"
    review_actions: set[str] = field(default_factory=set)
    review_paths: set[str] = field(default_factory=set)
    blocked_paths: set[str] = field(default_factory=lambda: {".env"})

    def __post_init__(self) -> None:
        if self.profile not in VALID_GOVERNANCE_PROFILES:
            raise ValueError(f"invalid governance profile: {self.profile}")


@dataclass
class ActionRisk:
    level: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "reason": self.reason,
        }


@dataclass
class PendingApproval:
    id: str
    step: int
    action: str
    path: str | None
    risk_level: str
    reason: str
    profile: str
    arguments_preview: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step": self.step,
            "action": self.action,
            "path": self.path,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "profile": self.profile,
            "arguments_preview": self.arguments_preview,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class ApprovalQueue:
    approvals: list[PendingApproval] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"approvals": [approval.to_dict() for approval in self.approvals]}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> "ApprovalQueue":
        if not path.exists():
            return cls()

        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        approvals = [
            PendingApproval(**approval)
            for approval in payload.get("approvals", [])
        ]
        return cls(approvals)

    def append(self, approval: PendingApproval) -> None:
        self.approvals.append(approval)


def approval_queue_path(root: Path) -> Path:
    return root / "runs" / "latest" / "pending_approvals.json"


def preview_args(args: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            preview[key] = redact_text(value[:240])
        else:
            preview[key] = value
    return preview


def classify_action_risk(
    action: Action,
    policy: WorkspacePolicy,
    config: GovernanceConfig,
) -> ActionRisk:
    decision = check_action(action, policy)
    if not decision.allowed:
        return ActionRisk("blocked", decision.reason)

    path = _action_path(action)
    if path is not None and _matches_any(path, config.blocked_paths):
        return ActionRisk("blocked", f"blocked path: {path}")

    if action.action in config.review_actions:
        return ActionRisk("review", f"{action.action} requires human review")

    if path is not None and _matches_any(path, config.review_paths):
        return ActionRisk(
            "review",
            f"{action.action} on protected path requires human review",
        )

    return ActionRisk("safe", "safe action")


def _action_path(action: Action) -> str | None:
    path = action.args.get("path")
    if not isinstance(path, str) or not path:
        return None
    return path.replace("\\", "/")


def _matches_any(path: str, patterns: set[str]) -> bool:
    return any(fnmatch(path, pattern.replace("\\", "/")) for pattern in patterns)
