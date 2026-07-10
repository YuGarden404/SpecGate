from __future__ import annotations

import json
from html import escape
from pathlib import Path

from specgate.approvals import ApprovalQueue, approval_queue_path
from specgate.gate import GateResult
from specgate.memory import load_memory_summary
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary
from specgate.tool_registry import default_tool_registry


def _render_trust_summary(trust: TrustSummary | None, profile: str = "strict") -> str:
    if trust is None:
        return (
            "<h2>Trust Summary</h2>"
            f"<p>Profile: {escape(profile)}</p>"
            "<p>No trust summary available.</p>"
        )

    reasons = "\n".join(f"<li>{escape(reason)}</li>" for reason in trust.reasons)
    if not reasons:
        reasons = "<li>No trust reasons recorded.</li>"
    return (
        "<h2>Trust Summary</h2>"
        f"<p>Profile: {escape(profile)}</p>"
        f"<p>Status: <strong>{escape(trust.status)}</strong></p>"
        f"<ul>{reasons}</ul>"
    )


def _render_metrics(metrics: RunMetrics | None) -> str:
    if metrics is None:
        return "<h2>Run Metrics</h2><p>No run metrics available.</p>"

    rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in metrics.to_dict().items()
    )
    return f"<h2>Run Metrics</h2><table><tbody>{rows}</tbody></table>"


def _render_permission_decisions(permission_decisions: list[PermissionDecision] | None) -> str:
    if not permission_decisions:
        return "<h2>Permission Decisions</h2><p>No permission decisions recorded.</p>"

    rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(decision.step))}</td>"
        f"<td>{escape(decision.action)}</td>"
        f"<td>{escape(decision.path or '')}</td>"
        f"<td>{'yes' if decision.allowed else 'no'}</td>"
        f"<td>{'yes' if decision.blocked else 'no'}</td>"
        f"<td>{escape(decision.reason)}</td>"
        f"<td>{escape(decision.profile)}</td>"
        f"<td>{escape(decision.rule_family)}</td>"
        "</tr>"
        for decision in permission_decisions
    )
    return (
        "<h2>Permission Decisions</h2>"
        "<table>"
        "<thead><tr>"
        "<th>Step</th><th>Action</th><th>Path</th><th>Allowed</th>"
        "<th>Blocked</th><th>Reason</th><th>Profile</th><th>Rule Family</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _render_pending_approvals(root: Path) -> str:
    try:
        queue = ApprovalQueue.read(approval_queue_path(root))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Pending Approvals</h2>"
            f"<p>could not read pending approvals: {escape(str(exc))}</p>"
        )

    if not queue.approvals:
        return "<h2>Pending Approvals</h2><p>No pending approvals.</p>"

    rows = "\n".join(
        "<tr>"
        f"<td>{escape(approval.id)}</td>"
        f"<td>{escape(approval.status)}</td>"
        f"<td>{escape(approval.action)}</td>"
        f"<td>{escape(approval.path or '')}</td>"
        f"<td>{escape(approval.reason)}</td>"
        "</tr>"
        for approval in queue.approvals
    )
    return (
        "<h2>Pending Approvals</h2>"
        "<table>"
        "<thead><tr><th>ID</th><th>Status</th><th>Action</th><th>Path</th><th>Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _render_retrieval_evidence(root: Path) -> str:
    retrieval_path = root / "runs" / "latest" / "retrieval.json"
    if not retrieval_path.exists():
        return "<h2>Retrieval Evidence</h2><p>No retrieval evidence recorded.</p>"

    try:
        data = json.loads(retrieval_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("retrieval evidence must be an object")
        selected_chunks = data.get("selected_chunks", [])
        if not isinstance(selected_chunks, list):
            raise ValueError("retrieval selected_chunks must be a list")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Retrieval Evidence</h2>"
            f"<p>could not read retrieval evidence: {escape(str(exc))}</p>"
        )

    query_terms = data.get("query_terms", [])
    terms_text = ", ".join(str(term) for term in query_terms) if isinstance(query_terms, list) else ""
    summary = (
        f"<p>Query terms: {escape(terms_text)}</p>"
        f"<p>Candidate chunks: {escape(str(data.get('candidate_count', 0)))}</p>"
    )
    if not selected_chunks:
        return "<h2>Retrieval Evidence</h2>" + summary + "<p>No chunks selected.</p>"

    rows: list[str] = []
    for chunk in selected_chunks:
        if not isinstance(chunk, dict):
            continue
        matched_terms = chunk.get("matched_terms", [])
        matched_text = ", ".join(str(term) for term in matched_terms) if isinstance(matched_terms, list) else ""
        rows.append(
            "<tr>"
            f"<td>{escape(str(chunk.get('path', '')))}</td>"
            f"<td>{escape(str(chunk.get('start_line', '')))}-{escape(str(chunk.get('end_line', '')))}</td>"
            f"<td>{escape(str(chunk.get('score', '')))}</td>"
            f"<td>{escape(matched_text)}</td>"
            f"<td>{escape(str(chunk.get('reason', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<h2>Retrieval Evidence</h2>" + summary + "<p>No valid chunks selected.</p>"

    return (
        "<h2>Retrieval Evidence</h2>"
        + summary
        + "<table>"
        + "<thead><tr><th>Path</th><th>Lines</th><th>Score</th><th>Matched Terms</th><th>Reason</th></tr></thead>"
        + f"<tbody>{''.join(rows)}</tbody>"
        + "</table>"
    )


def _render_compression_evidence(root: Path) -> str:
    compression_path = root / "runs" / "latest" / "compression.json"
    if not compression_path.exists():
        return "<h2>Compression Evidence</h2><p>No compression evidence recorded.</p>"

    try:
        data = json.loads(compression_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("compression evidence must be an object")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Compression Evidence</h2>"
            f"<p>could not read compression evidence: {escape(str(exc))}</p>"
        )

    rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(_render_jsonish(value))}</td></tr>"
        for key, value in data.items()
        if key != "rendered_events"
    )
    return f"<h2>Compression Evidence</h2><table><tbody>{rows}</tbody></table>"


def _render_role_isolation_evidence(root: Path) -> str:
    isolation_path = root / "runs" / "latest" / "isolation.json"
    if not isolation_path.exists():
        return "<h2>Role Isolation Evidence</h2><p>No role isolation evidence recorded.</p>"

    try:
        data = json.loads(isolation_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("role isolation evidence must be an object")
        roles = data.get("roles", [])
        if not isinstance(roles, list):
            raise ValueError("role isolation roles must be a list")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Role Isolation Evidence</h2>"
            f"<p>could not read role isolation evidence: {escape(str(exc))}</p>"
        )

    rows: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(str(role.get('role', '')))}</td>"
            f"<td>{escape(_render_jsonish(role.get('visible_sections', [])))}</td>"
            f"<td>{escape(_render_jsonish(role.get('hidden_sections', [])))}</td>"
            f"<td>{escape(_render_jsonish(role.get('allowed_actions', [])))}</td>"
            f"<td>{escape(_render_jsonish(role.get('state_keys', [])))}</td>"
            "</tr>"
        )
    if not rows:
        return "<h2>Role Isolation Evidence</h2><p>No role isolation roles recorded.</p>"
    return (
        "<h2>Role Isolation Evidence</h2>"
        "<table>"
        "<thead><tr><th>Role</th><th>Visible Sections</th><th>Hidden State</th><th>Allowed Actions</th><th>State Keys</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_jsonish(value: object) -> str:
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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


def generate_report(
    root: Path,
    gate: GateResult,
    steps: int,
    metrics: RunMetrics | None = None,
    permission_decisions: list[PermissionDecision] | None = None,
    trust: TrustSummary | None = None,
    profile: str = "strict",
) -> Path:
    report_dir = root / "reports" / "latest"
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "index.html"
    issues = "\n".join(f"<li>{escape(issue.code)}: {escape(issue.message)}</li>" for issue in gate.issues)
    checks = "\n".join(f"<li>{escape(check.code)}: {'PASS' if check.passed else 'FAIL'}</li>" for check in gate.checks)
    tools = "\n".join(
        f"<li><strong>{escape(tool.name)}</strong> [{escape(tool.permission)}]: {escape(tool.description)}</li>"
        for tool in default_tool_registry().values()
    )
    trust_summary = _render_trust_summary(trust, profile)
    metrics_summary = _render_metrics(metrics)
    decisions_summary = _render_permission_decisions(permission_decisions)
    pending_approvals = _render_pending_approvals(root)
    retrieval_evidence = _render_retrieval_evidence(root)
    compression_evidence = _render_compression_evidence(root)
    role_isolation_evidence = _render_role_isolation_evidence(root)
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
  <p>Steps: {escape(str(steps))}</p>
  <p>Gate: {escape(gate.summary)}</p>
  {trust_summary}
  {metrics_summary}
  {decisions_summary}
  {pending_approvals}
  {retrieval_evidence}
  {compression_evidence}
  {role_isolation_evidence}
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
