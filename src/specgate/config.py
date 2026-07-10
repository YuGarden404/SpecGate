from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from specgate.approvals import GovernanceConfig
from specgate.policy import WorkspacePolicy


VALID_CONTEXT_STRATEGIES = {"baseline", "compressed", "injection-safe", "rag-select"}


def _string_set(value: object, field_name: str) -> set[str]:
    if isinstance(value, str) or not isinstance(value, list | tuple | set):
        raise ValueError(f"governance.{field_name} must be a list of strings")

    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"governance.{field_name} must be a list of strings")

    return set(value)


def _string_list(value: object, field_name: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, list | tuple):
        raise ValueError(f"{field_name} must be a list of strings")

    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")

    return list(value)


def _int_value(data: dict[str, object], key: str, default: int, section: str) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"{section}.{key} must be an integer")
    return value


def _bool_value(data: dict[str, object], key: str, default: bool, section: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be a boolean")
    return value


@dataclass(frozen=True)
class ContextConfig:
    strategy: str = "baseline"
    budget_chars: int = 12000

    def __post_init__(self) -> None:
        if self.strategy not in VALID_CONTEXT_STRATEGIES:
            raise ValueError(f"context.strategy must be one of {sorted(VALID_CONTEXT_STRATEGIES)}")
        if self.budget_chars <= 0:
            raise ValueError("context.budget_chars must be positive")


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int = 6
    chunk_lines: int = 40
    chunk_overlap_lines: int = 5
    max_chunk_chars: int = 3000

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("retrieval.top_k must be positive")
        if self.chunk_lines <= 0:
            raise ValueError("retrieval.chunk_lines must be positive")
        if self.chunk_overlap_lines < 0:
            raise ValueError("retrieval.chunk_overlap_lines must be non-negative")
        if self.chunk_overlap_lines >= self.chunk_lines:
            raise ValueError("retrieval.chunk_overlap_lines must be smaller than retrieval.chunk_lines")
        if self.max_chunk_chars <= 0:
            raise ValueError("retrieval.max_chunk_chars must be positive")


@dataclass(frozen=True)
class CompressionConfig:
    enabled: bool = False
    max_tool_result_chars: int = 700

    def __post_init__(self) -> None:
        if self.max_tool_result_chars <= 0:
            raise ValueError("compression.max_tool_result_chars must be positive")


@dataclass(frozen=True)
class IsolationConfig:
    enabled: bool = False
    roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkspaceConfig:
    policy: WorkspacePolicy
    governance: GovernanceConfig
    context: ContextConfig = field(default_factory=ContextConfig)
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    isolation: IsolationConfig = field(default_factory=IsolationConfig)


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

    context_data = data.get("context", {})
    context = ContextConfig(
        strategy=context_data.get("strategy", "baseline"),
        budget_chars=_int_value(context_data, "budget_chars", 12000, "context"),
    )

    retrieval_data = data.get("retrieval", {})
    retrieval = RetrievalSettings(
        top_k=_int_value(retrieval_data, "top_k", 6, "retrieval"),
        chunk_lines=_int_value(retrieval_data, "chunk_lines", 40, "retrieval"),
        chunk_overlap_lines=_int_value(retrieval_data, "chunk_overlap_lines", 5, "retrieval"),
        max_chunk_chars=_int_value(retrieval_data, "max_chunk_chars", 3000, "retrieval"),
    )

    compression_data = data.get("compression", {})
    compression = CompressionConfig(
        enabled=_bool_value(compression_data, "enabled", False, "compression"),
        max_tool_result_chars=_int_value(
            compression_data,
            "max_tool_result_chars",
            700,
            "compression",
        ),
    )

    isolation_data = data.get("isolation", {})
    isolation = IsolationConfig(
        enabled=_bool_value(isolation_data, "enabled", False, "isolation"),
        roles=_string_list(isolation_data.get("roles", []), "isolation.roles"),
    )

    return WorkspaceConfig(
        policy=policy,
        governance=GovernanceConfig(**governance_kwargs),
        context=context,
        retrieval=retrieval,
        compression=compression,
        isolation=isolation,
    )


def load_policy(config_path: Path) -> WorkspacePolicy:
    return load_workspace_config(config_path).policy
