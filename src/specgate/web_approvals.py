from __future__ import annotations

import sqlite3
from pathlib import Path

from specgate.approvals import ApprovalQueue, approval_queue_path
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import project_paths


def list_web_approvals(db_path: Path, user_id: int) -> list[sqlite3.Row]:
    conn = connect_db(db_path)
    try:
        return conn.execute(
            """
            select approvals.*
            from approvals
            join runs on runs.id = approvals.run_id
            where runs.user_id = ?
            order by approvals.created_at desc, approvals.id desc
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def approve_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
) -> sqlite3.Row:
    return _decide_web_approval(db_path, data_root, user_id, web_approval_id, "approved", None)


def deny_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    reason: str,
) -> sqlite3.Row:
    if reason is None or not reason.strip():
        raise ValueError("reason is required")
    return _decide_web_approval(db_path, data_root, user_id, web_approval_id, "denied", reason.strip())


def _decide_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    status: str,
    reason: str | None,
) -> sqlite3.Row:
    row = _load_owned_approval(db_path, user_id, web_approval_id)
    paths = project_paths(data_root, user_id, row["project_id"])
    queue_path = approval_queue_path(paths.workspace)
    decided_at = utc_now().isoformat()

    queue = ApprovalQueue.read(queue_path)
    if status == "approved":
        queue = queue.approve(row["approval_id"], decided_at)
    elif status == "denied":
        queue = queue.deny(row["approval_id"], reason or "", decided_at)
    else:
        raise ValueError("invalid approval decision")
    queue.write(queue_path)

    conn = connect_db(db_path)
    try:
        conn.execute(
            """
            update approvals
            set status = ?, decided_at = ?
            where id = ?
            """,
            (status, decided_at, web_approval_id),
        )
        conn.commit()
        return conn.execute("select * from approvals where id = ?", (web_approval_id,)).fetchone()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_owned_approval(db_path: Path, user_id: int, web_approval_id: int) -> sqlite3.Row:
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            """
            select approvals.*
            from approvals
            join runs on runs.id = approvals.run_id
            where approvals.id = ? and runs.user_id = ?
            """,
            (web_approval_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("approval not found")
        return row
    finally:
        conn.close()
