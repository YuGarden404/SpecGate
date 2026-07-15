from __future__ import annotations

import sqlite3
from pathlib import Path

from specgate.approvals import ApprovalStore
from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.web_projects import project_paths, web_run_paths


class ApprovalConsistencyError(ValueError):
    code = "approval_consistency_error"


def list_web_approvals(
    db_path: Path,
    data_root: Path,
    user_id: int,
) -> list[dict]:
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """
            select approvals.*, runs.status as run_status
            from approvals
            join runs on runs.id = approvals.run_id
            where runs.user_id = ?
            order by approvals.created_at desc, approvals.id desc
            """,
            (user_id,),
        ).fetchall()
        approvals: list[dict] = []
        for row in rows:
            paths = project_paths(data_root, user_id, int(row["project_id"]))
            queue_path = web_run_paths(paths, int(row["run_id"])).approval_queue
            queue = ApprovalStore(queue_path).read_existing()
            approvals.append({**dict(row), "queue_revision": queue.revision})
        return approvals
    finally:
        conn.close()


def approve_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    expected_revision: int,
) -> dict:
    return _decide_web_approval(
        db_path,
        data_root,
        user_id,
        web_approval_id,
        "approved",
        None,
        expected_revision,
    )


def deny_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    reason: str,
    expected_revision: int,
) -> dict:
    if reason is None or not reason.strip():
        raise ValueError("reason is required")
    return _decide_web_approval(
        db_path,
        data_root,
        user_id,
        web_approval_id,
        "denied",
        reason.strip(),
        expected_revision,
    )


def _decide_web_approval(
    db_path: Path,
    data_root: Path,
    user_id: int,
    web_approval_id: int,
    status: str,
    reason: str | None,
    expected_revision: int,
) -> dict:
    conn = connect_db(db_path)
    try:
        row = _load_web_approval(conn, user_id, web_approval_id)
        if row["run_status"] != "needs_approval":
            raise ValueError("run is not waiting for approval")
        if row["status"] != "pending":
            raise ValueError("approval is not pending")

        paths = project_paths(data_root, user_id, row["project_id"])
        queue_path = web_run_paths(paths, int(row["run_id"])).approval_queue
        decided_at = utc_now().isoformat()
        updated_queue = ApprovalStore(queue_path).decide(
            row["approval_id"],
            status,
            expected_revision=expected_revision,
            decided_at=decided_at,
            reason=reason,
        )

        try:
            conn.execute("begin immediate")
            cursor = conn.execute(
                """
                update approvals
                set status = ?, decided_at = ?
                where id = ? and status = 'pending'
                """,
                (status, decided_at, web_approval_id),
            )
            if cursor.rowcount != 1:
                raise ApprovalConsistencyError(
                    "approval_consistency_error: queue updated but database row was not updated"
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, ApprovalConsistencyError):
                raise
            raise ApprovalConsistencyError(
                "approval_consistency_error: queue updated but database row was not updated"
            ) from exc

        updated = conn.execute(
            "select * from approvals where id = ?",
            (web_approval_id,),
        ).fetchone()
        return {
            **dict(updated),
            "run_status": row["run_status"],
            "queue_revision": updated_queue.revision,
        }
    finally:
        conn.close()


def _load_web_approval(
    conn: sqlite3.Connection,
    user_id: int,
    web_approval_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        """
        select approvals.*, runs.status as run_status
        from approvals
        join runs on runs.id = approvals.run_id
        join projects on projects.id = runs.project_id
        where approvals.id = ?
          and runs.user_id = ?
          and projects.user_id = ?
          and approvals.project_id = runs.project_id
        """,
        (web_approval_id, user_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("approval not found")
    return row
