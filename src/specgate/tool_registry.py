from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class PermissionClass(str, Enum):
    READ = "read"
    WRITE = "write"
    INSPECT = "inspect"
    CONTROL = "control"


class SideEffectClass(str, Enum):
    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    RUN_CONTROL = "run_control"


class _ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileArgs(_ToolModel):
    path: str


class ReadFileResult(_ToolModel):
    path: str
    content: str


class WriteFileArgs(_ToolModel):
    path: str
    content: str


class WriteFileResult(_ToolModel):
    path: str


class ListFilesArgs(_ToolModel):
    pass


class ListFilesResult(_ToolModel):
    files: list[str]


class FinishArgs(_ToolModel):
    summary: str = ""


class FinishResult(_ToolModel):
    summary: str


class ToolHandler(Protocol):
    def execute(self, args: BaseModel, context: Any) -> BaseModel | dict[str, Any]: ...


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str


@dataclass(frozen=True)
class ToolDefinition:
    metadata: ToolMetadata
    permission_class: PermissionClass
    side_effect_class: SideEffectClass
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def permission(self) -> str:
        return self.permission_class.value

    @property
    def args_schema(self) -> dict[str, str]:
        return {name: str(field.annotation) for name, field in self.args_model.model_fields.items()}

    @property
    def result_schema(self) -> dict[str, str]:
        return {
            name: str(field.annotation)
            for name, field in self.result_model.model_fields.items()
        }


class DuplicateToolError(ValueError):
    pass


class UnknownToolError(KeyError):
    pass


class ToolRegistry(Mapping[str, ToolDefinition]):
    def __init__(self, definitions: Iterable[ToolDefinition] = ()):
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise DuplicateToolError(definition.name)
        self._definitions[definition.name] = definition

    def resolve(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def __getitem__(self, name: str) -> ToolDefinition:
        return self.resolve(name)

    def __iter__(self) -> Iterator[str]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def values(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())


def default_tool_definitions() -> tuple[ToolDefinition, ...]:
    from specgate.tool_handlers import (
        FinishHandler,
        ListFilesHandler,
        ReadFileHandler,
        ReplaceFileHandler,
        WriteFileHandler,
    )

    return (
        ToolDefinition(
            ToolMetadata("read_file", "Read allowed UTF-8 workspace text."),
            PermissionClass.READ,
            SideEffectClass.NONE,
            ReadFileArgs,
            ReadFileResult,
            ReadFileHandler(),
        ),
        ToolDefinition(
            ToolMetadata("write_file", "Write allowed UTF-8 workspace text."),
            PermissionClass.WRITE,
            SideEffectClass.WORKSPACE_WRITE,
            WriteFileArgs,
            WriteFileResult,
            WriteFileHandler(),
        ),
        ToolDefinition(
            ToolMetadata("replace_file", "Replace allowed UTF-8 workspace text."),
            PermissionClass.WRITE,
            SideEffectClass.WORKSPACE_WRITE,
            WriteFileArgs,
            WriteFileResult,
            ReplaceFileHandler(),
        ),
        ToolDefinition(
            ToolMetadata("list_files", "List policy-readable workspace files."),
            PermissionClass.INSPECT,
            SideEffectClass.NONE,
            ListFilesArgs,
            ListFilesResult,
            ListFilesHandler(),
        ),
        ToolDefinition(
            ToolMetadata("finish", "Request final Gate and completion."),
            PermissionClass.CONTROL,
            SideEffectClass.RUN_CONTROL,
            FinishArgs,
            FinishResult,
            FinishHandler(),
        ),
    )


def default_tool_registry() -> ToolRegistry:
    return ToolRegistry(default_tool_definitions())


def render_tool_registry_for_context(
    registry: Mapping[str, ToolDefinition] | None = None,
) -> str:
    selected = default_tool_registry() if registry is None else registry
    lines: list[str] = []
    for tool in selected.values():
        args = ", ".join(tool.args_schema) if tool.args_schema else "none"
        results = ", ".join(tool.result_schema) if tool.result_schema else "none"
        lines.append(f"- {tool.name} [{tool.permission}]: {tool.description}")
        lines.append(f"  args: {args}")
        lines.append(f"  result: {results}")
    return "\n".join(lines)


# Retain the imported name used by the legacy dispatcher until its Task 6 migration.
ToolSpec = ToolDefinition
