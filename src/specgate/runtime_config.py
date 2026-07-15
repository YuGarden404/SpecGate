from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Literal, Mapping

from specgate.approvals import VALID_GOVERNANCE_PROFILES
from specgate.config import VALID_CONTEXT_STRATEGIES


class RuntimeConfigError(ValueError):
    code = "invalid_runtime_config"

    def __init__(
        self,
        field: str,
        message: str = "运行配置无效 / Invalid runtime configuration",
    ) -> None:
        self.field = field
        super().__init__(message)


def _strict_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeConfigError(field)
    if not minimum <= value <= maximum:
        raise RuntimeConfigError(field)
    return value


@dataclass(frozen=True)
class RunRuntimeConfig:
    schema_version: int = 1
    source: Literal["created", "migration"] = "created"
    governance_profile: str = "review"
    context_strategy: str = "injection-safe"
    max_steps: int = 5
    context_budget_chars: int = 12000
    retrieval_top_k: int = 6
    retrieval_budget_chars: int = 9000
    compression_max_tool_result_chars: int = 1200

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise RuntimeConfigError("schema_version")
        if self.source not in {"created", "migration"}:
            raise RuntimeConfigError("source")
        if self.governance_profile not in VALID_GOVERNANCE_PROFILES:
            raise RuntimeConfigError("governance_profile")
        if self.context_strategy not in VALID_CONTEXT_STRATEGIES:
            raise RuntimeConfigError("context_strategy")
        _strict_int("max_steps", self.max_steps, 1, 20)
        _strict_int("context_budget_chars", self.context_budget_chars, 1000, 100000)
        _strict_int("retrieval_top_k", self.retrieval_top_k, 1, 20)
        _strict_int("retrieval_budget_chars", self.retrieval_budget_chars, 500, 50000)
        _strict_int(
            "compression_max_tool_result_chars",
            self.compression_max_tool_result_chars,
            100,
            10000,
        )

    @classmethod
    def from_settings(cls, values: Mapping[str, object]) -> RunRuntimeConfig:
        try:
            payload = {name: values[name] for name in _SETTING_FIELDS}
        except (KeyError, TypeError) as exc:
            raise RuntimeConfigError("settings") from exc
        return cls(**payload)

    @classmethod
    def for_migration(cls, values: Mapping[str, object]) -> RunRuntimeConfig:
        defaults = cls().to_dict()
        payload = {
            name: values[name] if name in values else defaults[name]
            for name in _SETTING_FIELDS
        }
        return cls(source="migration", **payload)

    @classmethod
    def from_json(cls, raw: str) -> RunRuntimeConfig:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeConfigError("runtime_config_json") from exc
        expected = {field.name for field in fields(cls)}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise RuntimeConfigError("runtime_config_json")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise RuntimeConfigError("runtime_config_json") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


_SETTING_FIELDS = (
    "governance_profile",
    "context_strategy",
    "max_steps",
    "context_budget_chars",
    "retrieval_top_k",
    "retrieval_budget_chars",
    "compression_max_tool_result_chars",
)
