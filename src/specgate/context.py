from __future__ import annotations

from pathlib import Path

from specgate.context_selector import ContextSelection, select_context_files
from specgate.gate import GateResult


def _artifact_summary(path: Path) -> str:
    if not path.exists():
        return "index.html 摘要：文件不存在"
    content = path.read_text(encoding="utf-8")
    node_count = content.count('class="node"') + content.count("class='node'")
    return f"index.html 摘要：{len(content)} 字符，node 出现 {node_count} 次"


def _render_manifest(selection: ContextSelection) -> str:
    lines = [
        f"budget_chars: {selection.budget_chars}",
        f"used_chars: {selection.used_chars}",
    ]
    for item in selection.files:
        lines.append(f"- {item.status}: {item.path} ({item.reason}, chars={item.chars})")
    return "\n".join(lines)


def _render_selected_files(selection: ContextSelection) -> str:
    blocks: list[str] = []
    for item in selection.files:
        if item.status not in {"selected", "truncated"}:
            continue
        blocks.append(f"### {item.path}\n```text\n{item.content}\n```")
    if not blocks:
        return "没有文件进入上下文。"
    return "\n\n".join(blocks)


def build_context_pack(root: Path, latest_gate: GateResult | None) -> str:
    selection = select_context_files(root)
    gate_summary = latest_gate.summary if latest_gate else "尚未运行 Gate"

    return "\n\n".join(
        [
            "你是 SpecGate harness 中的 coding agent。只输出严格 JSON action。",
            "## Context Manifest\n" + _render_manifest(selection),
            "## Selected Files\n" + _render_selected_files(selection),
            "## " + _artifact_summary(root / "index.html"),
            "## 最近 Gate 结果\n" + gate_summary,
        ]
    )
