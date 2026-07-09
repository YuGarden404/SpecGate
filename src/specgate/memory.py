from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from specgate.trace import redact


MEMORY_FILE = "memory.json"
MAX_MEMORY_RUNS = 5
MAX_SUMMARY_CHARS = 500


def _safe_summary(summary: str) -> str:
    redacted = redact(summary)
    text = redacted if isinstance(redacted, str) else str(redacted)
    if len(text) > MAX_SUMMARY_CHARS:
        return text[:MAX_SUMMARY_CHARS] + "...[truncated]"
    return text


def _memory_path(root: Path) -> Path:
    return root / MEMORY_FILE


def _load_memory(root: Path) -> dict[str, Any]:
    path = _memory_path(root)
    if not path.exists():
        return {"runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return {"runs": []}
    return data


def append_memory(root: Path, passed: bool, steps: int, gate_summary: str) -> Path:
    data = _load_memory(root)
    runs = data["runs"]
    runs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passed": passed,
            "steps": steps,
            "gate_summary": _safe_summary(gate_summary),
        }
    )
    data["runs"] = runs[-MAX_MEMORY_RUNS:]
    path = _memory_path(root)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_memory_summary(root: Path) -> str:
    runs = _load_memory(root)["runs"]
    if not runs:
        return "No cross-session memory yet."
    lines: list[str] = []
    for index, item in enumerate(runs[-MAX_MEMORY_RUNS:], 1):
        if not isinstance(item, dict):
            continue
        lines.append(
            " | ".join(
                [
                    f"run {index}",
                    f"passed={item.get('passed')}",
                    f"steps={item.get('steps')}",
                    f"gate={_safe_summary(str(item.get('gate_summary', '')))}",
                ]
            )
        )
    return "\n".join(lines) if lines else "No cross-session memory yet."
