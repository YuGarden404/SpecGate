from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from specgate.web_approvals import approve_web_approval, deny_web_approval, list_web_approvals
from specgate.web_auth import (
    authenticate_user,
    create_session,
    create_user,
    delete_session,
    get_user_by_session,
)
from specgate.web_db import connect_db, init_db
from specgate.web_debug import build_run_debug
from specgate.web_projects import create_manual_project, create_project_from_zip, project_paths
from specgate.web_runs import create_run, get_run, resume_run_once, start_run_background
from specgate.web_settings import clear_api_key, get_settings, update_settings, upsert_api_key


SESSION_COOKIE_NAME = "specgate_session"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class AuthRequest(BaseModel):
    username: str
    password: str


class ManualProjectRequest(BaseModel):
    name: str
    spec_text: str
    checklist_text: str
    index_html: str | None = None


class MessageRequest(BaseModel):
    content: str
    role: str = "user"


class RunRequest(BaseModel):
    prompt: str


class SettingsRequest(BaseModel):
    governance_profile: str
    context_strategy: str


class ApiKeyRequest(BaseModel):
    api_key: str


class DenyRequest(BaseModel):
    reason: str


def create_app(
    data_root: Path | None = None,
    db_path: Path | None = None,
    secure_cookies: bool | None = None,
) -> FastAPI:
    resolved_data_root = Path(
        data_root
        or os.environ.get("SPECGATE_WEB_DATA")
        or os.environ.get("SPECGATE_WEB_DATA_ROOT")
        or Path.cwd() / "var" / "specgate_web"
    )
    resolved_db_path = Path(
        db_path
        or os.environ.get("SPECGATE_WEB_DB_PATH")
        or resolved_data_root / "web.sqlite3"
    )
    resolved_data_root.mkdir(parents=True, exist_ok=True)
    init_db(resolved_db_path)
    resolved_secure_cookies = (
        os.environ.get("SPECGATE_WEB_SECURE_COOKIES") == "1"
        if secure_cookies is None
        else secure_cookies
    )

    app = FastAPI(title="SpecGate Web")
    app.state.data_root = resolved_data_root
    app.state.db_path = resolved_db_path
    app.state.api_key_encryption_secret = os.environ.get("SPECGATE_WEB_SECRET") or os.environ.get(
        "SPECGATE_WEB_API_KEY_SECRET"
    )

    @app.post("/api/auth/register")
    def register(payload: AuthRequest, response: Response) -> dict[str, Any]:
        try:
            user = create_user(app.state.db_path, payload.username, payload.password)
            token = create_session(app.state.db_path, int(user["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _set_session_cookie(response, token, secure=resolved_secure_cookies)
        return {"user": _user_dict(user)}

    @app.post("/api/auth/login")
    def login(payload: AuthRequest, response: Response) -> dict[str, Any]:
        try:
            user = authenticate_user(app.state.db_path, payload.username, payload.password)
            token = create_session(app.state.db_path, int(user["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        _set_session_cookie(response, token, secure=resolved_secure_cookies)
        return {"user": _user_dict(user)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            delete_session(app.state.db_path, token)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(current_user)) -> dict[str, Any]:
        return {"user": _user_dict(user)}

    @app.get("/api/projects")
    def list_projects(user=Depends(current_user)) -> dict[str, Any]:
        with closing(connect_db(app.state.db_path)) as conn:
            rows = conn.execute(
                """
                select
                  projects.*,
                  (
                    select runs.id from runs
                    where runs.project_id = projects.id and runs.user_id = projects.user_id
                    order by runs.id desc
                    limit 1
                  ) as latest_run_id
                from projects
                where projects.user_id = ?
                order by id desc
                """,
                (user["id"],),
            ).fetchall()
        return {"projects": [_project_dict(row) for row in rows]}

    @app.post("/api/projects")
    def create_project(payload: ManualProjectRequest, user=Depends(current_user)) -> dict[str, Any]:
        try:
            project = create_manual_project(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                name=payload.name,
                spec_text=payload.spec_text,
                checklist_text=payload.checklist_text,
                index_html=payload.index_html,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project": _project_dict(project)}

    @app.post("/api/projects/upload")
    async def upload_project(
        name: str = Form(...),
        file: UploadFile = File(...),
        user=Depends(current_user),
    ) -> dict[str, Any]:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload exceeds 5 MiB limit")
        try:
            project = create_project_from_zip(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                name,
                content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project": _project_dict(project)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, user=Depends(current_user)) -> dict[str, Any]:
        return {"project": _project_dict(_load_project_or_404(app.state.db_path, int(user["id"]), project_id))}

    @app.get("/api/projects/{project_id}/preview")
    def preview_project(project_id: int, user=Depends(current_user)):
        project = _load_project_or_404(app.state.db_path, int(user["id"]), project_id)
        preview = project_paths(app.state.data_root, int(user["id"]), int(project["id"])).workspace / "index.html"
        if not preview.is_file():
            raise HTTPException(status_code=404, detail="preview not found")
        return PlainTextResponse(preview.read_text(encoding="utf-8"))

    @app.get("/api/projects/{project_id}/messages")
    def list_messages(project_id: int, user=Depends(current_user)) -> dict[str, Any]:
        _load_project_or_404(app.state.db_path, int(user["id"]), project_id)
        with closing(connect_db(app.state.db_path)) as conn:
            rows = conn.execute(
                """
                select * from messages
                where project_id = ? and user_id = ?
                order by id asc
                """,
                (project_id, user["id"]),
            ).fetchall()
        return {"messages": [_row_dict(row) for row in rows]}

    @app.post("/api/projects/{project_id}/messages")
    def create_message(
        project_id: int,
        payload: MessageRequest,
        user=Depends(current_user),
    ) -> dict[str, Any]:
        _load_project_or_404(app.state.db_path, int(user["id"]), project_id)
        if payload.role != "user":
            raise HTTPException(status_code=400, detail="role must be user")
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")
        with closing(connect_db(app.state.db_path)) as conn:
            cursor = conn.execute(
                """
                insert into messages (project_id, user_id, role, content)
                values (?, ?, ?, ?)
                """,
                (project_id, user["id"], payload.role, content),
            )
            conn.commit()
            message = conn.execute("select * from messages where id = ?", (cursor.lastrowid,)).fetchone()
        return {"message": _row_dict(message)}

    @app.post("/api/projects/{project_id}/runs")
    def create_project_run(
        project_id: int,
        payload: RunRequest,
        user=Depends(current_user),
    ) -> dict[str, Any]:
        try:
            run = create_run(app.state.db_path, project_id, int(user["id"]), payload.prompt)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        start_run_background(app.state.db_path, app.state.data_root, int(run["id"]))
        return {"run": _run_dict(run)}

    @app.get("/api/runs/{run_id}")
    def read_run(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            run = get_run(app.state.db_path, int(user["id"]), run_id)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"run": _run_dict(run)}

    @app.get("/api/runs/{run_id}/debug")
    def read_run_debug(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            debug = build_run_debug(app.state.db_path, app.state.data_root, int(user["id"]), run_id)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"debug": debug}

    @app.get("/api/runs/{run_id}/artifacts/index")
    def get_index_artifact(run_id: int, user=Depends(current_user)):
        run = _load_run_for_artifact(app.state.db_path, int(user["id"]), run_id)
        return _artifact_response(
            run["index_artifact_path"],
            "text/html",
            headers={
                "Content-Disposition": 'attachment; filename="index.html"',
                "Content-Security-Policy": "sandbox",
            },
        )

    @app.get("/api/runs/{run_id}/artifacts/zip")
    def get_zip_artifact(run_id: int, user=Depends(current_user)):
        run = _load_run_for_artifact(app.state.db_path, int(user["id"]), run_id)
        return _artifact_response(run["zip_artifact_path"], "application/zip")

    @app.get("/api/approvals")
    def list_approvals(user=Depends(current_user)) -> dict[str, Any]:
        approvals = list_web_approvals(app.state.db_path, int(user["id"]))
        return {"approvals": [_approval_dict(row) for row in approvals]}

    @app.post("/api/approvals/{approval_id}/approve")
    def approve(approval_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            approval = approve_web_approval(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                approval_id,
            )
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"approval": _approval_dict(approval)}

    @app.post("/api/approvals/{approval_id}/deny")
    def deny(approval_id: int, payload: DenyRequest, user=Depends(current_user)) -> dict[str, Any]:
        try:
            approval = deny_web_approval(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                approval_id,
                payload.reason,
            )
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"approval": _approval_dict(approval)}

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            run = resume_run_once(app.state.db_path, app.state.data_root, int(user["id"]), run_id)
            if run is None:
                run = get_run(app.state.db_path, int(user["id"]), run_id)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"run": _run_dict(run)}

    @app.get("/api/settings")
    def read_settings(user=Depends(current_user)) -> dict[str, Any]:
        return {"settings": get_settings(app.state.db_path, int(user["id"]))}

    @app.put("/api/settings")
    def put_settings(payload: SettingsRequest, user=Depends(current_user)) -> dict[str, Any]:
        try:
            settings = update_settings(
                app.state.db_path,
                int(user["id"]),
                payload.governance_profile,
                payload.context_strategy,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"settings": settings}

    @app.put("/api/settings/api-key")
    def put_api_key(payload: ApiKeyRequest, user=Depends(current_user)) -> dict[str, Any]:
        try:
            settings = upsert_api_key(
                app.state.db_path,
                int(user["id"]),
                payload.api_key,
                app.state.api_key_encryption_secret,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"settings": settings}

    @app.delete("/api/settings/api-key")
    def delete_api_key(user=Depends(current_user)) -> dict[str, Any]:
        return {"settings": clear_api_key(app.state.db_path, int(user["id"]))}

    static_dir = Path(__file__).with_name("web_static")
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    try:
        return get_user_by_session(request.app.state.db_path, token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="authentication required") from exc


def _set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 7,
    )


def _load_project_or_404(db_path: Path, user_id: int, project_id: int):
    with closing(connect_db(db_path)) as conn:
        row = conn.execute(
            """
            select
              projects.*,
              (
                select runs.id from runs
                where runs.project_id = projects.id and runs.user_id = projects.user_id
                order by runs.id desc
                limit 1
              ) as latest_run_id
            from projects
            where projects.id = ? and projects.user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row


def _load_run_for_artifact(db_path: Path, user_id: int, run_id: int):
    try:
        return get_run(db_path, user_id, run_id)
    except ValueError as exc:
        raise _http_error_for_value_error(exc) from exc


def _artifact_response(path_value: str | None, media_type: str, headers: dict[str, str] | None = None):
    if not path_value:
        raise HTTPException(status_code=404, detail="artifact not found")
    path = Path(path_value)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=media_type, headers=headers)


def _http_error_for_value_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 404 if "not found" in message else 400
    return HTTPException(status_code=status_code, detail=message)


def _row_dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _user_dict(row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "username": data["username"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _project_dict(row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "name": data["name"],
        "create_mode": data["create_mode"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "last_run_status": data["last_run_status"],
        "latest_run_id": data.get("latest_run_id"),
    }


def _run_dict(row) -> dict[str, Any]:
    data = _row_dict(row)
    run = {
        "id": data["id"],
        "status": data["status"],
        "prompt": data["prompt"],
        "trust_level": data["trust_level"],
        "error_message": data["error_message"],
        "created_at": data["created_at"],
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
        "has_index_artifact": bool(data["index_artifact_path"]),
        "has_zip_artifact": bool(data["zip_artifact_path"]),
    }
    if data["index_artifact_path"]:
        run["index_artifact_url"] = f"/api/runs/{data['id']}/artifacts/index"
    if data["zip_artifact_path"]:
        run["zip_artifact_url"] = f"/api/runs/{data['id']}/artifacts/zip"
    return run


def _approval_dict(row) -> dict[str, Any]:
    data = _row_dict(row)
    return {
        "id": data["id"],
        "run_id": data["run_id"],
        "project_id": data["project_id"],
        "approval_id": data["approval_id"],
        "status": data["status"],
        "action_name": data["action_name"],
        "target_path": data["target_path"],
        "reason": data["reason"],
        "preview_json": data["preview_json"],
        "created_at": data["created_at"],
        "decided_at": data["decided_at"],
    }
