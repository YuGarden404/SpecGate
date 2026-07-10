from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from specgate.approvals import GovernanceConfig
from specgate.policy import WorkspacePolicy


def _string_set(value: object, field_name: str) -> set[str]:
    if isinstance(value, str) or not isinstance(value, list | tuple | set):
        raise ValueError(f"governance.{field_name} must be a list of strings")

    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"governance.{field_name} must be a list of strings")

    return set(value)


@dataclass(frozen=True)
class WorkspaceConfig:
    policy: WorkspacePolicy
    governance: GovernanceConfig


def load_workspace_config(config_path: Path) -> WorkspaceConfig:
    data = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    root = config_path.parent
    policy = WorkspacePolicy(
        root=root,
        allowed_actions=set(data["policy"]["allowed_actions"]),
        allowed_read_paths=set(data["policy"]["allowed_read_paths"]),
        allowed_write_paths=set(data["policy"]["allowed_write_paths"]),
    )

    governance_data = data.get("governance", {})
    governance_kwargs = {
        "profile": governance_data.get("profile", "strict"),
    }
    if "review_actions" in governance_data:
        governance_kwargs["review_actions"] = _string_set(
            governance_data["review_actions"],
            "review_actions",
        )
    if "review_paths" in governance_data:
        governance_kwargs["review_paths"] = _string_set(
            governance_data["review_paths"],
            "review_paths",
        )
    if "blocked_paths" in governance_data:
        governance_kwargs["blocked_paths"] = _string_set(
            governance_data["blocked_paths"],
            "blocked_paths",
        )

    return WorkspaceConfig(
        policy=policy,
        governance=GovernanceConfig(**governance_kwargs),
    )


def load_policy(config_path: Path) -> WorkspacePolicy:
    return load_workspace_config(config_path).policy
