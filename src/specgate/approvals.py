from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
from typing import Any

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action
from specgate.security import SECRET_PATTERNS


VALID_GOVERNANCE_PROFILES = ("strict", "demo", "review")


@dataclass
class GovernanceConfig:
    profile: str = "strict"
    review_actions: set[str] = field(default_factory=set)
    review_paths: set[str] = field(default_factory=set)
    blocked_paths: set[str] = field(default_factory=lambda: {".env", "**/.env"})

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

    def append(self, approval: PendingApproval) -> "ApprovalQueue":
        return ApprovalQueue([*self.approvals, approval])


def approval_queue_path(root: Path) -> Path:
    return root / "runs" / "latest" / "pending_approvals.json"


def preview_args(args: dict[str, Any]) -> dict[str, Any]:
    return _preview_value(args)


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
    normalized_path = path.replace("\\", "/")
    return any(
        _matches_pattern(normalized_path, pattern.replace("\\", "/"))
        for pattern in patterns
    )


def _preview_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value

    if isinstance(value, str):
        return _redact_text(value[:240])

    if isinstance(value, list | tuple):
        return [_preview_value(item) for item in value]

    if isinstance(value, dict):
        return {
            _redact_text(str(key)[:240]): _preview_value(item)
            for key, item in value.items()
        }

    return _redact_text(str(value)[:240])


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    return redacted


def _redact_match(match: re.Match[str]) -> str:
    if match.re.pattern.startswith(r"(?i)(api[_-]?key"):
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def _matches_pattern(path: str, pattern: str) -> bool:
    if path == pattern:
        return True

    return _match_parts(path.split("/"), pattern.split("/"))


def _match_parts(path_parts: list[str], pattern_parts: list[str]) -> bool:
    if not pattern_parts:
        return not path_parts

    head, *tail = pattern_parts
    if head == "**":
        return any(
            _match_parts(path_parts[index:], tail)
            for index in range(len(path_parts) + 1)
        )

    if not path_parts:
        return False

    return fnmatchcase(path_parts[0], head) and _match_parts(path_parts[1:], tail)
