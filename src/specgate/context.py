from __future__ import annotations

from pathlib import Path

from specgate.gate import GateResult


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _artifact_summary(path: Path) -> str:
    if not path.exists():
        return "index.html 摘要：文件不存在"
    content = path.read_text(encoding="utf-8")
    node_count = content.count('class="node"') + content.count("class='node'")
    return f"index.html 摘要：{len(content)} 字符，node 出现 {node_count} 次"


def build_context_pack(root: Path, latest_gate: GateResult | None) -> str:
    task_spec = _read_optional(root / "TASK_SPEC.md")
    checklist = _read_optional(root / "CHECKLIST.md")
    gate_summary = latest_gate.summary if latest_gate else "尚未运行 Gate"

    return "\n\n".join(
        [
            "你是 SpecGate harness 中的 coding agent。只输出严格 JSON action。",
            "## TASK_SPEC.md\n" + task_spec,
            "## CHECKLIST.md\n" + checklist,
            "## " + _artifact_summary(root / "index.html"),
            "## 最近 Gate 结果\n" + gate_summary,
        ]
    )
