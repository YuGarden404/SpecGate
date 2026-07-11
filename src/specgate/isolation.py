from __future__ import annotations

from dataclasses import asdict, dataclass


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


def build_role_contexts() -> list[RoleContext]:
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
) -> dict[str, object]:
    contexts = build_role_contexts()
    role_executions = executions or []
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
