from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
from pathlib import Path

from specgate.approvals import ApprovalQueue, GovernanceConfig, approval_queue_path
from specgate.config import ContextConfig, WorkspaceConfig
from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.run_storage import initialize_run_storage, remove_run_storage
from specgate.runner import AgentRunner, RunResult
from specgate.trace import redact
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import ProjectPaths, package_result_zip, project_paths
from specgate.web_settings import get_settings


ACTIVE_RUN_CONFLICT_MESSAGE = "该项目已有进行中的运行 / This project already has an active run"


class ActiveRunConflict(ValueError):
    def __init__(self) -> None:
        super().__init__(ACTIVE_RUN_CONFLICT_MESSAGE)


def create_run(
    db_path: Path,
    project_id: int,
    user_id: int,
    prompt: str,
    *,
    data_root: Path,
) -> sqlite3.Row:
    run_prompt = _require_text(prompt, "prompt")
    run_id, paths, created_at = _reserve_initializing_run(
        db_path,
        data_root,
        project_id,
        user_id,
        run_prompt,
    )
    storage_initialized = False
    try:
        initialize_run_storage(paths, run_id)
        storage_initialized = True
        return _queue_initialized_run(
            db_path,
            run_id,
            project_id,
            user_id,
            run_prompt,
            created_at,
        )
    except Exception as exc:
        _recover_failed_run_creation(
            db_path,
            paths,
            run_id,
            storage_initialized=storage_initialized,
            error=exc,
        )
        raise


def _reserve_initializing_run(
    db_path: Path,
    data_root: Path,
    project_id: int,
    user_id: int,
    run_prompt: str,
) -> tuple[int, ProjectPaths, str]:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if project is None:
            raise ValueError("project not found")

        active_run = conn.execute(
            """
            select id from runs
            where project_id = ? and status in ('initializing', 'queued', 'running', 'needs_approval')
            limit 1
            """,
            (project_id,),
        ).fetchone()
        if active_run is not None:
            raise ActiveRunConflict()

        now = utc_now().isoformat()
        cursor = conn.execute(
            """
            insert into runs (project_id, user_id, status, prompt, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (project_id, user_id, "initializing", run_prompt, now),
        )
        run_id = int(cursor.lastrowid)
        paths = project_paths(data_root, int(project["user_id"]), int(project["id"]))
        conn.commit()
        return run_id, paths, now
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _queue_initialized_run(
    db_path: Path,
    run_id: int,
    project_id: int,
    user_id: int,
    run_prompt: str,
    created_at: str,
) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            "select status from runs where id = ? and project_id = ? and user_id = ?",
            (run_id, project_id, user_id),
        ).fetchone()
        if run is None or run["status"] != "initializing":
            raise RuntimeError("run is no longer initializing")

        conn.execute(
            """
            insert into messages (project_id, user_id, role, content, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (project_id, user_id, "user", run_prompt, created_at),
        )
        cursor = conn.execute(
            "update runs set status = 'queued' where id = ? and status = 'initializing'",
            (run_id,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("run is no longer initializing")
        run = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        conn.commit()
        return run
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _recover_failed_run_creation(
    db_path: Path,
    paths: ProjectPaths,
    run_id: int,
    *,
    storage_initialized: bool,
    error: Exception,
) -> None:
    if storage_initialized:
        try:
            remove_run_storage(paths, run_id)
        except Exception as cleanup_error:
            error.add_note(f"run storage cleanup failed: {cleanup_error}")
            _record_run_creation_failure(db_path, run_id, error, cleanup_error)
            return

    try:
        _delete_initializing_run(db_path, run_id)
    except Exception as cleanup_error:
        error.add_note(f"initializing run cleanup failed: {cleanup_error}")
        _record_run_creation_failure(db_path, run_id, error, cleanup_error)


def _delete_initializing_run(db_path: Path, run_id: int) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("delete from runs where id = ? and status = 'initializing'", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_run_creation_failure(
    db_path: Path,
    run_id: int,
    error: Exception,
    cleanup_error: Exception,
) -> None:
    detail = f"{_safe_error(error)}; cleanup failed: {_safe_error(cleanup_error)}"
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            update runs
            set status = 'failed', error_message = ?, finished_at = ?
            where id = ? and status = 'initializing'
            """,
            (detail, utc_now().isoformat(), run_id),
        )
        conn.commit()
    except Exception as diagnostic_error:
        conn.rollback()
        error.add_note(f"run creation diagnostic update failed: {diagnostic_error}")
    finally:
        conn.close()


def get_run(db_path: Path, user_id: int, run_id: int) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("run not found")
        return row
    finally:
        conn.close()


def start_run_background(db_path: Path, data_root: Path, run_id: int) -> threading.Thread:
    thread = threading.Thread(
        target=execute_run_once,
        args=(db_path, data_root, run_id),
        daemon=True,
    )
    thread.start()
    return thread


def execute_run_once(db_path: Path, data_root: Path, run_id: int) -> None:
    run: sqlite3.Row | None = None
    try:
        run = _load_run(db_path, run_id)
        project = _load_project(db_path, run["project_id"], run["user_id"])
        paths = project_paths(data_root, run["user_id"], project["id"])
        if not _mark_running(db_path, run_id):
            return

        index_before = _index_signature(paths.workspace / "index.html")
        settings = get_settings(db_path, int(run["user_id"]))
        result = _run_mock_agent(paths, settings)
        queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
        index_path: Path | None = None
        zip_path: Path | None = None
        index_after = _index_signature(paths.workspace / "index.html")
        produced_index = index_after is not None and index_after != index_before
        if produced_index:
            index_path, zip_path = _publish_artifacts(paths)

        status = _status_for_result(result, queue, produced_index=produced_index)
        error_message = None if status in {"completed", "needs_approval"} else "Gate did not pass"
        if status == "failed" and not produced_index:
            error_message = "Run did not produce index.html"
        trust_level = _trust_level(result, status)
        _finish_run(
            db_path,
            run_id,
            status=status,
            trust_level=trust_level,
            error_message=error_message,
            index_artifact_path=index_path,
            zip_artifact_path=zip_path,
            queue=queue,
        )
    except Exception as exc:
        if run is not None:
            _mark_failed(db_path, run_id, _safe_error(exc))
            return
        raise


def resume_run_once(db_path: Path, data_root: Path, user_id: int, run_id: int) -> sqlite3.Row | None:
    run = get_run(db_path, user_id, run_id)
    if run["status"] != "needs_approval":
        return None

    project = _load_project(db_path, run["project_id"], user_id)
    paths = project_paths(data_root, user_id, project["id"])
    queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
    if queue.next_resume_candidate() is None:
        raise ValueError("no approved or denied approval to resume")

    running_run: sqlite3.Row | None = None
    try:
        running_run = _mark_resume_running(db_path, user_id, run_id)
        if running_run is None:
            return None

        index_before = _index_signature(paths.workspace / "index.html")
        settings = get_settings(db_path, user_id)
        result = _run_resume_agent(paths, settings)
        queue = ApprovalQueue.read(approval_queue_path(paths.workspace))
        index_path: Path | None = None
        zip_path: Path | None = None
        index_after = _index_signature(paths.workspace / "index.html")
        produced_index = index_after is not None and index_after != index_before
        if produced_index:
            index_path, zip_path = _publish_artifacts(paths)

        status = _status_for_result(result, queue, produced_index=produced_index)
        error_message = None if status in {"completed", "needs_approval"} else "Gate did not pass"
        if status == "failed" and not produced_index:
            error_message = "Run did not produce index.html"
        trust_level = _trust_level(result, status)
        _finish_run(
            db_path,
            run_id,
            status=status,
            trust_level=trust_level,
            error_message=error_message,
            index_artifact_path=index_path,
            zip_artifact_path=zip_path,
            queue=queue,
        )
        return get_run(db_path, user_id, run_id)
    except Exception as exc:
        if running_run is not None:
            _mark_failed(db_path, run_id, _safe_error(exc))
            return get_run(db_path, user_id, run_id)
        raise


def _run_mock_agent(paths: ProjectPaths, settings: dict) -> RunResult:
    governance = GovernanceConfig(profile=settings["governance_profile"])
    policy = WorkspacePolicy(
        root=paths.workspace,
        allowed_actions={"read_file", "list_files", "write_file", "replace_file", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )
    workspace_config = WorkspaceConfig(
        policy=policy,
        governance=governance,
        context=ContextConfig(strategy=settings["context_strategy"]),
    )
    llm = MockLLM(
        [
            {
                "schema_version": "1",
                "action": "write_file",
                "args": {
                    "path": "index.html",
                    "content": _default_result_html(),
                },
            },
            {
                "schema_version": "1",
                "action": "finish",
                "args": {"summary": "SpecGate Result generated"},
            },
        ]
    )
    runner = AgentRunner(
        paths.workspace,
        llm,
        workspace_config.policy,
        max_steps=5,
        context_strategy=workspace_config.context.strategy,
        governance_config=workspace_config.governance,
    )
    return runner.run()


def _run_resume_agent(paths: ProjectPaths, settings: dict) -> RunResult:
    governance = GovernanceConfig(profile=settings["governance_profile"])
    policy = WorkspacePolicy(
        root=paths.workspace,
        allowed_actions={"read_file", "list_files", "write_file", "replace_file", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )
    workspace_config = WorkspaceConfig(
        policy=policy,
        governance=governance,
        context=ContextConfig(strategy=settings["context_strategy"]),
    )
    llm = MockLLM(
        [
            {
                "schema_version": "1",
                "action": "finish",
                "args": {"summary": "SpecGate approval resume completed"},
            }
        ]
    )
    runner = AgentRunner(
        paths.workspace,
        llm,
        workspace_config.policy,
        max_steps=5,
        context_strategy=workspace_config.context.strategy,
        governance_config=workspace_config.governance,
    )
    return runner.resume_from_approval()


def _default_result_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpecGate Result</title>
</head>
<body>
  <main>
    <h1>SpecGate Result</h1>
    <input type="search" aria-label="Filter results" placeholder="Filter">
    <p>This offline HTML page was generated by the SpecGate mock execution pipeline.</p>
  </main>
</body>
</html>
"""


def _load_run(db_path: Path, run_id: int) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("run not found")
        return row
    finally:
        conn.close()


def _load_project(db_path: Path, project_id: int, user_id: int) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("project not found")
        return row
    finally:
        conn.close()


def _mark_running(db_path: Path, run_id: int) -> bool:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            """
            update runs
            set status = ?, started_at = ?, finished_at = null, error_message = null
            where id = ? and status = ?
            """,
            ("running", now, run_id, "queued"),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def _mark_resume_running(db_path: Path, user_id: int, run_id: int) -> sqlite3.Row | None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            """
            update runs
            set status = ?, started_at = ?, finished_at = null, error_message = null
            where id = ? and user_id = ? and status = ?
            """,
            ("running", now, run_id, user_id, "needs_approval"),
        )
        conn.commit()
        if cursor.rowcount == 1:
            return conn.execute("select * from runs where id = ?", (run_id,)).fetchone()

        row = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        if row is None or row["user_id"] != user_id:
            raise ValueError("run not found")
        return None
    finally:
        conn.close()


def _finish_run(
    db_path: Path,
    run_id: int,
    *,
    status: str,
    trust_level: str,
    error_message: str | None,
    index_artifact_path: Path | None,
    zip_artifact_path: Path | None,
    queue: ApprovalQueue,
) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute(
            """
            update runs
            set status = ?,
                trust_level = ?,
                index_artifact_path = ?,
                zip_artifact_path = ?,
                error_message = ?,
                finished_at = ?
            where id = ?
            """,
            (
                status,
                trust_level,
                str(index_artifact_path) if index_artifact_path is not None else None,
                str(zip_artifact_path) if zip_artifact_path is not None else None,
                error_message,
                now,
                run_id,
            ),
        )
        _record_artifacts(conn, run_id, index_artifact_path, zip_artifact_path)
        _sync_approvals(conn, run_id, queue)
        conn.execute(
            """
            update projects
            set last_run_status = ?, updated_at = ?
            where id = (select project_id from runs where id = ?)
            """,
            (status, now, run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _mark_failed(db_path: Path, run_id: int, error_message: str) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute(
            """
            update runs
            set status = ?,
                trust_level = ?,
                index_artifact_path = null,
                zip_artifact_path = null,
                error_message = ?,
                finished_at = ?
            where id = ?
            """,
            ("failed", "failed", error_message, now, run_id),
        )
        conn.execute("delete from artifacts where run_id = ?", (run_id,))
        conn.execute(
            """
            update projects
            set last_run_status = ?, updated_at = ?
            where id = (select project_id from runs where id = ?)
            """,
            ("failed", now, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _publish_artifacts(paths: ProjectPaths) -> tuple[Path, Path]:
    source = paths.workspace / "index.html"
    if not source.is_file():
        raise ValueError("index.html was not produced")
    paths.artifacts.mkdir(parents=True, exist_ok=True)
    index_path = paths.artifacts / "latest-index.html"
    shutil.copy2(source, index_path)
    zip_path = package_result_zip(paths.artifacts)
    return index_path, zip_path


def _index_signature(path: Path) -> tuple[int, int, str] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return stat.st_mtime_ns, stat.st_size, digest


def _record_artifacts(
    conn: sqlite3.Connection,
    run_id: int,
    index_artifact_path: Path | None,
    zip_artifact_path: Path | None,
) -> None:
    conn.execute("delete from artifacts where run_id = ?", (run_id,))
    for kind, path in (("index", index_artifact_path), ("zip", zip_artifact_path)):
        if path is None:
            continue
        conn.execute(
            "insert into artifacts (run_id, kind, path) values (?, ?, ?)",
            (run_id, kind, str(path)),
        )


def _sync_approvals(conn: sqlite3.Connection, run_id: int, queue: ApprovalQueue) -> None:
    run = conn.execute("select project_id from runs where id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("run not found")

    conn.execute("delete from approvals where run_id = ?", (run_id,))
    for approval in queue.approvals:
        conn.execute(
            """
            insert into approvals (
                run_id,
                project_id,
                approval_id,
                status,
                action_name,
                target_path,
                reason,
                preview_json,
                created_at,
                decided_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run["project_id"],
                approval.id,
                approval.status,
                approval.action,
                approval.path,
                approval.reason,
                json.dumps(approval.arguments_preview, ensure_ascii=False),
                approval.created_at or utc_now().isoformat(),
                approval.decided_at,
            ),
        )


def _status_for_result(result: RunResult, queue: ApprovalQueue, *, produced_index: bool) -> str:
    has_pending_approval = any(approval.status == "pending" for approval in queue.approvals)
    if queue.next_resume_candidate() is not None or has_pending_approval:
        return "needs_approval"
    if not produced_index:
        return "failed"
    if result.passed:
        return "completed"
    return "failed"


def _trust_level(result: RunResult, status: str) -> str:
    if result.trust is not None:
        return result.trust.status
    if status == "completed":
        return "trusted"
    if status == "needs_approval":
        return "warning"
    return "failed"


def _safe_error(exc: Exception) -> str:
    text = str(redact(str(exc))) or exc.__class__.__name__
    return text[:300]


def _require_text(value: str, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()
