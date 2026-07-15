from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Literal


class LLMConfigError(ValueError):
    code = "invalid_llm_config"

    def __init__(
        self,
        field: str,
        message: str = "LLM 配置快照无效 / Invalid LLM configuration snapshot",
    ) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True)
class LLMRunConfig:
    schema_version: int = 1
    source: Literal["created", "migration-v5"] = "created"
    mode: Literal["mock", "openai-compatible"] = "mock"
    base_url: str | None = None
    model: str | None = None
    credential_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise LLMConfigError("schema_version")
        if self.source not in {"created", "migration-v5"}:
            raise LLMConfigError("source")
        if self.mode == "mock":
            if any(
                value is not None
                for value in (
                    self.base_url,
                    self.model,
                    self.credential_fingerprint,
                )
            ):
                raise LLMConfigError("mode")
            return
        if self.mode != "openai-compatible":
            raise LLMConfigError("mode")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise LLMConfigError("base_url")
        if not isinstance(self.model, str) or not self.model:
            raise LLMConfigError("model")
        fingerprint = self.credential_fingerprint
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise LLMConfigError("credential_fingerprint")
        if any(char not in "0123456789abcdef" for char in fingerprint):
            raise LLMConfigError("credential_fingerprint")

    @classmethod
    def mock(
        cls,
        *,
        source: Literal["created", "migration-v5"] = "created",
    ) -> LLMRunConfig:
        return cls(source=source)

    @classmethod
    def real(
        cls,
        base_url: str,
        model: str,
        fingerprint: str,
    ) -> LLMRunConfig:
        return cls(
            mode="openai-compatible",
            base_url=base_url,
            model=model,
            credential_fingerprint=fingerprint,
        )

    @classmethod
    def from_json(cls, raw: str) -> LLMRunConfig:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMConfigError("llm_config_json") from exc
        expected = {field.name for field in fields(cls)}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise LLMConfigError("llm_config_json")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise LLMConfigError("llm_config_json") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
