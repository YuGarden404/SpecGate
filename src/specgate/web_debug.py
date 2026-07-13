from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Any

from specgate.trace import redact
from specgate.web_db import connect_db
from specgate.web_projects import RunPaths, project_paths, web_run_paths


DEFAULT_MAX_TRACE_EVENTS = 200
DEFAULT_MAX_EVENT_CHARS = 4000


def build_run_debug(
    db_path: Path,
    data_root: Path,
    user_id: int,
    run_id: int,
    *,
    max_trace_events: int = DEFAULT_MAX_TRACE_EVENTS,
    max_event_chars: int = DEFAULT_MAX_EVENT_CHARS,
) -> dict[str, Any]:
    if max_trace_events < 1:
        raise ValueError("max_trace_events must be positive")
    if max_event_chars < 1:
        raise ValueError("max_event_chars must be positive")

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

    paths = web_run_paths(
        project_paths(data_root, user_id, int(project["id"])),
        run_id,
    )
    artifact_payloads = [_artifact_dict(row, run_id, paths, data_root) for row in artifacts]
    approval_payloads = [_approval_dict(row) for row in approvals]
    trace = _read_trace(paths.audit / "trace.jsonl", max_trace_events, max_event_chars)
    evidence = {
        "retrieval": _read_json_evidence(paths.audit / "retrieval.json"),
        "compression": _read_json_evidence(paths.audit / "compression.json"),
        "isolation": _read_json_evidence(paths.audit / "isolation.json"),
        "security": _read_json_evidence(paths.audit / "security.json"),
    }

    return {
        "run": _run_dict(run),
        "project": _project_dict(project),
        "artifacts": artifact_payloads,
        "approvals": approval_payloads,
        "trace": trace,
        "evidence": evidence,
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
        trusted_path = _validate_trusted_path(data_root, expected_path)
        file_stat = os.stat(trusted_path, follow_symlinks=False)
    except (OSError, RuntimeError, ValueError):
        return False, 0
    if not stat.S_ISREG(file_stat.st_mode):
        return False, 0
    return True, file_stat.st_size


def _validate_trusted_path(data_root: Path, expected_path: Path) -> Path:
    root = Path(os.path.abspath(data_root))
    expected = Path(os.path.abspath(expected_path))
    relative = expected.relative_to(root)
    trusted_root = root.resolve(strict=True)
    resolved_expected = expected.resolve(strict=False)
    resolved_expected.relative_to(trusted_root)

    for current in (root, *(root / part for part in _cumulative_parts(relative))):
        try:
            file_stat = os.lstat(current)
        except FileNotFoundError:
            break
        if _is_link_or_reparse(current, file_stat):
            raise ValueError("artifact path contains an untrusted link")
    return expected


def _cumulative_parts(relative: Path):
    current = Path()
    for part in relative.parts:
        current /= part
        yield current


def _is_link_or_reparse(path: Path, file_stat) -> bool:
    if stat.S_ISLNK(file_stat.st_mode) or path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(file_stat, "st_file_attributes", 0) & reparse_flag)


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


def _read_trace(path: Path, max_events: int, max_event_chars: int) -> dict[str, Any]:
    if not path.is_file():
        return {
            "events": [],
            "truncated": False,
            "max_events": max_events,
            "max_event_chars": max_event_chars,
        }

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = lines[-max_events:]
    events = [_parse_trace_line(line, max_event_chars) for line in selected]
    return {
        "events": events,
        "truncated": len(lines) > max_events or any(event.get("truncated") for event in events),
        "max_events": max_events,
        "max_event_chars": max_event_chars,
        "total_events": len(lines),
    }


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
    truncated = _truncate_value(event, max_event_chars)
    if isinstance(truncated, dict):
        truncated["truncated"] = True
        return truncated
    return {"value": truncated, "truncated": True}


def _truncate_value(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "...[truncated]"
    if isinstance(value, list):
        return [_truncate_value(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_value(item, max_chars) for key, item in value.items()}
    return value


def _read_json_evidence(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return redact(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {"error": str(redact(str(exc)))}
