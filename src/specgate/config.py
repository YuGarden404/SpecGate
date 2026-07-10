from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from specgate.approvals import GovernanceConfig
from specgate.policy import WorkspacePolicy


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
        "review_actions": set(governance_data.get("review_actions", [])),
        "review_paths": set(governance_data.get("review_paths", [])),
    }
    if "blocked_paths" in governance_data:
        governance_kwargs["blocked_paths"] = set(governance_data["blocked_paths"])

    return WorkspaceConfig(
        policy=policy,
        governance=GovernanceConfig(**governance_kwargs),
    )


def load_policy(config_path: Path) -> WorkspacePolicy:
    return load_workspace_config(config_path).policy
