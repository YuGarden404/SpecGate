from __future__ import annotations

from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
from typing import Any

import specgate.workspace_fs as workspace_fs
from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action
from specgate.security import SECRET_PATTERNS


VALID_GOVERNANCE_PROFILES = ("strict", "demo", "review")
HARD_BLOCKED_PATHS = {".env", "**/.env"}
VALID_APPROVAL_STATUSES = {
    "pending",
    "approved",
    "denied",
    "applied",
    "rejected",
    "failed",
}
RESUMABLE_APPROVAL_STATUSES = {"approved", "denied"}
TERMINAL_APPROVAL_STATUSES = {"applied", "rejected", "failed"}


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
    action_payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    resolved_at: str | None = None
    target_state: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_APPROVAL_STATUSES:
            raise ValueError(f"invalid approval status: {self.status}")

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
            "action_payload": self.action_payload,
            "status": self.status,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decision_reason": self.decision_reason,
            "resolved_at": self.resolved_at,
            "target_state": self.target_state,
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
        if not isinstance(payload, dict):
            raise ValueError("pending approvals payload must be an object")

        raw_approvals = payload.get("approvals", [])
        if not isinstance(raw_approvals, list):
            raise ValueError("pending approvals must be a list")

        if not all(isinstance(approval, dict) for approval in raw_approvals):
            raise ValueError("pending approval entries must be objects")

        approvals = [_parse_pending_approval(approval) for approval in raw_approvals]
        return cls(approvals)

    def append(self, approval: PendingApproval) -> "ApprovalQueue":
        return ApprovalQueue([*self.approvals, approval])

    def find(self, approval_id: str) -> PendingApproval:
        for approval in self.approvals:
            if approval.id == approval_id:
                return approval
        raise ValueError(f"approval not found: {approval_id}")

    def approve(self, approval_id: str, decided_at: str) -> "ApprovalQueue":
        approval = self.find(approval_id)
        if approval.status != "pending":
            raise ValueError("approval is not pending")
        replacement = replace(
            approval,
            status="approved",
            decided_at=decided_at,
            decision_reason=None,
        )
        return ApprovalQueue(_replace_approval(self.approvals, approval_id, replacement))

    def deny(self, approval_id: str, reason: str, decided_at: str) -> "ApprovalQueue":
        approval = self.find(approval_id)
        if approval.status != "pending":
            raise ValueError("approval is not pending")
        replacement = replace(
            approval,
            status="denied",
            decided_at=decided_at,
            decision_reason=reason,
        )
        return ApprovalQueue(_replace_approval(self.approvals, approval_id, replacement))

    def resolve(
        self,
        approval_id: str,
        status: str,
        resolved_at: str,
        reason: str | None = None,
    ) -> "ApprovalQueue":
        if status not in TERMINAL_APPROVAL_STATUSES:
            raise ValueError("resolved approval status must be applied, rejected, or failed")
        approval = self.find(approval_id)
        if approval.status not in RESUMABLE_APPROVAL_STATUSES:
            raise ValueError("approval is not resumable")
        allowed_targets = {
            "approved": {"applied", "failed"},
            "denied": {"rejected"},
        }
        if status not in allowed_targets[approval.status]:
            raise ValueError("invalid approval transition")
        replacement = replace(
            approval,
            status=status,
            resolved_at=resolved_at,
            decision_reason=reason if reason is not None else approval.decision_reason,
        )
        return ApprovalQueue(_replace_approval(self.approvals, approval_id, replacement))

    def next_resume_candidate(self) -> PendingApproval | None:
        for approval in self.approvals:
            if approval.status in RESUMABLE_APPROVAL_STATUSES:
                return approval
        return None


def _replace_approval(
    approvals: list[PendingApproval],
    approval_id: str,
    replacement: PendingApproval,
) -> list[PendingApproval]:
    found = False
    updated: list[PendingApproval] = []
    for approval in approvals:
        if approval.id == approval_id:
            found = True
            updated.append(replacement)
        else:
            updated.append(approval)
    if not found:
        raise ValueError(f"approval not found: {approval_id}")
    return updated


def approval_queue_path(root: Path) -> Path:
    return root / "runs" / "latest" / "pending_approvals.json"


def _parse_pending_approval(approval: dict[str, Any]) -> PendingApproval:
    required = {
        "id",
        "step",
        "action",
        "path",
        "risk_level",
        "reason",
        "profile",
        "status",
    }
    if not required.issubset(approval):
        raise ValueError("pending approval entry has invalid schema")

    string_fields = ("id", "action", "risk_level", "reason", "profile", "status")
    if not all(isinstance(approval[field], str) for field in string_fields):
        raise ValueError("pending approval entry has invalid schema")

    if not isinstance(approval["step"], int) or isinstance(approval["step"], bool):
        raise ValueError("pending approval entry has invalid schema")

    if approval["path"] is not None and not isinstance(approval["path"], str):
        raise ValueError("pending approval entry has invalid schema")

    if "arguments_preview" in approval and not isinstance(approval["arguments_preview"], dict):
        raise ValueError("pending approval entry has invalid schema")

    if "action_payload" in approval and not isinstance(approval["action_payload"], dict):
        raise ValueError("pending approval entry has invalid schema")

    if "target_state" in approval and approval["target_state"] is not None:
        _validate_target_state(approval["target_state"])

    for optional_field in ("created_at", "decided_at", "decision_reason", "resolved_at"):
        if (
            optional_field in approval
            and approval[optional_field] is not None
            and not isinstance(approval[optional_field], str)
        ):
            raise ValueError("pending approval entry has invalid schema")

    if approval["status"] not in VALID_APPROVAL_STATUSES:
        raise ValueError("pending approval entry has invalid schema")

    return PendingApproval(
        id=approval["id"],
        step=approval["step"],
        action=approval["action"],
        path=approval["path"],
        risk_level=approval["risk_level"],
        reason=approval["reason"],
        profile=approval["profile"],
        arguments_preview=approval.get("arguments_preview", {}),
        action_payload=approval.get("action_payload", {}),
        status=approval["status"],
        created_at=approval.get("created_at"),
        decided_at=approval.get("decided_at"),
        decision_reason=approval.get("decision_reason"),
        resolved_at=approval.get("resolved_at"),
        target_state=approval.get("target_state"),
    )


def capture_target_state(root: Path, relative_path: str | None) -> dict[str, Any] | None:
    if relative_path is None:
        return None

    normalized_path = workspace_fs.normalize_workspace_relative(relative_path)
    state = workspace_fs.workspace_file_state(root, normalized_path)
    return {
        "path": normalized_path,
        "exists": state.exists,
        "sha256": state.sha256,
    }


def target_state_matches(root: Path, target_state: dict[str, Any] | None) -> bool:
    if target_state is None:
        return True
    _validate_target_state(target_state)
    try:
        current = capture_target_state(root, target_state["path"])
    except (OSError, workspace_fs.WorkspacePathError):
        return False
    return current == target_state


def _validate_target_state(target_state: Any) -> None:
    if not isinstance(target_state, dict):
        raise ValueError("pending approval entry has invalid schema")
    required = {"path", "exists", "sha256"}
    if not required.issubset(target_state):
        raise ValueError("pending approval entry has invalid schema")
    if not isinstance(target_state["path"], str):
        raise ValueError("pending approval entry has invalid schema")
    if not isinstance(target_state["exists"], bool):
        raise ValueError("pending approval entry has invalid schema")
    if target_state["sha256"] is not None and not isinstance(target_state["sha256"], str):
        raise ValueError("pending approval entry has invalid schema")


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
    if path is not None and _matches_any(path, config.blocked_paths | HARD_BLOCKED_PATHS):
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
