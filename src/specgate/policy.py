from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specgate.actions import Action
from specgate.workspace_fs import WorkspacePathError, normalize_workspace_relative


@dataclass(frozen=True)
class WorkspacePolicy:
    root: Path
    allowed_actions: set[str]
    allowed_read_paths: set[str]
    allowed_write_paths: set[str]


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str
    rule_family: str = "none"


def check_action(action: Action, policy: WorkspacePolicy) -> GuardrailDecision:
    if action.action not in policy.allowed_actions:
        return GuardrailDecision(False, f"unknown action: {action.action}", "action")

    path_value = action.args.get("path")
    if action.action in {"read_file", "write_file", "replace_file"} and path_value is None:
        return GuardrailDecision(
            False,
            f"missing required path for {action.action}",
            "invalid_path",
        )
    if path_value is None:
        return GuardrailDecision(True, "allowed")
    if not isinstance(path_value, str) or not path_value:
        return GuardrailDecision(
            False,
            "path must be a non-empty string",
            "invalid_path",
        )

    try:
        normalized = normalize_workspace_relative(path_value)
    except WorkspacePathError as exc:
        reason = (
            "path escapes workspace"
            if exc.rule_family == "path_escape"
            else f"invalid workspace path: {exc.message}"
        )
        return GuardrailDecision(False, reason, exc.rule_family)

    if action.action in {"write_file", "replace_file"}:
        if normalized not in policy.allowed_write_paths:
            return GuardrailDecision(
                False,
                f"write path not allowed: {normalized}",
                "allowlist",
            )

    if action.action == "read_file":
        if normalized not in policy.allowed_read_paths:
            return GuardrailDecision(
                False,
                f"read path not allowed: {normalized}",
                "allowlist",
            )

    return GuardrailDecision(True, "allowed")
