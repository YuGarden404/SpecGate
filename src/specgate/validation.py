from __future__ import annotations

from typing import Protocol

from specgate.tool_registry import SideEffectClass
from specgate.tool_runtime import PreparedToolCall, ToolResult


class ValidationPolicy(Protocol):
    def should_validate(
        self,
        call: PreparedToolCall,
        result: ToolResult,
    ) -> bool: ...


class DefaultValidationPolicy:
    def should_validate(
        self,
        call: PreparedToolCall,
        result: ToolResult,
    ) -> bool:
        del result
        return call.definition.side_effect_class in {
            SideEffectClass.WORKSPACE_WRITE,
            SideEffectClass.RUN_CONTROL,
        }
