from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import threading
import zipfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Callable

from specgate.approvals import ApprovalQueue, GovernanceConfig
from specgate.config import ContextConfig, WorkspaceConfig
from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.run_storage import (
    RunInitializationLock,
    RunPublicationLock,
    RunStorageOwnershipError,
    RunStoragePostRenameError,
    RunStorageTargetExists,
    cleanup_interrupted_run_storage,
    initialize_run_storage,
    promote_run_workspace,
    remove_run_storage,
    run_quarantine_capacity_guard,
    validate_run_storage_ownership,
)
from specgate.runner import AgentRunner, RunResult
from specgate.trace import redact
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import ProjectPaths, RunPaths, project_paths, web_run_paths
from specgate.web_runtime import RunCancelled, RunTask, RunTimedOut
from specgate.web_settings import get_runtime_settings
from specgate.workspace_fs import (
    WorkspaceTreeRenameError,
    open_workspace_file,
    publish_workspace_bytes,
    read_workspace_bytes,
    read_workspace_text,
    workspace_file_state,
)


ACTIVE_RUN_CONFLICT_MESSAGE = "该项目已有进行中的运行 / This project already has an active run"
INTERRUPTED_RUN_INITIALIZATION_ERROR = "Interrupted run initialization cleanup failed"
INTERRUPTED_RUN_UNOWNED_STORAGE_ERROR = (
    "Interrupted run initialization cleanup failed: unowned storage retained"
)


class RunLimitExceeded(ValueError):
    code = "run_limit_exceeded"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        messages = {
            "user": "当前用户的活动运行已达上限 / User active run limit reached",
            "project": ACTIVE_RUN_CONFLICT_MESSAGE,
        }
        super().__init__(messages[scope])


class ActiveRunConflict(RunLimitExceeded):
    def __init__(self) -> None:
        super().__init__("project")


class RunCancellationConflict(ValueError):
    code = "run_cancellation_conflict"


def recover_interrupted_run_initializations(db_path: Path, data_root: Path) -> None:
    conn = connect_db(db_path)
    try:
        interrupted_runs = conn.execute(
            """
            select id, project_id, user_id
            from runs
            where status = 'initializing'
            order by id
            """
        ).fetchall()
    finally:
        conn.close()

    for run in interrupted_runs:
        paths = project_paths(data_root, int(run["user_id"]), int(run["project_id"]))
        run_id = int(run["id"])
        initialization_lock = RunInitializationLock(paths, run_id)
        if not initialization_lock.try_acquire():
            continue
        try:
            if not _run_is_still_initializing(db_path, run_id):
                continue
            try:
                cleanup_interrupted_run_storage(paths, run_id)
            except RunStorageOwnershipError:
                _mark_interrupted_initialization_failed(
                    db_path,
                    run_id,
                    INTERRUPTED_RUN_UNOWNED_STORAGE_ERROR,
                )
            except Exception:
                _mark_interrupted_initialization_failed(
                    db_path,
                    run_id,
                    INTERRUPTED_RUN_INITIALIZATION_ERROR,
                )
            else:
                _delete_initializing_run(db_path, run_id)
        finally:
            initialization_lock.release()


def recover_interrupted_run_publications(db_path: Path, data_root: Path) -> None:
    conn = connect_db(db_path)
    try:
        publishing_runs = conn.execute(
            """
            select id, project_id, user_id, index_artifact_path, zip_artifact_path
            from runs
            where status = 'publishing'
            order by id
            """
        ).fetchall()
    finally:
        conn.close()

    for run in publishing_runs:
        run_id = int(run["id"])
        project = project_paths(data_root, int(run["user_id"]), int(run["project_id"]))
        paths = web_run_paths(project, run_id)
        publication_lock = RunPublicationLock(project, run_id)
        if not publication_lock.try_acquire():
            continue
        try:
            locked_run = _load_publishing_run(db_path, run_id)
            if locked_run is None:
                continue
            _validate_publication_storage(db_path, locked_run, project, paths)
            promote_run_workspace(project, run_id)
            _finalize_run_publication(db_path, run_id)
        except Exception as exc:
            try:
                _record_publication_error(db_path, run_id, _safe_error(exc))
            except Exception as diagnostic_error:
                exc.add_note(f"publication recovery diagnostic update failed: {_safe_error(diagnostic_error)}")
        finally:
            publication_lock.release()


def create_run(
    db_path: Path,
    project_id: int,
    user_id: int,
    prompt: str,
    *,
    data_root: Path,
    max_active_runs_per_user: int = 4,
    on_reserved_run: Callable[[int], None] | None = None,
) -> sqlite3.Row:
    run_prompt = _require_text(prompt, "prompt")
    run_id, paths, created_at, initialization_lock, quota_guard = _reserve_initializing_run(
        db_path,
        data_root,
        project_id,
        user_id,
        run_prompt,
        max_active_runs_per_user,
    )
    storage_initialized = False
    try:
        if on_reserved_run is not None:
            on_reserved_run(run_id)
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
    finally:
        try:
            initialization_lock.release()
        finally:
            quota_guard.__exit__(None, None, None)


def _reserve_initializing_run(
    db_path: Path,
    data_root: Path,
    project_id: int,
    user_id: int,
    run_prompt: str,
    max_active_runs_per_user: int,
) -> tuple[
    int,
    ProjectPaths,
    str,
    RunInitializationLock,
    AbstractContextManager[None],
]:
    conn = connect_db(db_path)
    initialization_lock = None
    quota_guard = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        project = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if project is None:
            raise ValueError("project not found")

        active_count = conn.execute(
            """
            select count(*) from runs
            where user_id = ? and status in (
                'initializing', 'queued', 'running', 'needs_approval',
                'cancel_requested', 'publishing'
            )
            """,
            (user_id,),
        ).fetchone()[0]
        if active_count >= max_active_runs_per_user:
            raise RunLimitExceeded("user")

        active_run = conn.execute(
            """
            select id from runs
            where project_id = ? and status in (
                'initializing', 'queued', 'running', 'needs_approval',
                'cancel_requested', 'publishing'
            )
            limit 1
            """,
            (project_id,),
        ).fetchone()
        if active_run is not None:
            raise ActiveRunConflict()

        paths = project_paths(data_root, int(project["user_id"]), int(project["id"]))
        quota_guard = run_quarantine_capacity_guard(paths)
        quota_guard.__enter__()

        now = utc_now().isoformat()
        cursor = conn.execute(
            """
            insert into runs (project_id, user_id, status, prompt, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (project_id, user_id, "initializing", run_prompt, now),
        )
        run_id = int(cursor.lastrowid)
        initialization_lock = RunInitializationLock(paths, run_id)
        initialization_lock.acquire()
        conn.commit()
        return run_id, paths, now, initialization_lock, quota_guard
    except Exception:
        conn.rollback()
        try:
            if initialization_lock is not None:
                initialization_lock.release()
        finally:
            if quota_guard is not None:
                quota_guard.__exit__(None, None, None)
        raise
    finally:
        conn.close()


def _run_is_still_initializing(db_path: Path, run_id: int) -> bool:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute("select status from runs where id = ?", (run_id,)).fetchone()
        conn.commit()
        return run is not None and run["status"] == "initializing"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_publishing_run(db_path: Path, run_id: int) -> sqlite3.Row | None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            """
            select id, project_id, user_id, index_artifact_path, zip_artifact_path
            from runs
            where id = ? and status = 'publishing'
            """,
            (run_id,),
        ).fetchone()
        conn.commit()
        return run
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
    else:
        if not isinstance(error, RunStorageTargetExists):
            try:
                cleanup_interrupted_run_storage(paths, run_id)
            except RunStorageOwnershipError:
                pass
            except Exception as cleanup_error:
                error.add_note(f"run storage cleanup failed: {cleanup_error}")
                _record_initializing_run_creation_failure(db_path, run_id, error, cleanup_error)
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


def _mark_interrupted_initialization_failed(
    db_path: Path,
    run_id: int,
    error_message: str,
) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            update runs
            set status = 'failed', trust_level = 'failed', error_message = ?, finished_at = ?
            where id = ? and status = 'initializing'
            """,
            (error_message, utc_now().isoformat(), run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_initializing_run_creation_failure(
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
            set trust_level = 'failed', error_message = ?
            where id = ? and status = 'initializing'
            """,
            (detail, run_id),
        )
        conn.commit()
    except Exception as diagnostic_error:
        conn.rollback()
        error.add_note(f"run creation diagnostic update failed: {diagnostic_error}")
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


def execute_run_once(
    db_path: Path,
    data_root: Path,
    run_id: int,
    *,
    review_existing_writes: bool = True,
    stop_check: Callable[[], None] | None = None,
    deadline_at: str | None = None,
) -> None:
    checker = stop_check or (lambda: None)
    run: sqlite3.Row | None = None
    publication_prepared = False
    workspace_promoted = False
    publication_lock: RunPublicationLock | None = None
    try:
        run = _load_run(db_path, run_id)
        project = _load_project(db_path, run["project_id"], run["user_id"])
        project_storage = project_paths(data_root, run["user_id"], project["id"])
        paths = web_run_paths(project_storage, run_id)
        if not _mark_running(db_path, run_id, deadline_at=deadline_at):
            return

        checker()
        index_before = _index_signature(paths.workspace / "index.html")
        settings = get_runtime_settings(db_path, int(run["user_id"]))
        settings = {
            **settings,
            "review_existing_writes": review_existing_writes,
            "_stop_check": checker,
        }
        result = _run_mock_agent(paths, settings)
        checker()
        queue = ApprovalQueue.read(paths.approval_queue)
        index_path: Path | None = None
        zip_path: Path | None = None
        index_after = _index_signature(paths.workspace / "index.html")
        produced_index = index_after is not None and index_after != index_before
        stale_gate_result = (
            result.outcome == "completed"
            and produced_index
            and not _gate_artifact_is_current(result, paths)
        )
        if produced_index and not stale_gate_result:
            index_path, zip_path = _publish_artifacts(
                paths,
                _gate_artifact_sha256(result),
            )
            checker()

        status = (
            "failed"
            if stale_gate_result
            else _status_for_result(result, queue, produced_index=produced_index)
        )
        error_message = (
            "stale_gate_result"
            if stale_gate_result
            else None if status in {"completed", "needs_approval"} else "Gate did not pass"
        )
        if status == "failed" and not produced_index and not stale_gate_result:
            error_message = "Run did not produce index.html"
        trust_level = _trust_level(result, status)
        if status == "completed":
            publication_lock = RunPublicationLock(project_storage, run_id)
            publication_lock.acquire()
            _require_current_gate_artifact(result, paths)
            _write_and_validate_publication_manifest(project_storage, paths, run_id)
            _prepare_run_publication(
                db_path,
                run_id,
                trust_level=trust_level,
                index_artifact_path=index_path,
                zip_artifact_path=zip_path,
                queue=queue,
            )
            publication_prepared = True
            promote_run_workspace(project_storage, run_id)
            workspace_promoted = True
            _finalize_run_publication(db_path, run_id)
        else:
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
    except RunCancelled as exc:
        if run is not None:
            _mark_stopped(db_path, run_id, status="cancelled", error_message=str(exc))
            return
        raise
    except RunTimedOut as exc:
        if run is not None:
            _mark_stopped(db_path, run_id, status="timed_out", error_message=str(exc))
            return
        raise
    except Exception as exc:
        if run is not None:
            if publication_prepared and (
                workspace_promoted
                or isinstance(exc, (RunStoragePostRenameError, WorkspaceTreeRenameError))
            ):
                try:
                    _record_publication_error(db_path, run_id, _safe_error(exc))
                except Exception as diagnostic_error:
                    exc.add_note(f"publication diagnostic update failed: {_safe_error(diagnostic_error)}")
                raise
            if _finish_if_stopped(db_path, run_id, checker):
                return
            _mark_failed(db_path, run_id, _safe_error(exc))
            return
        raise
    finally:
        if publication_lock is not None:
            publication_lock.release()


def resume_run_once(
    db_path: Path,
    data_root: Path,
    user_id: int,
    run_id: int,
    *,
    review_existing_writes: bool = True,
    stop_check: Callable[[], None] | None = None,
    deadline_at: str | None = None,
) -> sqlite3.Row | None:
    checker = stop_check or (lambda: None)
    run = get_run(db_path, user_id, run_id)
    if run["status"] not in {"queued", "needs_approval"}:
        return None

    project = _load_project(db_path, run["project_id"], user_id)
    project_storage = project_paths(data_root, user_id, project["id"])
    paths = web_run_paths(project_storage, run_id)
    queue = ApprovalQueue.read(paths.approval_queue)
    if queue.next_resume_candidate() is None:
        if run["status"] == "queued":
            return None
        raise ValueError("no approved or denied approval to resume")

    running_run: sqlite3.Row | None = None
    publication_prepared = False
    workspace_promoted = False
    publication_lock: RunPublicationLock | None = None
    try:
        running_run = _mark_resume_running(
            db_path,
            user_id,
            run_id,
            deadline_at=deadline_at,
        )
        if running_run is None:
            return None

        index_before = _index_signature(paths.workspace / "index.html")
        settings = get_runtime_settings(db_path, user_id)
        settings = {
            **settings,
            "review_existing_writes": review_existing_writes,
            "_stop_check": checker,
        }
        result = _run_resume_agent(paths, settings)
        checker()
        queue = ApprovalQueue.read(paths.approval_queue)
        index_path: Path | None = None
        zip_path: Path | None = None
        index_after = _index_signature(paths.workspace / "index.html")
        gate_artifact_is_current = _gate_artifact_is_current(result, paths)
        produced_index = index_after is not None and (
            index_after != index_before
            or (result.outcome == "completed" and gate_artifact_is_current)
        )
        stale_gate_result = (
            result.outcome == "completed"
            and produced_index
            and not gate_artifact_is_current
        )
        if produced_index and not stale_gate_result:
            index_path, zip_path = _publish_artifacts(
                paths,
                _gate_artifact_sha256(result),
            )
            checker()

        status = (
            "failed"
            if stale_gate_result
            else _status_for_result(result, queue, produced_index=produced_index)
        )
        error_message = (
            "stale_gate_result"
            if stale_gate_result
            else None if status in {"completed", "needs_approval"} else "Gate did not pass"
        )
        if status == "failed" and not produced_index and not stale_gate_result:
            error_message = "Run did not produce index.html"
        trust_level = _trust_level(result, status)
        if status == "completed":
            publication_lock = RunPublicationLock(project_storage, run_id)
            publication_lock.acquire()
            _require_current_gate_artifact(result, paths)
            _write_and_validate_publication_manifest(project_storage, paths, run_id)
            _prepare_run_publication(
                db_path,
                run_id,
                trust_level=trust_level,
                index_artifact_path=index_path,
                zip_artifact_path=zip_path,
                queue=queue,
            )
            publication_prepared = True
            promote_run_workspace(project_storage, run_id)
            workspace_promoted = True
            _finalize_run_publication(db_path, run_id)
        else:
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
    except RunCancelled as exc:
        if running_run is not None:
            _mark_stopped(db_path, run_id, status="cancelled", error_message=str(exc))
            return get_run(db_path, user_id, run_id)
        raise
    except RunTimedOut as exc:
        if running_run is not None:
            _mark_stopped(db_path, run_id, status="timed_out", error_message=str(exc))
            return get_run(db_path, user_id, run_id)
        raise
    except Exception as exc:
        if running_run is not None:
            if publication_prepared and (
                workspace_promoted
                or isinstance(exc, (RunStoragePostRenameError, WorkspaceTreeRenameError))
            ):
                try:
                    _record_publication_error(db_path, run_id, _safe_error(exc))
                except Exception as diagnostic_error:
                    exc.add_note(f"publication diagnostic update failed: {_safe_error(diagnostic_error)}")
                raise
            if _finish_if_stopped(db_path, run_id, checker):
                return get_run(db_path, user_id, run_id)
            _mark_failed(db_path, run_id, _safe_error(exc))
            return get_run(db_path, user_id, run_id)
        raise
    finally:
        if publication_lock is not None:
            publication_lock.release()


def recover_interrupted_runtime_states(db_path: Path) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        interrupted = conn.execute(
            "select id, project_id from runs where status = 'running'"
        ).fetchall()
        cancelled = conn.execute(
            "select id, project_id from runs where status = 'cancel_requested'"
        ).fetchall()
        conn.execute(
            """
            update runs
            set status = 'failed', trust_level = 'failed',
                error_message = '进程重启中断', finished_at = ?,
                index_artifact_path = null, zip_artifact_path = null
            where status = 'running'
            """,
            (now,),
        )
        conn.execute(
            """
            update runs
            set status = 'cancelled', trust_level = 'failed',
                error_message = '运行已取消', finished_at = ?,
                index_artifact_path = null, zip_artifact_path = null
            where status = 'cancel_requested'
            """,
            (now,),
        )
        for row in interrupted:
            conn.execute("delete from artifacts where run_id = ?", (row["id"],))
            conn.execute(
                "update projects set last_run_status = 'failed', updated_at = ? where id = ?",
                (now, row["project_id"]),
            )
        for row in cancelled:
            conn.execute("delete from artifacts where run_id = ?", (row["id"],))
            conn.execute(
                "update projects set last_run_status = 'cancelled', updated_at = ? where id = ?",
                (now, row["project_id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_queued_runs(db_path: Path) -> list[sqlite3.Row]:
    conn = connect_db(db_path)
    try:
        return conn.execute(
            "select * from runs where status = 'queued' order by created_at asc, id asc"
        ).fetchall()
    finally:
        conn.close()


def queued_run_task(data_root: Path, run: sqlite3.Row) -> RunTask:
    project = project_paths(
        data_root,
        int(run["user_id"]),
        int(run["project_id"]),
    )
    paths = web_run_paths(project, int(run["id"]))
    queue = ApprovalQueue.read(paths.approval_queue)
    return RunTask(
        int(run["id"]),
        int(run["user_id"]),
        queue.next_resume_candidate() is not None,
    )


def queue_run_resume(
    db_path: Path,
    data_root: Path,
    user_id: int,
    run_id: int,
) -> sqlite3.Row:
    run = get_run(db_path, user_id, run_id)
    if run["status"] != "needs_approval":
        raise ValueError("run is not waiting for approval")
    project = _load_project(db_path, int(run["project_id"]), user_id)
    paths = web_run_paths(
        project_paths(data_root, user_id, int(project["id"])),
        run_id,
    )
    if ApprovalQueue.read(paths.approval_queue).next_resume_candidate() is None:
        raise ValueError("no approved or denied approval to resume")

    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            update runs
            set status = 'queued', deadline_at = null, finished_at = null
            where id = ? and user_id = ? and status = 'needs_approval'
            """,
            (run_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("run is no longer waiting for approval")
        queued = conn.execute(
            "select * from runs where id = ?",
            (run_id,),
        ).fetchone()
        conn.commit()
        return queued
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _gate_artifact_is_current(result: RunResult, paths: RunPaths) -> bool:
    final_gate = result.final_gate
    if final_gate is None or final_gate.artifact_sha256 is None:
        return False
    state = workspace_file_state(paths.workspace, "index.html")
    return state.exists and state.sha256 == final_gate.artifact_sha256


def _gate_artifact_sha256(result: RunResult) -> str:
    final_gate = result.final_gate
    if final_gate is None or final_gate.artifact_sha256 is None:
        raise ValueError("stale_gate_result")
    return final_gate.artifact_sha256


def _require_current_gate_artifact(result: RunResult, paths: RunPaths) -> None:
    if not _gate_artifact_is_current(result, paths):
        raise ValueError("stale_gate_result")


def _run_mock_agent(paths: RunPaths, settings: dict) -> RunResult:
    governance = GovernanceConfig(
        profile=settings["governance_profile"],
        review_existing_writes=settings.get("review_existing_writes", True),
    )
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
        audit_dir=paths.audit,
        approval_queue_file=paths.approval_queue,
        stop_check=settings.get("_stop_check"),
    )
    return runner.run()


def _run_resume_agent(paths: RunPaths, settings: dict) -> RunResult:
    governance = GovernanceConfig(
        profile=settings["governance_profile"],
        review_existing_writes=settings.get("review_existing_writes", True),
    )
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
        audit_dir=paths.audit,
        approval_queue_file=paths.approval_queue,
        reset_audit=False,
        stop_check=settings.get("_stop_check"),
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


def _mark_running(db_path: Path, run_id: int, *, deadline_at: str | None = None) -> bool:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            """
            update runs
            set status = ?, started_at = ?, finished_at = null, error_message = null,
                deadline_at = ?
            where id = ? and status = ?
            """,
            ("running", now, deadline_at, run_id, "queued"),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def _mark_resume_running(
    db_path: Path,
    user_id: int,
    run_id: int,
    *,
    deadline_at: str | None = None,
) -> sqlite3.Row | None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        cursor = conn.execute(
            """
            update runs
            set status = ?, started_at = ?, finished_at = null, error_message = null,
                deadline_at = ?
            where id = ? and user_id = ? and status in ('queued', 'needs_approval')
            """,
            ("running", now, deadline_at, run_id, user_id),
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


def _prepare_run_publication(
    db_path: Path,
    run_id: int,
    *,
    trust_level: str,
    index_artifact_path: Path,
    zip_artifact_path: Path,
    queue: ApprovalQueue,
) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            update runs
            set status = 'publishing',
                trust_level = ?,
                index_artifact_path = ?,
                zip_artifact_path = ?,
                error_message = null,
                finished_at = null
            where id = ? and status = 'running'
            """,
            (trust_level, str(index_artifact_path), str(zip_artifact_path), run_id),
        )
        if cursor.rowcount != 1:
            current = conn.execute(
                "select status from runs where id = ?",
                (run_id,),
            ).fetchone()
            if current is not None and current["status"] == "cancel_requested":
                raise RunCancelled("运行已取消")
            raise RuntimeError("run is not ready for publication")
        _record_artifacts(conn, run_id, index_artifact_path, zip_artifact_path)
        _sync_approvals(conn, run_id, queue)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finalize_run_publication(db_path: Path, run_id: int) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            update runs
            set status = 'completed', error_message = null, finished_at = ?
            where id = ? and status = 'publishing'
            """,
            (now, run_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("run is not publishing")
        conn.execute(
            """
            update projects
            set last_run_status = 'completed', updated_at = ?
            where id = (select project_id from runs where id = ?)
            """,
            (now, run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_publication_error(db_path: Path, run_id: int, error_message: str) -> None:
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "update runs set error_message = ? where id = ? and status = 'publishing'",
            (error_message, run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validate_publication_storage(
    db_path: Path,
    run: sqlite3.Row,
    project: ProjectPaths,
    paths: RunPaths,
) -> None:
    if not workspace_file_state(paths.workspace, "index.html").exists:
        raise ValueError("workspace index.html is required for publication recovery")
    if run["index_artifact_path"] != str(paths.index_artifact) or not workspace_file_state(
        paths.artifacts,
        "index.html",
    ).exists:
        raise ValueError("index.html artifact is required for publication recovery")
    if run["zip_artifact_path"] != str(paths.zip_artifact) or not workspace_file_state(
        paths.artifacts,
        "result.zip",
    ).exists:
        raise ValueError("result.zip artifact is required for publication recovery")

    _validate_publication_manifest(project, paths, int(run["id"]))

    conn = connect_db(db_path)
    try:
        records = conn.execute(
            "select kind, path from artifacts where run_id = ? order by kind",
            (run["id"],),
        ).fetchall()
    finally:
        conn.close()
    if [(record["kind"], record["path"]) for record in records] != [
        ("index", str(paths.index_artifact)),
        ("zip", str(paths.zip_artifact)),
    ]:
        raise ValueError("artifact records are required for publication recovery")


def _write_and_validate_publication_manifest(
    project: ProjectPaths,
    paths: RunPaths,
    run_id: int,
) -> None:
    ownership = validate_run_storage_ownership(project, run_id)
    zip_index = _read_publication_zip_index(paths.zip_artifact)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "ownership": ownership,
        "workspace_index_sha256": _sha256_file(paths.workspace / "index.html"),
        "index_artifact_sha256": _sha256_file(paths.index_artifact),
        "zip_artifact_sha256": _sha256_file(paths.zip_artifact),
        "zip_index_sha256": hashlib.sha256(zip_index).hexdigest(),
    }
    manifest_path = paths.audit / "publication-manifest.json"
    publish_workspace_bytes(
        paths.audit,
        manifest_path.name,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    )
    _validate_publication_manifest(project, paths, run_id)


def _validate_publication_manifest(project: ProjectPaths, paths: RunPaths, run_id: int) -> None:
    ownership = validate_run_storage_ownership(project, run_id)
    manifest_path = paths.audit / "publication-manifest.json"
    try:
        manifest = json.loads(read_workspace_text(paths.audit, manifest_path.name))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("publication manifest is invalid") from exc
    expected = {
        "schema_version": 1,
        "run_id": run_id,
        "ownership": ownership,
        "workspace_index_sha256": _sha256_file(paths.workspace / "index.html"),
        "index_artifact_sha256": _sha256_file(paths.index_artifact),
        "zip_artifact_sha256": _sha256_file(paths.zip_artifact),
        "zip_index_sha256": hashlib.sha256(_read_publication_zip_index(paths.zip_artifact)).hexdigest(),
    }
    if manifest != expected:
        raise ValueError("publication manifest does not match run storage")
    if expected["workspace_index_sha256"] != expected["index_artifact_sha256"]:
        raise ValueError("workspace and index artifact do not match")
    if expected["index_artifact_sha256"] != expected["zip_index_sha256"]:
        raise ValueError("zip index.html does not match index artifact")


def _sha256_file(path: Path) -> str:
    try:
        content = read_workspace_bytes(path.parent, path.name)
    except ValueError as exc:
        raise ValueError(f"{path.name} is required for publication") from exc
    return hashlib.sha256(content).hexdigest()


def _read_publication_zip_index(path: Path) -> bytes:
    try:
        content = read_workspace_bytes(path.parent, path.name)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.namelist() != ["index.html"]:
                raise ValueError("publication zip must contain only index.html")
            return archive.read("index.html")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("publication zip is invalid") from exc


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


def cancel_run(db_path: Path, user_id: int, run_id: int) -> sqlite3.Row:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        run = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise ValueError("run not found")

        original_status = run["status"]
        if original_status == "queued":
            target_status = "cancelled"
        elif original_status == "running":
            target_status = "cancel_requested"
        elif original_status == "needs_approval":
            target_status = "cancelled"
        elif original_status == "cancel_requested":
            conn.execute(
                """
                update runs
                set cancel_requested_at = coalesce(cancel_requested_at, ?)
                where id = ? and user_id = ? and status = 'cancel_requested'
                """,
                (now, run_id, user_id),
            )
            updated = conn.execute(
                "select * from runs where id = ?",
                (run_id,),
            ).fetchone()
            conn.commit()
            return updated
        else:
            raise RunCancellationConflict("run cannot be cancelled from current status")

        finished_at = now if target_status == "cancelled" else None
        cursor = conn.execute(
            """
            update runs
            set status = ?,
                cancel_requested_at = ?,
                finished_at = ?,
                error_message = ?,
                trust_level = case
                    when ? = 'cancelled' then 'failed'
                    else trust_level
                end,
                index_artifact_path = case
                    when ? = 'cancelled' then null
                    else index_artifact_path
                end,
                zip_artifact_path = case
                    when ? = 'cancelled' then null
                    else zip_artifact_path
                end
            where id = ? and user_id = ? and status = ?
            """,
            (
                target_status,
                now,
                finished_at,
                "运行已取消" if target_status == "cancelled" else None,
                target_status,
                target_status,
                target_status,
                run_id,
                user_id,
                original_status,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("run status changed during cancellation")
        if target_status == "cancelled":
            conn.execute("delete from artifacts where run_id = ?", (run_id,))
            conn.execute(
                """
                update projects
                set last_run_status = 'cancelled', updated_at = ?
                where id = (select project_id from runs where id = ?)
                """,
                (now, run_id),
            )
        updated = conn.execute(
            "select * from runs where id = ?",
            (run_id,),
        ).fetchone()
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cancel_queued_run_for_shutdown(db_path: Path, run_id: int) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            update runs
            set status = 'cancelled', trust_level = 'failed',
                error_message = '运行已取消', finished_at = ?,
                cancel_requested_at = coalesce(cancel_requested_at, ?),
                index_artifact_path = null, zip_artifact_path = null
            where id = ? and status = 'queued'
            """,
            (now, now, run_id),
        )
        if cursor.rowcount == 1:
            conn.execute("delete from artifacts where run_id = ?", (run_id,))
            conn.execute(
                """
                update projects
                set last_run_status = 'cancelled', updated_at = ?
                where id = (select project_id from runs where id = ?)
                """,
                (now, run_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def request_running_cancel_for_shutdown(db_path: Path, run_id: int) -> None:
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            update runs
            set status = 'cancel_requested',
                cancel_requested_at = coalesce(cancel_requested_at, ?)
            where id = ? and status = 'running'
            """,
            (now, run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _mark_stopped(
    db_path: Path,
    run_id: int,
    *,
    status: str,
    error_message: str,
) -> None:
    if status not in {"cancelled", "timed_out"}:
        raise ValueError("invalid stopped run status")
    now = utc_now().isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            update runs
            set status = ?,
                trust_level = 'failed',
                index_artifact_path = null,
                zip_artifact_path = null,
                error_message = ?,
                finished_at = ?,
                cancel_requested_at = case
                    when ? = 'cancelled' then coalesce(cancel_requested_at, ?)
                    else cancel_requested_at
                end
            where id = ? and status in ('running', 'cancel_requested')
            """,
            (status, error_message, now, status, now, run_id),
        )
        if cursor.rowcount == 1:
            conn.execute("delete from artifacts where run_id = ?", (run_id,))
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


def _finish_if_stopped(
    db_path: Path,
    run_id: int,
    checker: Callable[[], None],
) -> bool:
    try:
        checker()
    except RunCancelled as exc:
        _mark_stopped(db_path, run_id, status="cancelled", error_message=str(exc))
        return True
    except RunTimedOut as exc:
        _mark_stopped(db_path, run_id, status="timed_out", error_message=str(exc))
        return True

    current = _load_run(db_path, run_id)
    if current["status"] == "cancel_requested":
        _mark_stopped(
            db_path,
            run_id,
            status="cancelled",
            error_message="运行已取消",
        )
        return True
    return False


def _publish_artifacts(paths: RunPaths, expected_sha256: str) -> tuple[Path, Path]:
    try:
        index_content = read_workspace_bytes(paths.workspace, "index.html")
    except ValueError as exc:
        raise ValueError("index.html was not produced")
    if hashlib.sha256(index_content).hexdigest() != expected_sha256:
        raise ValueError("stale_gate_result")
    index_path = paths.index_artifact
    publish_workspace_bytes(paths.artifacts, index_path.name, index_content)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", index_content)
    zip_path = paths.zip_artifact
    publish_workspace_bytes(paths.artifacts, zip_path.name, archive_buffer.getvalue())
    return index_path, zip_path


def _index_signature(path: Path) -> tuple[int, int, str] | None:
    if not workspace_file_state(path.parent, path.name).exists:
        return None
    with open_workspace_file(path.parent, path.name) as handle:
        file_stat = os.fstat(handle.fileno())
        digest = hashlib.sha256(handle.read()).hexdigest()
    return file_stat.st_mtime_ns, file_stat.st_size, digest


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
