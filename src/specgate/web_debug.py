from __future__ import annotations

import json
import sqlite3
from collections import deque
from contextlib import closing
from pathlib import Path
from typing import Any

from specgate.runtime_config import RunRuntimeConfig, RuntimeConfigError
from specgate.trace import redact
from specgate.web_db import connect_db
from specgate.web_projects import RunPaths, project_paths, web_run_paths
from specgate.workspace_fs import (
    WorkspacePathError,
    open_workspace_file,
    workspace_file_metadata,
)


DEFAULT_MAX_TRACE_EVENTS = 200
DEFAULT_MAX_EVENT_CHARS = 4000
MAX_TRACE_EVENTS = 1000
MAX_EVENT_CHARS = 16_000
MAX_TRACE_LINE_BYTES = 64 * 1024
TRACE_RECORD_OVERHEAD_BYTES = 512
MAX_EVIDENCE_BYTES = 256 * 1024
SAFE_WORKSPACE_RULE_FAMILIES = frozenset(
    {
        "invalid_path",
        "linked_path",
        "path_escape",
        "path_race",
        "reparse_point",
        "unsafe_file_type",
    }
)
TRACE_SUMMARY_FIELDS = (
    "event_type",
    "event",
    "action",
    "status",
    "name",
    "tool",
    "tool_name",
    "phase",
    "timestamp",
    "message",
)


def build_run_debug(
    db_path: Path,
    data_root: Path,
    user_id: int,
    run_id: int,
    *,
    max_trace_events: int = DEFAULT_MAX_TRACE_EVENTS,
    max_event_chars: int = DEFAULT_MAX_EVENT_CHARS,
) -> dict[str, Any]:
    if not 1 <= max_trace_events <= MAX_TRACE_EVENTS:
        raise ValueError(f"max_trace_events must be between 1 and {MAX_TRACE_EVENTS}")
    if not 1 <= max_event_chars <= MAX_EVENT_CHARS:
        raise ValueError(f"max_event_chars must be between 1 and {MAX_EVENT_CHARS}")

    with closing(connect_db(db_path)) as conn:
        run = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise ValueError("run not found")
        project = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (run["project_id"], user_id),
        ).fetchone()
        if project is None:
            raise ValueError("project not found")
        artifacts = conn.execute(
            "select * from artifacts where run_id = ? order by kind, id",
            (run_id,),
        ).fetchall()
        approvals = conn.execute(
            "select * from approvals where run_id = ? order by id",
            (run_id,),
        ).fetchall()

    try:
        runtime_config = RunRuntimeConfig.from_json(
            run["runtime_config_json"]
        ).to_dict()
        runtime_config_error = None
    except RuntimeConfigError:
        runtime_config = None
        runtime_config_error = "invalid_runtime_config"

    paths = web_run_paths(
        project_paths(data_root, user_id, int(project["id"])),
        run_id,
    )
    artifact_payloads = [_artifact_dict(row, run_id, paths, data_root) for row in artifacts]
    approval_payloads = [_approval_dict(row) for row in approvals]
    trace = _read_trace(paths.audit, "trace.jsonl", max_trace_events, max_event_chars)
    evidence = {
        "retrieval": _read_json_evidence(paths.audit, "retrieval.json"),
        "compression": _read_json_evidence(paths.audit, "compression.json"),
        "isolation": _read_json_evidence(paths.audit, "isolation.json"),
        "security": _read_json_evidence(paths.audit, "security.json"),
    }

    return {
        "run": _run_dict(run),
        "project": _project_dict(project),
        "artifacts": artifact_payloads,
        "approvals": approval_payloads,
        "trace": trace,
        "evidence": evidence,
        "runtime_config": runtime_config,
        "runtime_config_error": runtime_config_error,
        "summary": {
            "status": run["status"],
            "trust_level": run["trust_level"],
            "has_artifacts": any(item["exists"] for item in artifact_payloads),
            "artifact_count": len(artifact_payloads),
            "approval_count": len(approval_payloads),
            "trace_event_count": len(trace["events"]),
        },
    }


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "project_id": data["project_id"],
        "status": data["status"],
        "prompt": redact(data["prompt"]),
        "trust_level": data["trust_level"],
        "error_message": redact(data["error_message"]),
        "created_at": data["created_at"],
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
        "has_index_artifact": bool(data["index_artifact_path"]),
        "has_zip_artifact": bool(data["zip_artifact_path"]),
    }


def _project_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "name": data["name"],
        "create_mode": data["create_mode"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "last_run_status": data["last_run_status"],
    }


def _artifact_dict(row: sqlite3.Row, run_id: int, paths: RunPaths, data_root: Path) -> dict[str, Any]:
    data = _row_dict(row)
    kind = data["kind"]
    expected_path = {
        "index": paths.index_artifact,
        "zip": paths.zip_artifact,
    }.get(kind)
    exists = False
    size_bytes = 0
    if expected_path is not None and Path(data["path"]) == expected_path:
        exists, size_bytes = _trusted_file_metadata(data_root, expected_path)
    download_url = None
    if kind == "index":
        download_url = f"/api/runs/{run_id}/artifacts/index"
    elif kind == "zip":
        download_url = f"/api/runs/{run_id}/artifacts/zip"
    return {
        "id": data["id"],
        "kind": kind,
        "exists": exists,
        "size_bytes": size_bytes,
        "download_url": download_url,
        "created_at": data["created_at"],
    }


def _trusted_file_metadata(data_root: Path, expected_path: Path) -> tuple[bool, int]:
    try:
        relative = expected_path.relative_to(data_root).as_posix()
        metadata = workspace_file_metadata(data_root, relative)
    except (OSError, RuntimeError, ValueError):
        return False, 0
    return True, metadata.size_bytes


def _approval_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "run_id": data["run_id"],
        "project_id": data["project_id"],
        "approval_id": data["approval_id"],
        "status": data["status"],
        "action_name": data["action_name"],
        "target_path": data["target_path"],
        "reason": redact(data["reason"]),
        "preview_json": redact(data["preview_json"]),
        "created_at": data["created_at"],
        "decided_at": data["decided_at"],
    }


def _read_trace(
    audit_root: Path,
    relative: str,
    max_events: int,
    max_event_chars: int,
) -> dict[str, Any]:
    try:
        records: deque[bytes | dict[str, Any]] = deque(maxlen=max_events)
        total_events = 0
        record_limit = min(
            MAX_TRACE_LINE_BYTES,
            max_event_chars * 4 + TRACE_RECORD_OVERHEAD_BYTES,
        )
        with open_workspace_file(audit_root, relative, "read") as handle:
            while True:
                raw_line = handle.readline(record_limit + 1)
                if not raw_line:
                    break
                line_too_long = len(raw_line) > record_limit
                if line_too_long:
                    while raw_line and not raw_line.endswith(b"\n"):
                        raw_line = handle.readline(record_limit + 1)
                    record: bytes | dict[str, Any] = {
                        "event_type": "trace_line_truncated",
                        "truncated": True,
                    }
                else:
                    if not raw_line.strip():
                        continue
                    record = raw_line
                total_events += 1
                records.append(record)
    except WorkspacePathError as exc:
        error = None if _is_optional_missing(exc, relative) else _audit_error(
            "audit trace unavailable",
            exc.rule_family,
        )
        return _empty_trace(max_events, max_event_chars, error=error)
    except OSError:
        return _empty_trace(
            max_events,
            max_event_chars,
            error=_audit_error("audit trace unavailable", "path_race"),
        )

    selected = [_parse_trace_record(record, max_event_chars) for record in records]
    return {
        "events": selected,
        "truncated": total_events > max_events
        or any(event.get("truncated") for event in selected),
        "max_events": max_events,
        "max_event_chars": max_event_chars,
        "total_events": total_events,
    }


def _parse_trace_record(
    record: bytes | dict[str, Any],
    max_event_chars: int,
) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    try:
        line = record.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "event_type": "trace_decode_error",
            "truncated": True,
        }
    return _parse_trace_line(line, max_event_chars)


def _empty_trace(
    max_events: int,
    max_event_chars: int,
    *,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "events": [],
        "truncated": False,
        "max_events": max_events,
        "max_event_chars": max_event_chars,
    }
    if error is not None:
        trace["error"] = error
    return trace


def _parse_trace_line(line: str, max_event_chars: int) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        event = {"event_type": "trace_parse_error", "message": str(redact(str(exc)))}
    if not isinstance(event, dict):
        event = {"event_type": "trace_value", "value": event}
    event = redact(event)
    return _truncate_event(event, max_event_chars)


def _truncate_event(event: dict[str, Any], max_event_chars: int) -> dict[str, Any]:
    serialized = json.dumps(event, ensure_ascii=False, sort_keys=True)
    if len(serialized) <= max_event_chars:
        return event
    summary: dict[str, Any] = {"truncated": True}
    field_chars = min(128, max(16, max_event_chars // 8))
    for key in TRACE_SUMMARY_FIELDS:
        value = event.get(key)
        if isinstance(value, str):
            summary[key] = (
                value
                if len(value) <= field_chars
                else value[:field_chars] + "...[truncated]"
            )
        elif value is None or isinstance(value, (bool, int, float)):
            if key in event:
                summary[key] = value
    summary["preview"] = serialized[:max_event_chars] + "...[truncated]"
    return summary


def _read_json_evidence(audit_root: Path, relative: str) -> Any:
    try:
        with open_workspace_file(audit_root, relative, "read") as handle:
            raw_content = handle.read(MAX_EVIDENCE_BYTES + 1)
    except WorkspacePathError as exc:
        if _is_optional_missing(exc, relative):
            return None
        return _audit_error("audit evidence unavailable", exc.rule_family)
    except OSError:
        return _audit_error("audit evidence unavailable", "path_race")
    if len(raw_content) > MAX_EVIDENCE_BYTES:
        return {
            "error": "audit evidence exceeds size limit",
            "truncated": True,
            "max_bytes": MAX_EVIDENCE_BYTES,
        }
    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "audit evidence is not valid UTF-8"}
    try:
        evidence = redact(json.loads(content))
        return None if evidence == {} else evidence
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {"error": str(redact(str(exc)))}


def _is_optional_missing(exc: WorkspacePathError, relative: str) -> bool:
    return exc.rule_family == "path_race" and exc.missing_path == relative


def _audit_error(message: str, rule_family: str) -> dict[str, str]:
    safe_family = (
        rule_family if rule_family in SAFE_WORKSPACE_RULE_FAMILIES else "path_race"
    )
    return {"error": message, "rule_family": safe_family}
