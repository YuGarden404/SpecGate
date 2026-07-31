from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]


class AgentArtifactValidationError(ValueError):
    code = "artifact_schema_invalid"


class AgentArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    schema_version: Literal["1"] = "1"
    producer_run_id: NonEmptyString
    references: tuple[NonEmptyString, ...] = ()


class PlanArtifact(AgentArtifact):
    kind: Literal["plan"] = "plan"
    steps: tuple[NonEmptyString, ...]


class ImplementationArtifact(AgentArtifact):
    kind: Literal["implementation"] = "implementation"
    changed_paths: tuple[NonEmptyString, ...]
    summary: str


class ReviewArtifact(AgentArtifact):
    kind: Literal["review"] = "review"
    accepted: StrictBool
    repair_required: StrictBool
    issues: tuple[NonEmptyString, ...] = ()


Artifact: TypeAlias = Annotated[
    PlanArtifact | ImplementationArtifact | ReviewArtifact,
    Field(discriminator="kind"),
]
_ARTIFACT_ADAPTER = TypeAdapter(Artifact)


def parse_agent_artifact(payload: str | bytes | dict[str, Any]) -> Artifact:
    try:
        if isinstance(payload, (str, bytes)):
            return _ARTIFACT_ADAPTER.validate_json(payload)
        if isinstance(payload, dict):
            return _ARTIFACT_ADAPTER.validate_python(payload)
        raise TypeError("artifact payload must be JSON text or an object")
    except (TypeError, ValueError, ValidationError) as exc:
        raise AgentArtifactValidationError(
            "artifact_schema_invalid"
        ) from exc
