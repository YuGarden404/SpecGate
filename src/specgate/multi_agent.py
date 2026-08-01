from __future__ import annotations

from specgate.agent_service import AgentBudget, AgentDefinition


ROLE_SEQUENCE = ("planner", "implementer", "reviewer")


def phase_for_role(role: str) -> str:
    phases = {"planner": "plan", "implementer": "implement", "reviewer": "review"}
    if role not in phases:
        raise ValueError(f"unknown role: {role}")
    return phases[role]


def build_agent_definitions(
    *,
    context_chars: int,
    include_skill_tools: bool = False,
) -> tuple[AgentDefinition, ...]:
    skill_capabilities = (
        frozenset({"load_skill", "read_skill_resource"})
        if include_skill_tools
        else frozenset()
    )
    read_capabilities = frozenset(
        {"read_file", "list_files", "finish"}
    ) | skill_capabilities
    write_capabilities = read_capabilities | frozenset(
        {"write_file", "replace_file"}
    )
    budget = AgentBudget(
        max_steps=1,
        context_chars=context_chars,
        child_runs=0,
    )
    return (
        AgentDefinition(
            agent_id="planner",
            instructions=(
                "Produce a PlanArtifact. Call finish once with the complete "
                "PlanArtifact JSON in args.summary."
            ),
            capability_set=read_capabilities,
            context_policy="multi-agent-isolated",
            budget=budget,
        ),
        AgentDefinition(
            agent_id="implementer",
            instructions=(
                "Apply one implementation action from the supplied artifacts. "
                "A successful workspace write produces an "
                "ImplementationArtifact. If no write is needed, call finish "
                "with complete ImplementationArtifact JSON in args.summary."
            ),
            capability_set=write_capabilities,
            context_policy="multi-agent-isolated",
            budget=budget,
        ),
        AgentDefinition(
            agent_id="reviewer",
            instructions=(
                "Produce a ReviewArtifact. Call finish once with the complete "
                "ReviewArtifact JSON in args.summary. Use the typed "
                "repair_required field to request a repair."
            ),
            capability_set=read_capabilities,
            context_policy="multi-agent-isolated",
            budget=budget,
        ),
    )
