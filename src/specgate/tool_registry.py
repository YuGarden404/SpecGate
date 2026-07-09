from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: str
    args_schema: dict[str, str]
    result_schema: dict[str, str]


def default_tool_registry() -> dict[str, ToolSpec]:
    tools = [
        ToolSpec(
            "read_file",
            "Read a UTF-8 text file allowed by workspace policy.",
            "read",
            {"path": "relative path allowed by policy"},
            {"path": "relative path", "content": "utf-8 text content"},
        ),
        ToolSpec(
            "write_file",
            "Write a UTF-8 text file allowed by workspace policy and snapshot protection.",
            "write",
            {"path": "relative path allowed by policy", "content": "utf-8 text content"},
            {"path": "written relative path"},
        ),
        ToolSpec(
            "replace_file",
            "Replace a UTF-8 text file allowed by workspace policy and snapshot protection.",
            "write",
            {"path": "relative path allowed by policy", "content": "utf-8 text content"},
            {"path": "replaced relative path"},
        ),
        ToolSpec(
            "list_files",
            "List files inside the workspace.",
            "inspect",
            {},
            {"files": "list of relative paths"},
        ),
        ToolSpec(
            "finish",
            "Finish the agent loop with a short summary.",
            "control",
            {"summary": "short final summary"},
            {"summary": "final summary"},
        ),
    ]
    return {tool.name: tool for tool in tools}


def render_tool_registry_for_context(registry: dict[str, ToolSpec] | None = None) -> str:
    selected = registry or default_tool_registry()
    lines: list[str] = []
    for name in sorted(selected):
        tool = selected[name]
        args = ", ".join(tool.args_schema) if tool.args_schema else "none"
        results = ", ".join(tool.result_schema) if tool.result_schema else "none"
        lines.append(f"- {tool.name} [{tool.permission}]: {tool.description}")
        lines.append(f"  args: {args}")
        lines.append(f"  result: {results}")
    return "\n".join(lines)
