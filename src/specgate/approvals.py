from __future__ import annotations

from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
import json
import os
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
    "applying",
    "applied",
    "rejected",
    "failed",
}
RESUMABLE_APPROVAL_STATUSES = {"approved", "denied", "applying"}
TERMINAL_APPROVAL_STATUSES = {"applied", "rejected", "failed"}


class ApprovalConflictError(ValueError):
    code = "approval_conflict"


@dataclass
class GovernanceConfig:
    profile: str = "strict"
    review_actions: set[str] = field(default_factory=set)
    review_paths: set[str] = field(default_factory=set)
    blocked_paths: set[str] = field(default_factory=lambda: {".env", "**/.env"})
    review_existing_writes: bool = False

    def __post_init__(self) -> None:
        if self.profile not in VALID_GOVERNANCE_PROFILES:
            raise ValueError(f"invalid governance profile: {self.profile}")


@dataclass
class ActionRisk:
    level: str
    reason: str
    rule_family: str = "none"

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "reason": self.reason,
            "rule_family": self.rule_family,
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
    schema_version: str = "2"
    revision: int = 0

    def __post_init__(self) -> None:
        if self.schema_version not in {"1", "2"}:
            raise ValueError("unsupported approval queue schema version")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise ValueError("approval queue revision must be an integer")
        if self.revision < 0:
            raise ValueError("approval queue revision must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "approvals": [approval.to_dict() for approval in self.approvals],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalQueue":
        if not isinstance(payload, dict):
            raise ValueError("pending approvals payload must be an object")

        schema_version = payload.get("schema_version", "1")
        revision = payload.get("revision", 0)
        if not isinstance(schema_version, str) or schema_version not in {"1", "2"}:
            raise ValueError("unsupported approval queue schema version")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("approval queue revision must be a non-negative integer")

        raw_approvals = payload.get("approvals", [])
        if not isinstance(raw_approvals, list):
            raise ValueError("pending approvals must be a list")
        if not all(isinstance(approval, dict) for approval in raw_approvals):
            raise ValueError("pending approval entries must be objects")

        return cls(
            approvals=[_parse_pending_approval(approval) for approval in raw_approvals],
            schema_version=schema_version,
            revision=revision,
        )

    def write(self, path: Path) -> None:
        root, relative_path = _approval_queue_location(path)
        workspace_fs.write_workspace_text(
            root,
            relative_path,
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> "ApprovalQueue":
        try:
            return read_existing_approval_queue(path)
        except workspace_fs.WorkspacePathError as exc:
            if _is_missing_queue_file(exc, path):
                return cls()
            raise

    def append(self, approval: PendingApproval) -> "ApprovalQueue":
        return replace(self, approvals=[*self.approvals, approval])

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
        return replace(
            self,
            approvals=_replace_approval(self.approvals, approval_id, replacement),
        )

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
        return replace(
            self,
            approvals=_replace_approval(self.approvals, approval_id, replacement),
        )

    def transition(
        self,
        approval_id: str,
        status: str,
        resolved_at: str,
        reason: str | None = None,
    ) -> "ApprovalQueue":
        approval = self.find(approval_id)
        allowed_targets = {
            "approved": {"applying", "applied", "failed"},
            "applying": {"applied", "failed"},
            "denied": {"rejected"},
        }
        if approval.status not in allowed_targets:
            raise ValueError("approval is not resumable")
        if status not in allowed_targets[approval.status]:
            raise ValueError("invalid approval transition")
        replacement = replace(
            approval,
            status=status,
            resolved_at=(resolved_at if status in TERMINAL_APPROVAL_STATUSES else None),
            decision_reason=reason if reason is not None else approval.decision_reason,
        )
        return replace(
            self,
            approvals=_replace_approval(self.approvals, approval_id, replacement),
        )

    def resolve(
        self,
        approval_id: str,
        status: str,
        resolved_at: str,
        reason: str | None = None,
    ) -> "ApprovalQueue":
        if status not in TERMINAL_APPROVAL_STATUSES:
            raise ValueError("resolved approval status must be applied, rejected, or failed")
        return self.transition(approval_id, status, resolved_at, reason)

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


class ApprovalStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> ApprovalQueue:
        with _approval_queue_lock(self.path):
            return ApprovalQueue.read(self.path)

    def read_existing(self) -> ApprovalQueue:
        with _approval_queue_lock(self.path):
            return read_existing_approval_queue(self.path)

    def append(
        self,
        approval: PendingApproval,
        *,
        expected_revision: int,
    ) -> ApprovalQueue:
        return self._mutate(
            expected_revision,
            lambda queue: queue.append(approval),
        )

    def decide(
        self,
        approval_id: str,
        status: str,
        *,
        expected_revision: int,
        decided_at: str,
        reason: str | None = None,
    ) -> ApprovalQueue:
        def mutation(queue: ApprovalQueue) -> ApprovalQueue:
            if status == "approved":
                return queue.approve(approval_id, decided_at)
            if status == "denied":
                return queue.deny(approval_id, reason or "", decided_at)
            raise ValueError("invalid approval decision")

        return self._mutate(expected_revision, mutation)

    def transition(
        self,
        approval_id: str,
        status: str,
        *,
        expected_revision: int,
        resolved_at: str,
        reason: str | None = None,
    ) -> ApprovalQueue:
        return self._mutate(
            expected_revision,
            lambda queue: queue.transition(
                approval_id,
                status,
                resolved_at,
                reason,
            ),
        )

    def _mutate(self, expected_revision: int, mutation) -> ApprovalQueue:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ValueError("expected revision must be an integer")
        with _approval_queue_lock(self.path):
            current = ApprovalQueue.read(self.path)
            if current.revision != expected_revision:
                raise ApprovalConflictError("approval queue revision changed")
            changed = mutation(current)
            updated = replace(
                changed,
                schema_version="2",
                revision=current.revision + 1,
            )
            updated.write(self.path)
            return updated


def _approval_queue_lock(path: Path):
    root, relative_path = _approval_queue_location(path)
    return workspace_fs.workspace_file_lock(root, f"{relative_path}.lock")


def _approval_queue_location(path: Path) -> tuple[Path, str]:
    absolute_path = Path(os.path.abspath(path))
    root = Path(absolute_path.anchor)
    relative_path = absolute_path.relative_to(root).as_posix()
    return root, workspace_fs.normalize_workspace_relative(relative_path)


def _is_missing_queue_file(
    error: workspace_fs.WorkspacePathError,
    path: Path,
) -> bool:
    if error.rule_family != "path_race":
        return False
    _, expected_relative = _approval_queue_location(path)
    return error.missing_path == expected_relative


def read_existing_approval_queue(path: Path) -> ApprovalQueue:
    root, relative_path = _approval_queue_location(path)
    content = workspace_fs.read_workspace_text(
        root,
        relative_path,
        encoding="utf-8-sig",
    )
    return _parse_approval_queue_content(content)


def read_approval_queue_if_present(
    workspace_root: Path,
    path: Path,
) -> ApprovalQueue | None:
    root = Path(os.path.abspath(workspace_root))
    absolute_path = Path(os.path.abspath(path))
    try:
        relative_path = workspace_fs.normalize_workspace_relative(
            absolute_path.relative_to(root).as_posix()
        )
    except ValueError as exc:
        raise workspace_fs.WorkspacePathError(
            "approval queue is outside the workspace",
            "invalid_path",
        ) from exc

    content = workspace_fs.read_optional_workspace_text(
        root,
        relative_path,
        encoding="utf-8-sig",
    )
    if content is None:
        return None
    return _parse_approval_queue_content(content)


def _parse_approval_queue_content(content: str) -> ApprovalQueue:
    payload = json.loads(content)
    return ApprovalQueue.from_dict(payload)


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
        return ActionRisk("blocked", decision.reason, decision.rule_family)

    path = _action_path(action)
    if path is not None and _matches_any(path, config.blocked_paths | HARD_BLOCKED_PATHS):
        return ActionRisk("blocked", f"blocked path: {path}", "allowlist")

    if action.action in config.review_actions:
        return ActionRisk("review", f"{action.action} requires human review")

    if path is not None and _matches_any(path, config.review_paths):
        return ActionRisk(
            "review",
            f"{action.action} on protected path requires human review",
        )

    if (
        config.review_existing_writes
        and action.action in {"write_file", "replace_file"}
        and path is not None
    ):
        try:
            target_state = workspace_fs.workspace_file_state(policy.root, path)
        except workspace_fs.WorkspacePathError as exc:
            return ActionRisk("blocked", str(exc), exc.rule_family)
        if target_state.exists:
            return ActionRisk(
                "review",
                f"{action.action} would overwrite an existing target",
                "existing_target",
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
