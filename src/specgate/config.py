from __future__ import annotations

from pathlib import Path
import tomllib

from specgate.policy import WorkspacePolicy


def load_policy(config_path: Path) -> WorkspacePolicy:
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    return WorkspacePolicy(
        root=root,
        allowed_actions=set(data["policy"]["allowed_actions"]),
        allowed_read_paths=set(data["policy"]["allowed_read_paths"]),
        allowed_write_paths=set(data["policy"]["allowed_write_paths"]),
    )
