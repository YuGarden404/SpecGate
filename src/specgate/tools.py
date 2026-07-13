from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import specgate.workspace_fs as workspace_fs
from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action
from specgate.snapshot import FileSnapshot
from specgate.tool_registry import ToolSpec, default_tool_registry


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    rule_family: str = "none"


class ToolDispatcher:
    def __init__(
        self,
        policy: WorkspacePolicy,
        snapshot: FileSnapshot | None = None,
        registry: dict[str, ToolSpec] | None = None,
    ):
        self.policy = policy
        self.snapshot = snapshot
        self.registry = default_tool_registry() if registry is None else registry

    def dispatch(self, action: Action) -> ToolResult:
        if action.action not in self.registry:
            return ToolResult(
                False,
                action.action,
                f"unknown action: {action.action}",
                blocked=True,
                rule_family="action",
            )

        decision = check_action(action, self.policy)
        if not decision.allowed:
            data = {}
            if decision.rule_family != "none":
                data["rule_family"] = decision.rule_family
            return ToolResult(
                False,
                action.action,
                decision.reason,
                data,
                blocked=True,
                rule_family=decision.rule_family,
            )

        if action.action == "write_file":
            return self._write_file(action)
        if action.action == "replace_file":
            return self._write_file(action)
        if action.action == "read_file":
            return self._read_file(action)
        if action.action == "list_files":
            return self._list_files(action)
        if action.action == "finish":
            return ToolResult(
                True,
                "finish",
                "finish requested",
                {"summary": action.args.get("summary", "")},
            )

        return ToolResult(
            False,
            action.action,
            f"unimplemented action: {action.action}",
            blocked=True,
            rule_family="action",
        )

    def _write_file(self, action: Action) -> ToolResult:
        relative_path = action.args["path"]
        if self.snapshot is not None:
            snapshot_decision = self.snapshot.check_unchanged(relative_path)
            if not snapshot_decision.allowed:
                data = {"path": relative_path}
                if snapshot_decision.rule_family != "none":
                    data["rule_family"] = snapshot_decision.rule_family
                return ToolResult(
                    False,
                    action.action,
                    snapshot_decision.reason,
                    data,
                    blocked=True,
                    rule_family=snapshot_decision.rule_family,
                )

        content = action.args.get("content", "")
        if not isinstance(content, str):
            return ToolResult(False, action.action, "content must be a string")
        try:
            workspace_fs.write_workspace_text(
                self.policy.root,
                relative_path,
                content,
                encoding="utf-8",
            )
            if self.snapshot is not None:
                self.snapshot.update_after_write(relative_path)
        except workspace_fs.WorkspacePathError as exc:
            return self._blocked_path_result(action, exc)
        return ToolResult(True, action.action, f"wrote {relative_path}", {"path": relative_path})

    def _read_file(self, action: Action) -> ToolResult:
        relative_path = action.args["path"]
        try:
            content = workspace_fs.read_workspace_text(
                self.policy.root,
                relative_path,
                encoding="utf-8",
            )
        except workspace_fs.WorkspacePathError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return ToolResult(False, action.action, f"file not found: {relative_path}")
            return self._blocked_path_result(action, exc)
        return ToolResult(
            True,
            action.action,
            f"read {relative_path}",
            {"path": relative_path, "content": content},
        )

    def _list_files(self, action: Action) -> ToolResult:
        try:
            files = sorted(
                relative_path
                for relative_path in workspace_fs.iter_workspace_files(self.policy.root)
                if relative_path in self.policy.allowed_read_paths
            )
        except workspace_fs.WorkspacePathError as exc:
            return self._blocked_path_result(action, exc)
        return ToolResult(True, action.action, "listed files", {"files": files})

    def _blocked_path_result(
        self,
        action: Action,
        error: workspace_fs.WorkspacePathError,
    ) -> ToolResult:
        data: dict[str, Any] = {"rule_family": error.rule_family}
        relative_path = action.args.get("path")
        if isinstance(relative_path, str):
            data["path"] = relative_path
        return ToolResult(
            False,
            action.action,
            f"{error.rule_family}: {error.message}",
            data,
            blocked=True,
            rule_family=error.rule_family,
        )
