from __future__ import annotations

from dataclasses import dataclass

import specgate.workspace_fs as workspace_fs
from specgate.policy import WorkspacePolicy
from specgate.snapshot import FileSnapshot
from specgate.tool_registry import (
    FinishArgs,
    FinishResult,
    ListFilesArgs,
    ListFilesResult,
    ReadFileArgs,
    ReadFileResult,
    WriteFileArgs,
    WriteFileResult,
)


@dataclass(frozen=True)
class ToolExecutionContext:
    policy: WorkspacePolicy
    snapshot: FileSnapshot | None


class ToolExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        blocked: bool = False,
        rule_family: str = "none",
    ):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.blocked = blocked
        self.rule_family = rule_family


class ReadFileHandler:
    def execute(
        self,
        args: ReadFileArgs,
        context: ToolExecutionContext,
    ) -> ReadFileResult:
        try:
            content = workspace_fs.read_workspace_text(
                context.policy.root,
                args.path,
                encoding="utf-8",
            )
        except UnicodeDecodeError as exc:
            raise ToolExecutionError(
                "invalid_encoding",
                f"invalid UTF-8 encoding: {args.path}",
                blocked=True,
                rule_family="invalid_encoding",
            ) from exc
        except workspace_fs.WorkspacePathError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                raise ToolExecutionError(
                    "tool_execution_failed",
                    f"file not found: {args.path}",
                ) from exc
            raise _blocked_path_error(exc) from exc
        return ReadFileResult(path=args.path, content=content)


class WriteFileHandler:
    def execute(
        self,
        args: WriteFileArgs,
        context: ToolExecutionContext,
    ) -> WriteFileResult:
        if context.snapshot is not None:
            snapshot_decision = context.snapshot.check_unchanged(args.path)
            if not snapshot_decision.allowed:
                raise ToolExecutionError(
                    snapshot_decision.rule_family,
                    snapshot_decision.reason,
                    blocked=True,
                    rule_family=snapshot_decision.rule_family,
                )

        try:
            workspace_fs.write_workspace_text(
                context.policy.root,
                args.path,
                args.content,
                encoding="utf-8",
            )
            if context.snapshot is not None:
                context.snapshot.update_after_write(args.path)
        except workspace_fs.WorkspacePathError as exc:
            raise _blocked_path_error(exc) from exc
        return WriteFileResult(path=args.path)


class ReplaceFileHandler(WriteFileHandler):
    pass


class ListFilesHandler:
    def execute(
        self,
        args: ListFilesArgs,
        context: ToolExecutionContext,
    ) -> ListFilesResult:
        del args
        try:
            files = []
            for relative_path in sorted(context.policy.allowed_read_paths):
                state = workspace_fs.workspace_file_state(
                    context.policy.root,
                    relative_path,
                )
                if state.exists:
                    files.append(relative_path)
        except workspace_fs.WorkspacePathError as exc:
            raise _blocked_path_error(exc) from exc
        return ListFilesResult(files=files)


class FinishHandler:
    def execute(
        self,
        args: FinishArgs,
        context: ToolExecutionContext,
    ) -> FinishResult:
        del context
        return FinishResult(summary=args.summary)


def _blocked_path_error(error: workspace_fs.WorkspacePathError) -> ToolExecutionError:
    return ToolExecutionError(
        error.rule_family,
        f"{error.rule_family}: {error.message}",
        blocked=True,
        rule_family=error.rule_family,
    )
