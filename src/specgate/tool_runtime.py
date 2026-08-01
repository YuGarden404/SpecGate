from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from specgate.actions import Action
from specgate.tool_handlers import ToolExecutionContext, ToolExecutionError
from specgate.tool_registry import ToolDefinition, ToolRegistry, UnknownToolError


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    rule_family: str = "none"
    code: str = "legacy"

    @classmethod
    def success(
        cls,
        action: str,
        data: dict[str, Any],
        *,
        message: str = "tool completed",
    ) -> ToolResult:
        return cls(True, action, message, data, code="ok")

    @classmethod
    def failure(
        cls,
        action: str,
        code: str,
        *,
        message: str = "tool failed",
        data: dict[str, Any] | None = None,
        blocked: bool = False,
        rule_family: str = "none",
    ) -> ToolResult:
        return cls(
            False,
            action,
            message,
            {} if data is None else data,
            blocked=blocked,
            rule_family=rule_family,
            code=code,
        )


@dataclass(frozen=True)
class PreparedToolCall:
    definition: ToolDefinition
    args: BaseModel


@dataclass(frozen=True)
class ToolPreparation:
    call: PreparedToolCall | None = None
    failure: ToolResult | None = None


class ToolRuntime:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def prepare(self, action: Action) -> ToolPreparation:
        try:
            definition = self.registry.resolve(action.action)
            args = definition.args_model.model_validate(action.args)
        except UnknownToolError:
            return ToolPreparation(
                failure=ToolResult.failure(
                    action.action,
                    "unknown_tool",
                    message=f"unknown tool: {action.action}",
                    blocked=True,
                    rule_family="action",
                )
            )
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(map(str, item["loc"])) for item in exc.errors()
            )
            return ToolPreparation(
                failure=ToolResult.failure(
                    action.action,
                    "tool_validation_failed",
                    message=f"invalid tool arguments: {fields}",
                    blocked=True,
                    rule_family="tool",
                )
            )
        return ToolPreparation(call=PreparedToolCall(definition, args))

    def execute_prepared(
        self,
        call: PreparedToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        try:
            raw_result = call.definition.handler.execute(call.args, context)
            result = call.definition.result_model.model_validate(raw_result)
        except ToolExecutionError as exc:
            data: dict[str, Any] = {}
            path = getattr(call.args, "path", None)
            if isinstance(path, str):
                data["path"] = path
            if exc.rule_family != "none":
                data["rule_family"] = exc.rule_family
            return ToolResult.failure(
                call.definition.name,
                exc.code,
                message=exc.safe_message,
                data=data,
                blocked=exc.blocked,
                rule_family=exc.rule_family,
            )
        return ToolResult.success(
            call.definition.name,
            result.model_dump(mode="json"),
        )
