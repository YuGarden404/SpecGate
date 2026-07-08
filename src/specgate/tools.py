from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False


class ToolDispatcher:
    def __init__(self, policy: WorkspacePolicy):
        self.policy = policy

    def dispatch(self, action: Action) -> ToolResult:
        decision = check_action(action, self.policy)
        if not decision.allowed:
            return ToolResult(False, action.action, decision.reason, blocked=True)

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

        return ToolResult(False, action.action, f"unimplemented action: {action.action}", blocked=True)

    def _resolve(self, relative: str) -> Path:
        return self.policy.root / relative

    def _write_file(self, action: Action) -> ToolResult:
        path = self._resolve(action.args["path"])
        content = action.args.get("content", "")
        if not isinstance(content, str):
            return ToolResult(False, action.action, "content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(True, action.action, f"wrote {action.args['path']}", {"path": action.args["path"]})

    def _read_file(self, action: Action) -> ToolResult:
        path = self._resolve(action.args["path"])
        if not path.exists():
            return ToolResult(False, action.action, f"file not found: {action.args['path']}")
        return ToolResult(
            True,
            action.action,
            f"read {action.args['path']}",
            {"path": action.args["path"], "content": path.read_text(encoding="utf-8")},
        )

    def _list_files(self, action: Action) -> ToolResult:
        files = sorted(
            str(path.relative_to(self.policy.root)).replace("\\", "/")
            for path in self.policy.root.rglob("*")
            if path.is_file()
        )
        return ToolResult(True, action.action, "listed files", {"files": files})
