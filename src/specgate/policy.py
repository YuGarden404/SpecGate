from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from specgate.actions import Action


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


def _normalize_relative(path_value: str) -> str | None:
    if not isinstance(path_value, str) or not path_value:
        return None
    pure = PurePosixPath(path_value.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return str(pure)


def check_action(action: Action, policy: WorkspacePolicy) -> GuardrailDecision:
    if action.action not in policy.allowed_actions:
        return GuardrailDecision(False, f"unknown action: {action.action}")

    path_value = action.args.get("path")
    if action.action in {"read_file", "write_file", "replace_file"} and path_value is None:
        return GuardrailDecision(False, f"missing required path for {action.action}")
    if path_value is None:
        return GuardrailDecision(True, "allowed")
    if not isinstance(path_value, str) or not path_value:
        return GuardrailDecision(False, "path must be a non-empty string")

    normalized = _normalize_relative(path_value)
    if normalized is None:
        return GuardrailDecision(False, "path escapes workspace")

    if action.action in {"write_file", "replace_file"}:
        if normalized not in policy.allowed_write_paths:
            return GuardrailDecision(False, f"write path not allowed: {normalized}")

    if action.action == "read_file":
        if normalized not in policy.allowed_read_paths:
            return GuardrailDecision(False, f"read path not allowed: {normalized}")

    return GuardrailDecision(True, "allowed")
