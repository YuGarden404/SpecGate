from __future__ import annotations

import json
from html import escape
from pathlib import Path

import specgate.workspace_fs as workspace_fs
from specgate.approvals import approval_queue_path, read_approval_queue_if_present
from specgate.gate import GateResult
from specgate.memory import load_memory_summary
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary
from specgate.tool_registry import default_tool_registry
from specgate.trace import redact
from specgate.workspace_fs import WorkspacePathError


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


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(redact(str(value)))


def _read_optional_report_text(root: Path, relative: str) -> str | None:
    relative_path = Path(relative)
    current = root
    for part in relative_path.parent.parts:
        current = current / part
        if workspace_fs.bind_workspace_tree(current, missing_ok=True) is None:
            return None
    return workspace_fs.read_optional_workspace_text(
        root,
        relative,
        encoding="utf-8",
    )


def _render_approval_history(root: Path) -> str:
    try:
        queue = read_approval_queue_if_present(root, approval_queue_path(root))
    except WorkspacePathError as exc:
        return (
            "<h2>Approval History</h2>"
            f"<p>could not read approval history safely: {escape(exc.rule_family)}</p>"
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Approval History</h2>"
            f"<p>could not read approval history: {escape(str(redact(str(exc))))}</p>"
        )

    if queue is None or not queue.approvals:
        return "<h2>Approval History</h2><p>No approvals recorded.</p>"

    rows = "\n".join(
        "<tr>"
        f"<td>{escape(_safe_text(approval.id))}</td>"
        f"<td>{escape(_safe_text(approval.status))}</td>"
        f"<td>{escape(_safe_text(approval.action))}</td>"
        f"<td>{escape(_safe_text(approval.path))}</td>"
        f"<td>{escape(_safe_text(approval.reason))}</td>"
        f"<td>{escape(_safe_text(approval.decision_reason))}</td>"
        "</tr>"
        for approval in queue.approvals
    )
    return (
        "<h2>Approval History</h2>"
        "<table>"
        "<thead><tr><th>ID</th><th>Status</th><th>Action</th><th>Path</th>"
        "<th>Reason</th><th>Decision Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _render_retrieval_evidence(root: Path) -> str:
    text = _read_optional_report_text(root, "runs/latest/retrieval.json")
    if text is None:
        return "<h2>Retrieval Evidence</h2><p>No retrieval evidence recorded.</p>"

    try:
        data = json.loads(text)
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
    text = _read_optional_report_text(root, "runs/latest/compression.json")
    if text is None:
        return "<h2>Compression Evidence</h2><p>No compression evidence recorded.</p>"

    try:
        data = json.loads(text)
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
    text = _read_optional_report_text(root, "runs/latest/isolation.json")
    if text is None:
        return "<h2>Role Isolation Evidence</h2><p>No role isolation evidence recorded.</p>"

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("role isolation evidence must be an object")
        roles = data.get("roles", [])
        if not isinstance(roles, list):
            raise ValueError("role isolation roles must be a list")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Role Isolation Evidence</h2>"
            f"<p>could not read role isolation evidence: {escape(_safe_text(exc))}</p>"
        )

    executions = data.get("executions", [])
    if isinstance(executions, list) and executions:
        rows: list[str] = []
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            rows.append(
                "<tr>"
                f"<td>{escape(_safe_text(execution.get('role', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('phase', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('context_chars', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('attempted_action', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('action_allowed_by_role', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('blocked_reason', '')))}</td>"
                f"<td>{escape(_safe_text(execution.get('summary', '')))}</td>"
                "</tr>"
            )
        if rows:
            return (
                "<h2>Role Execution Evidence</h2>"
                "<table>"
                "<thead><tr><th>Role</th><th>Phase</th><th>Context Chars</th><th>Action</th><th>Allowed By Role</th><th>Blocked Reason</th><th>Summary</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                "</table>"
            )

    rows: list[str] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(_safe_text(role.get('role', '')))}</td>"
            f"<td>{escape(_safe_text(_render_jsonish(role.get('visible_sections', []))))}</td>"
            f"<td>{escape(_safe_text(_render_jsonish(role.get('hidden_sections', []))))}</td>"
            f"<td>{escape(_safe_text(_render_jsonish(role.get('allowed_actions', []))))}</td>"
            f"<td>{escape(_safe_text(_render_jsonish(role.get('state_keys', []))))}</td>"
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


def _render_prompt_injection_safety(root: Path) -> str:
    text = _read_optional_report_text(root, "runs/latest/security.json")
    if text is None:
        return "<h2>Prompt Injection Safety</h2><p>No prompt injection safety evidence recorded.</p>"

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("prompt injection safety evidence must be an object")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Prompt Injection Safety</h2>"
            f"<p>could not read prompt injection safety evidence: {escape(str(redact(str(exc))))}</p>"
        )

    rows = "\n".join(
        f"<tr><th>{escape(str(redact(str(key))))}</th><td>{escape(_render_jsonish(redact(value)))}</td></tr>"
        for key, value in data.items()
    )
    return f"<h2>Prompt Injection Safety</h2><table><tbody>{rows}</tbody></table>"


def _render_benchmark_summary(root: Path) -> str:
    text = _read_optional_report_text(root, "eval-runs/latest/benchmark.json")
    if text is None:
        return "<h2>Benchmark Summary</h2><p>No benchmark summary recorded.</p>"

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("benchmark summary must be an object")
        results = data.get("results", [])
        if not isinstance(results, list):
            raise ValueError("benchmark results must be a list")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            "<h2>Benchmark Summary</h2>"
            f"<p>could not read benchmark summary: {escape(str(exc))}</p>"
        )

    rows: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(str(result.get('strategy', '')))}</td>"
            f"<td>{escape(str(result.get('total_cases', 0)))}</td>"
            f"<td>{escape(str(result.get('passed_cases', 0)))}</td>"
            f"<td>{escape(str(result.get('expected_matches', 0)))}</td>"
            f"<td>{escape(str(result.get('avg_context_chars', 0)))}</td>"
            f"<td>{escape(str(result.get('avg_retrieved_chunks', 0)))}</td>"
            f"<td>{escape(str(result.get('blocked_actions', 0)))}</td>"
            f"<td>{escape(str(result.get('effective_blocked_actions', 0)))}</td>"
            f"<td>{escape(str(result.get('approval_requests', 0)))}</td>"
            f"<td>{escape(str(result.get('parse_errors', 0)))}</td>"
            f"<td>{escape(str(result.get('gate_runs', 0)))}</td>"
            f"<td>{escape(str(result.get('role_runs', 0)))}</td>"
            f"<td>{escape(str(result.get('role_blocked_actions', 0)))}</td>"
            f"<td>{escape(str(result.get('review_repairs', 0)))}</td>"
            "</tr>"
        )
    if not rows:
        return "<h2>Benchmark Summary</h2><p>No benchmark strategy rows recorded.</p>"
    return (
        "<h2>Benchmark Summary</h2>"
        "<table>"
        "<thead><tr><th>Strategy</th><th>Cases</th><th>Passed</th><th>Expected Matches</th>"
        "<th>Avg Context Chars</th><th>Avg Retrieved Chunks</th><th>Blocked Actions</th><th>Effective Blocks</th>"
        "<th>Approval Requests</th><th>Parse Errors</th><th>Gate Runs</th>"
        "<th>Role Runs</th><th>Role Blocks</th><th>Review Repairs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_jsonish(value: object) -> str:
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _strip_action_payload(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_action_payload(item)
            for key, item in value.items()
            if key != "action_payload"
        }
    if isinstance(value, list):
        return [_strip_action_payload(item) for item in value]
    return value


def _render_run_events(root: Path) -> str:
    text = _read_optional_report_text(root, "runs/latest/trace.jsonl")
    if text is None:
        return "<p>No trace events found.</p>"

    items: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            items.append("<li><strong>malformed trace event</strong></li>")
            continue
        event_type = str(event.get("event_type", "unknown"))
        payload = json.dumps(redact(_strip_action_payload(event.get("payload", {}))), ensure_ascii=False)
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
    workspace_fs.ensure_workspace_directory(root, "reports/latest")
    output = root / "reports" / "latest" / "index.html"
    issues = "\n".join(f"<li>{escape(issue.code)}: {escape(issue.message)}</li>" for issue in gate.issues)
    checks = "\n".join(f"<li>{escape(check.code)}: {'PASS' if check.passed else 'FAIL'}</li>" for check in gate.checks)
    tools = "\n".join(
        f"<li><strong>{escape(tool.name)}</strong> [{escape(tool.permission)}]: {escape(tool.description)}</li>"
        for tool in default_tool_registry().values()
    )
    trust_summary = _render_trust_summary(trust, profile)
    metrics_summary = _render_metrics(metrics)
    decisions_summary = _render_permission_decisions(permission_decisions)
    approval_history = _render_approval_history(root)
    retrieval_evidence = _render_retrieval_evidence(root)
    compression_evidence = _render_compression_evidence(root)
    role_isolation_evidence = _render_role_isolation_evidence(root)
    prompt_injection_safety = _render_prompt_injection_safety(root)
    benchmark_summary = _render_benchmark_summary(root)
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
  {approval_history}
  {retrieval_evidence}
  {compression_evidence}
  {role_isolation_evidence}
  {prompt_injection_safety}
  {benchmark_summary}
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
    workspace_fs.write_workspace_text(
        root,
        "reports/latest/index.html",
        html,
        encoding="utf-8",
    )
    return output
