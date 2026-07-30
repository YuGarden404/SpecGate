from __future__ import annotations

from collections.abc import Mapping

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action
from specgate.snapshot import FileSnapshot
from specgate.tool_handlers import ToolExecutionContext
from specgate.tool_registry import ToolDefinition, ToolRegistry, default_tool_registry
from specgate.tool_runtime import ToolPreparation, ToolResult, ToolRuntime


class ToolDispatcher:
    def __init__(
        self,
        policy: WorkspacePolicy,
        snapshot: FileSnapshot | None = None,
        registry: ToolRegistry | Mapping[str, ToolDefinition] | None = None,
    ):
        self.policy = policy
        self.snapshot = snapshot
        self.registry = self._adapt_registry(registry)
        self.runtime = ToolRuntime(self.registry)

    @staticmethod
    def _adapt_registry(
        registry: ToolRegistry | Mapping[str, ToolDefinition] | None,
    ) -> ToolRegistry:
        if registry is None:
            return default_tool_registry()
        if isinstance(registry, ToolRegistry):
            return registry
        return ToolRegistry(registry.values())

    def prepare(self, action: Action) -> ToolPreparation:
        return self.runtime.prepare(action)

    def dispatch(self, action: Action) -> ToolResult:
        decision = check_action(action, self.policy)
        if not decision.allowed:
            data = {}
            if decision.rule_family != "none":
                data["rule_family"] = decision.rule_family
            return ToolResult.failure(
                action.action,
                (
                    decision.rule_family
                    if decision.rule_family != "none"
                    else "policy_denied"
                ),
                message=decision.reason,
                data=data,
                blocked=True,
                rule_family=decision.rule_family,
            )

        preparation = self.runtime.prepare(action)
        if preparation.failure is not None:
            if preparation.failure.code == "unknown_tool":
                return ToolResult.failure(
                    action.action,
                    "unknown_tool",
                    message=f"unknown action: {action.action}",
                    blocked=True,
                    rule_family="action",
                )
            return preparation.failure
        assert preparation.call is not None
        return self.runtime.execute_prepared(
            preparation.call,
            ToolExecutionContext(self.policy, self.snapshot),
        )
