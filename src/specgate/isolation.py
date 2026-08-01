from __future__ import annotations

from dataclasses import asdict, dataclass

from specgate.agent_service import AgentDefinition, AgentRunResult
from specgate.artifacts import (
    ImplementationArtifact,
    PlanArtifact,
    ReviewArtifact,
    parse_agent_artifact,
)


@dataclass(frozen=True)
class RoleContext:
    role: str
    visible_sections: tuple[str, ...]
    hidden_sections: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    state_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, str | list[str]]:
        data = asdict(self)
        return {key: list(value) if isinstance(value, tuple) else value for key, value in data.items()}


@dataclass(frozen=True)
class RoleExecution:
    role: str
    phase: str
    context_chars: int
    visible_sections: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    attempted_action: str
    action_allowed_by_role: bool
    blocked_reason: str | None
    summary: str | None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return {key: list(value) if isinstance(value, tuple) else value for key, value in data.items()}


ROLE_CONTEXTS = (
    RoleContext(
        role="planner",
        visible_sections=("Task", "Checklist", "Retrieved Context", "Latest Gate Feedback"),
        hidden_sections=("draft_patch", "review_notes"),
        allowed_actions=("read_file", "list_files", "finish"),
        state_keys=("task", "plan", "constraints"),
    ),
    RoleContext(
        role="implementer",
        visible_sections=("Task", "Checklist", "Retrieved Context", "Plan", "Latest Gate Feedback"),
        hidden_sections=("review_notes",),
        allowed_actions=("read_file", "list_files", "write_file", "replace_file", "finish"),
        state_keys=("task", "plan", "constraints", "draft_patch"),
    ),
    RoleContext(
        role="reviewer",
        visible_sections=("Task", "Checklist", "Final Artifact", "Trace Summary", "Latest Gate Feedback"),
        hidden_sections=("draft_patch",),
        allowed_actions=("read_file", "list_files", "finish"),
        state_keys=("task", "constraints", "review_notes"),
    ),
)


def build_role_contexts(
    definitions: tuple[AgentDefinition, ...] = (),
) -> list[RoleContext]:
    if definitions:
        return [_context_from_definition(definition) for definition in definitions]
    return list(ROLE_CONTEXTS)


def role_context_for(role: str) -> RoleContext:
    context = next((item for item in ROLE_CONTEXTS if item.role == role), None)
    if context is None:
        raise ValueError(f"unknown role: {role}")
    return context


def action_allowed_for_role(role: str, action: str) -> bool:
    return action in role_context_for(role).allowed_actions


def filter_state_for_role(role: str, state: dict[str, object]) -> dict[str, object]:
    context = role_context_for(role)
    return {key: value for key, value in state.items() if key in context.state_keys}


def build_isolation_evidence(
    strategy: str = "isolated-harness",
    executions: list[RoleExecution] | None = None,
    review_repairs: int = 0,
    *,
    definitions: tuple[AgentDefinition, ...] = (),
    agent_runs: tuple[AgentRunResult, ...] = (),
) -> dict[str, object]:
    contexts = build_role_contexts(definitions)
    role_executions = (
        list(executions)
        if executions is not None
        else [
            _execution_from_agent_run(run, contexts)
            for run in agent_runs
        ]
    )
    return {
        "strategy": strategy,
        "roles": [context.to_dict() for context in contexts],
        "role_contexts": len(contexts),
        "isolated_state_keys": sum(len(context.state_keys) for context in contexts),
        "role_runs": len(role_executions),
        "role_blocked_actions": sum(not execution.action_allowed_by_role for execution in role_executions),
        "review_repairs": review_repairs,
        "executions": [execution.to_dict() for execution in role_executions],
    }


def isolation_metadata() -> dict[str, object]:
    return build_isolation_evidence(strategy="isolated-harness")


def _context_from_definition(definition: AgentDefinition) -> RoleContext:
    legacy = next(
        (item for item in ROLE_CONTEXTS if item.role == definition.agent_id),
        None,
    )
    return RoleContext(
        role=definition.agent_id,
        visible_sections=() if legacy is None else legacy.visible_sections,
        hidden_sections=() if legacy is None else legacy.hidden_sections,
        allowed_actions=tuple(sorted(definition.capability_set)),
        state_keys=() if legacy is None else legacy.state_keys,
    )


def _execution_from_agent_run(
    run: AgentRunResult,
    contexts: list[RoleContext],
) -> RoleExecution:
    context = next(
        (item for item in contexts if item.role == run.definition_id),
        RoleContext(run.definition_id, (), (), (), ()),
    )
    tool_payloads = [
        item.payload
        for item in run.state.observations
        if item.kind == "tool_result"
    ]
    latest_tool = tool_payloads[-1] if tool_payloads else {}
    action = latest_tool.get("action", "none")
    attempted_action = action if isinstance(action, str) else "none"
    code = latest_tool.get("code")
    capability_blocked = code == "capability"
    message = latest_tool.get("message")
    summary = _artifact_summary(run)
    return RoleExecution(
        role=run.definition_id,
        phase={
            "planner": "plan",
            "implementer": "implement",
            "reviewer": "review",
        }.get(run.definition_id, "agent"),
        context_chars=run.state.metrics.context_chars_max,
        visible_sections=context.visible_sections,
        allowed_actions=context.allowed_actions,
        attempted_action=attempted_action,
        action_allowed_by_role=not capability_blocked,
        blocked_reason=(
            str(message)
            if capability_blocked and isinstance(message, str)
            else None
        ),
        summary=summary,
    )


def _artifact_summary(run: AgentRunResult) -> str | None:
    payloads = [
        item.payload
        for item in run.state.observations
        if item.kind == "agent_artifact"
    ]
    if len(payloads) != 1:
        return None
    try:
        artifact = parse_agent_artifact(payloads[0])
    except ValueError:
        return None
    if isinstance(artifact, PlanArtifact):
        return "; ".join(artifact.steps)
    if isinstance(artifact, ImplementationArtifact):
        return artifact.summary
    if isinstance(artifact, ReviewArtifact):
        return "; ".join(artifact.issues) or (
            "accepted" if artifact.accepted else "review completed"
        )
    return None
