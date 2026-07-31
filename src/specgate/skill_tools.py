from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from specgate.skill_registry import SkillRegistry, SkillRegistryError, SkillSession
from specgate.tool_handlers import ToolExecutionContext, ToolExecutionError


class _SkillToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoadSkillArgs(_SkillToolModel):
    name: str


class LoadSkillResult(_SkillToolModel):
    name: str
    instructions: str


class ReadSkillResourceArgs(_SkillToolModel):
    name: str
    path: str


class ReadSkillResourceResult(_SkillToolModel):
    name: str
    path: str
    content: str


class LoadSkillHandler:
    def execute(
        self,
        args: LoadSkillArgs,
        context: ToolExecutionContext,
    ) -> LoadSkillResult:
        registry, session = _require_skill_runtime(context)
        try:
            instructions = registry.load(args.name)
            session.activate(instructions.name)
        except SkillRegistryError as exc:
            raise _skill_error(exc) from exc
        return LoadSkillResult(
            name=instructions.name,
            instructions=instructions.body,
        )


class ReadSkillResourceHandler:
    def execute(
        self,
        args: ReadSkillResourceArgs,
        context: ToolExecutionContext,
    ) -> ReadSkillResourceResult:
        registry, session = _require_skill_runtime(context)
        try:
            instructions = registry.load(args.name)
            if instructions.name not in session.active_names:
                raise ToolExecutionError(
                    "inactive_skill",
                    "skill must be loaded before reading its resources",
                    blocked=True,
                    rule_family="skill",
                )
            resource = registry.read_resource(instructions.name, args.path)
        except ToolExecutionError:
            raise
        except SkillRegistryError as exc:
            raise _skill_error(exc) from exc
        return ReadSkillResourceResult(
            name=resource.name,
            path=resource.path,
            content=resource.content,
        )


def _require_skill_runtime(
    context: ToolExecutionContext,
) -> tuple[SkillRegistry, SkillSession]:
    if context.skill_registry is None or context.skill_session is None:
        raise ToolExecutionError(
            "skill_runtime_unavailable",
            "skill runtime is not configured",
            blocked=True,
            rule_family="skill",
        )
    return context.skill_registry, context.skill_session


def _skill_error(error: SkillRegistryError) -> ToolExecutionError:
    code = getattr(error, "code", str(error))
    return ToolExecutionError(
        code,
        f"skill operation failed: {code}",
        blocked=True,
        rule_family="skill",
    )
