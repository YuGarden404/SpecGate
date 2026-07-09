from __future__ import annotations

import json
from html import escape
from pathlib import Path

from specgate.gate import GateResult
from specgate.memory import load_memory_summary
from specgate.tool_registry import default_tool_registry


def _render_run_events(root: Path) -> str:
    trace_path = root / "runs" / "latest" / "trace.jsonl"
    if not trace_path.exists():
        return "<p>No trace events found.</p>"

    items: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            items.append(f"<li><strong>invalid_trace_line</strong>: <code>{escape(line[:240])}</code></li>")
            continue
        event_type = str(event.get("event_type", "unknown"))
        payload = json.dumps(event.get("payload", {}), ensure_ascii=False)
        if len(payload) > 500:
            payload = payload[:500] + "...[truncated]"
        items.append(f"<li><strong>{escape(event_type)}</strong>: <code>{escape(payload)}</code></li>")

    if not items:
        return "<p>No trace events found.</p>"
    return "<ol>" + "\n".join(items) + "</ol>"


def generate_report(root: Path, gate: GateResult, steps: int) -> Path:
    report_dir = root / "reports" / "latest"
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "index.html"
    issues = "\n".join(f"<li>{escape(issue.code)}: {escape(issue.message)}</li>" for issue in gate.issues)
    checks = "\n".join(f"<li>{escape(check.code)}: {'PASS' if check.passed else 'FAIL'}</li>" for check in gate.checks)
    tools = "\n".join(
        f"<li><strong>{escape(tool.name)}</strong> [{escape(tool.permission)}]: {escape(tool.description)}</li>"
        for tool in default_tool_registry().values()
    )
    events = _render_run_events(root)
    memory = escape(load_memory_summary(root))
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpecGate Run Report</title>
  <style>body{{font-family:Arial,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;line-height:1.5}}</style>
</head>
<body>
  <h1>SpecGate Run Report</h1>
  <p>Steps: {steps}</p>
  <p>Gate: {escape(gate.summary)}</p>
  <h2>Checks</h2>
  <ul>{checks}</ul>
  <h2>Issues</h2>
  <ul>{issues}</ul>
  <h2>Tools</h2>
  <ul>{tools}</ul>
  <h2>Run Events</h2>
  {events}
  <h2>Memory Summary</h2>
  <pre>{memory}</pre>
  <p><a href="../../index.html">Final artifact</a></p>
</body>
</html>"""
    output.write_text(html, encoding="utf-8")
    return output
