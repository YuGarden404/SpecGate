from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.concurrency import run_in_threadpool

from specgate.web_approvals import approve_web_approval, deny_web_approval, list_web_approvals
from specgate.web_auth import (
    authenticate_user,
    create_session,
    create_user,
    delete_session,
    get_user_by_session,
)
from specgate.web_db import connect_db, init_db
from specgate.web_credentials import WebCredentialError, WebCredentialService
from specgate.web_debug import build_run_debug
from specgate.web_projects import (
    ArchiveLimitError,
    ArchiveValidationError,
    create_manual_project,
    create_project_from_zip,
    project_paths,
    web_run_paths,
)
from specgate.runtime_config import RuntimeConfigError
from specgate.llm_config import LLMConfigError, LLMRunConfig
from specgate.llm import LLMProviderError
from specgate.llm_transport import LLMNetworkConfig, load_llm_network_config
from specgate.web_llm import (
    LLMConnectionTestLimiter,
    LLMConnectionTestService,
    WebLLMError,
    WebLLMFactory,
)
from specgate.web_runs import (
    ActiveRunConflict,
    RunCancellationConflict,
    RunLimitExceeded,
    cancel_queued_run_for_shutdown,
    cancel_run,
    create_run,
    execute_run_once,
    get_run,
    list_queued_runs,
    queued_run_task,
    queue_run_resume,
    recover_interrupted_run_initializations,
    recover_interrupted_run_publications,
    recover_interrupted_runtime_states,
    request_running_cancel_for_shutdown,
    resume_run_once,
)
from specgate.web_runtime import (
    RunControl,
    RunTask,
    RuntimeCapacityExceeded,
    WebRuntimeConfig,
    WebRuntimeCoordinator,
    load_web_runtime_config,
)
from specgate.web_settings import clear_api_key, get_settings, update_settings, upsert_api_key
from specgate.workspace_fs import WorkspacePathError, read_workspace_bytes, read_workspace_text


SESSION_COOKIE_NAME = "specgate_session"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
RUN_THREAD_SHUTDOWN_TIMEOUT_SECONDS = 5.0
PREVIEW_UNAVAILABLE_MESSAGE = "Project preview is temporarily unavailable"
UPLOAD_PATH_RACE_MESSAGE = "project archive storage changed during upload"
UPLOAD_INTERNAL_ERROR_MESSAGE = "project archive could not be stored safely"
RUN_CREATION_UNAVAILABLE_MESSAGE = "运行创建暂时不可用 / Run creation is temporarily unavailable"


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
    max_steps: StrictInt = Field(ge=1, le=20)
    context_budget_chars: StrictInt = Field(ge=1000, le=100000)
    retrieval_top_k: StrictInt = Field(ge=1, le=20)
    retrieval_budget_chars: StrictInt = Field(ge=500, le=50000)
    compression_max_tool_result_chars: StrictInt = Field(ge=100, le=10000)
    llm_base_url: str | None = None
    llm_model: str | None = None


class ApiKeyRequest(BaseModel):
    api_key: str


class LLMConnectionTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalDecisionRequest(BaseModel):
    expected_revision: StrictInt = Field(ge=0)


class DenyRequest(ApprovalDecisionRequest):
    reason: str


def create_app(
    data_root: Path | None = None,
    db_path: Path | None = None,
    secure_cookies: bool | None = None,
    credential_key: str | None = None,
    runtime_config: WebRuntimeConfig | None = None,
    llm_network_config: LLMNetworkConfig | None = None,
    llm_transport_factory=None,
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
    recover_interrupted_run_initializations(resolved_db_path, resolved_data_root)
    recover_interrupted_runtime_states(resolved_db_path)
    recover_interrupted_run_publications(resolved_db_path, resolved_data_root)
    resolved_secure_cookies = (
        os.environ.get("SPECGATE_WEB_SECURE_COOKIES") == "1"
        if secure_cookies is None
        else secure_cookies
    )
    resolved_runtime_config = runtime_config or load_web_runtime_config()
    resolved_llm_network_config = llm_network_config or load_llm_network_config()
    raw_credential_key = (
        credential_key
        if credential_key is not None
        else os.environ.get("SPECGATE_WEB_CREDENTIAL_KEY")
    )
    web_credentials = WebCredentialService.from_key_value(
        resolved_db_path,
        raw_credential_key,
    )
    web_llm_factory = WebLLMFactory(
        resolved_db_path,
        web_credentials,
        resolved_llm_network_config,
        transport_factory=llm_transport_factory,
    )
    llm_connection_tests = LLMConnectionTestService(
        web_llm_factory,
        LLMConnectionTestLimiter(),
    )

    def execute_runtime_task(task: RunTask, control: RunControl) -> None:
        if task.resume:
            resume_run_once(
                resolved_db_path,
                resolved_data_root,
                task.user_id,
                task.run_id,
                stop_check=control.check,
                deadline_at=control.deadline_at,
                llm_factory=web_llm_factory,
                remaining_seconds=control.remaining_seconds,
            )
        else:
            execute_run_once(
                resolved_db_path,
                resolved_data_root,
                task.run_id,
                stop_check=control.check,
                deadline_at=control.deadline_at,
                llm_factory=web_llm_factory,
                remaining_seconds=control.remaining_seconds,
            )

    runtime = WebRuntimeCoordinator(resolved_runtime_config, execute_runtime_task)

    def refill_provider(scheduled_run_ids: set[int]) -> RunTask | None:
        for row in list_queued_runs(resolved_db_path):
            if int(row["id"]) not in scheduled_run_ids:
                return queued_run_task(resolved_data_root, row)
        return None

    runtime.set_refill_provider(refill_provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime.start()
        app.state.runtime.refill()
        yield
        snapshot = app.state.runtime.begin_shutdown()
        for run_id in snapshot.pending_run_ids:
            cancel_queued_run_for_shutdown(app.state.db_path, run_id)
        for run_id in snapshot.running_run_ids:
            request_running_cancel_for_shutdown(app.state.db_path, run_id)
        app.state.runtime.join(RUN_THREAD_SHUTDOWN_TIMEOUT_SECONDS)
        app.state.web_llm_factory.shutdown()

    app = FastAPI(title="SpecGate Web", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/api/settings":
            errors = exc.errors()
            field = str(errors[0]["loc"][-1]) if errors else "runtime_config"
            return JSONResponse(
                status_code=400,
                content={
                    "detail": {
                        "code": "invalid_runtime_config",
                        "message": "运行配置无效 / Invalid runtime configuration",
                        "field": field,
                    }
                },
            )
        return JSONResponse(
            status_code=400,
            content={
                "detail": {
                    "code": "invalid_request",
                    "message": "请求参数无效 / Invalid request payload",
                    "errors": exc.errors(),
                }
            },
        )
    app.state.data_root = resolved_data_root
    app.state.db_path = resolved_db_path
    app.state.runtime_config = resolved_runtime_config
    app.state.runtime = runtime
    app.state.llm_network_config = resolved_llm_network_config
    app.state.web_credentials = web_credentials
    app.state.web_llm_factory = web_llm_factory
    app.state.llm_connection_tests = llm_connection_tests
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
            project = await run_in_threadpool(
                create_project_from_zip,
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                name,
                content,
            )
        except ArchiveLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ArchiveValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WorkspacePathError as exc:
            if exc.rule_family == "path_race":
                raise HTTPException(status_code=409, detail=UPLOAD_PATH_RACE_MESSAGE) from exc
            raise HTTPException(status_code=500, detail=UPLOAD_INTERNAL_ERROR_MESSAGE) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project": _project_dict(project)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, user=Depends(current_user)) -> dict[str, Any]:
        return {"project": _project_dict(_load_project_or_404(app.state.db_path, int(user["id"]), project_id))}

    @app.get("/api/projects/{project_id}/preview")
    def preview_project(project_id: int, user=Depends(current_user)):
        project = _load_project_or_404(app.state.db_path, int(user["id"]), project_id)
        paths = project_paths(app.state.data_root, int(user["id"]), int(project["id"]))
        with closing(connect_db(app.state.db_path)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                publishing = conn.execute(
                    """
                    select 1 from runs
                    where project_id = ? and user_id = ? and status = 'publishing'
                    limit 1
                    """,
                    (project_id, user["id"]),
                ).fetchone()
                if publishing is not None:
                    raise HTTPException(status_code=409, detail="project publication in progress")
                content = read_workspace_text(paths.workspace, "index.html")
                conn.commit()
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if _is_sqlite_lock_error(exc):
                    raise HTTPException(
                        status_code=503,
                        detail=PREVIEW_UNAVAILABLE_MESSAGE,
                    ) from exc
                raise
            except (OSError, UnicodeError, WorkspacePathError) as exc:
                raise HTTPException(status_code=404, detail="preview not found") from exc
        return PlainTextResponse(content)

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
            reservation = app.state.runtime.reserve()
        except RuntimeCapacityExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail={"code": exc.code, "scope": exc.scope, "message": str(exc)},
            ) from exc
        try:
            run = create_run(
                app.state.db_path,
                project_id,
                int(user["id"]),
                payload.prompt,
                data_root=app.state.data_root,
                max_active_runs_per_user=(
                    app.state.runtime_config.max_active_runs_per_user
                ),
                on_reserved_run=reservation.bind,
                llm_config_resolver=app.state.web_llm_factory.freeze_config,
            )
            app.state.runtime.submit(
                reservation,
                RunTask(int(run["id"]), int(user["id"]), False),
            )
        except (ActiveRunConflict, RunLimitExceeded) as exc:
            reservation.release()
            raise HTTPException(
                status_code=429,
                detail={"code": exc.code, "scope": exc.scope, "message": str(exc)},
            ) from exc
        except WebLLMError as exc:
            reservation.release()
            raise _http_error_for_llm_error(exc) from exc
        except sqlite3.OperationalError as exc:
            reservation.release()
            if _is_sqlite_lock_error(exc):
                raise HTTPException(status_code=503, detail=RUN_CREATION_UNAVAILABLE_MESSAGE) from exc
            raise
        except ValueError as exc:
            reservation.release()
            raise _http_error_for_value_error(exc) from exc
        except Exception:
            reservation.release()
            raise
        return {"run": _run_dict(run)}

    @app.get("/api/runs/{run_id}")
    def read_run(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            run = get_run(app.state.db_path, int(user["id"]), run_id)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"run": _run_dict(run)}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_project_run(
        run_id: int,
        user=Depends(current_user),
    ) -> dict[str, Any]:
        try:
            run = cancel_run(app.state.db_path, int(user["id"]), run_id)
        except RunCancellationConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc

        if run["status"] == "cancelled":
            app.state.runtime.discard_pending(run_id)
        elif run["status"] == "cancel_requested":
            app.state.runtime.signal_cancel(run_id)
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
        paths = web_run_paths(
            project_paths(app.state.data_root, int(user["id"]), int(run["project_id"])),
            run_id,
        )
        return _artifact_response(
            run["index_artifact_path"],
            paths.index_artifact,
            app.state.data_root,
            "text/html",
            headers={
                "Content-Disposition": 'attachment; filename="index.html"',
                "Content-Security-Policy": "sandbox",
            },
        )

    @app.get("/api/runs/{run_id}/artifacts/zip")
    def get_zip_artifact(run_id: int, user=Depends(current_user)):
        run = _load_run_for_artifact(app.state.db_path, int(user["id"]), run_id)
        paths = web_run_paths(
            project_paths(app.state.data_root, int(user["id"]), int(run["project_id"])),
            run_id,
        )
        return _artifact_response(
            run["zip_artifact_path"],
            paths.zip_artifact,
            app.state.data_root,
            "application/zip",
        )

    @app.get("/api/approvals")
    def list_approvals(user=Depends(current_user)) -> dict[str, Any]:
        approvals = list_web_approvals(
            app.state.db_path,
            app.state.data_root,
            int(user["id"]),
        )
        return {"approvals": [_approval_dict(row) for row in approvals]}

    @app.post("/api/approvals/{approval_id}/approve")
    def approve(
        approval_id: int,
        payload: ApprovalDecisionRequest,
        user=Depends(current_user),
    ) -> dict[str, Any]:
        try:
            approval = approve_web_approval(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                approval_id,
                payload.expected_revision,
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
                payload.expected_revision,
            )
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"approval": _approval_dict(approval)}

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            reservation = app.state.runtime.reserve()
        except RuntimeCapacityExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail={"code": exc.code, "scope": exc.scope, "message": str(exc)},
            ) from exc
        try:
            reservation.bind(run_id)
            run = queue_run_resume(
                app.state.db_path,
                app.state.data_root,
                int(user["id"]),
                run_id,
            )
            app.state.runtime.submit(
                reservation,
                RunTask(run_id, int(user["id"]), True),
            )
        except RuntimeConfigError as exc:
            reservation.release()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": (
                        "运行配置快照无效 / "
                        "Invalid runtime configuration snapshot"
                    ),
                    "field": exc.field,
                },
            ) from exc
        except ValueError as exc:
            reservation.release()
            raise _http_error_for_value_error(exc) from exc
        except Exception:
            reservation.release()
            raise
        return {"run": _run_dict(run)}

    @app.get("/api/settings")
    def read_settings(user=Depends(current_user)) -> dict[str, Any]:
        return {
            "settings": get_settings(
                app.state.db_path,
                int(user["id"]),
                app.state.web_credentials,
                app.state.llm_network_config.endpoint_policy,
            )
        }

    @app.put("/api/settings")
    def put_settings(payload: SettingsRequest, user=Depends(current_user)) -> dict[str, Any]:
        try:
            settings = update_settings(
                app.state.db_path,
                int(user["id"]),
                payload.governance_profile,
                payload.context_strategy,
                payload.max_steps,
                payload.context_budget_chars,
                payload.retrieval_top_k,
                payload.retrieval_budget_chars,
                payload.compression_max_tool_result_chars,
                app.state.web_credentials,
                llm_base_url=payload.llm_base_url,
                llm_model=payload.llm_model,
                endpoint_policy=app.state.llm_network_config.endpoint_policy,
            )
        except RuntimeConfigError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                    "field": exc.field,
                },
            ) from exc
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
                app.state.web_credentials,
                app.state.llm_network_config.endpoint_policy,
            )
        except WebCredentialError as exc:
            raise _http_error_for_credential_error(exc) from exc
        return {"settings": settings}

    @app.delete("/api/settings/api-key")
    def delete_api_key(user=Depends(current_user)) -> dict[str, Any]:
        try:
            settings = clear_api_key(
                app.state.db_path,
                int(user["id"]),
                app.state.web_credentials,
                app.state.llm_network_config.endpoint_policy,
            )
        except WebCredentialError as exc:
            raise _http_error_for_credential_error(exc) from exc
        return {"settings": settings}

    @app.post("/api/settings/llm/test")
    def test_llm_connection(
        payload: LLMConnectionTestRequest = LLMConnectionTestRequest(),
        user=Depends(current_user),
    ) -> dict[str, Any]:
        del payload
        try:
            return app.state.llm_connection_tests.test(int(user["id"]))
        except (WebLLMError, LLMProviderError) as exc:
            raise _http_error_for_llm_error(exc) from exc

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


def _artifact_response(
    path_value: str | None,
    expected_path: Path,
    data_root: Path,
    media_type: str,
    headers: dict[str, str] | None = None,
):
    if not path_value or Path(path_value) != expected_path:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        relative = expected_path.relative_to(data_root).as_posix()
        content = read_workspace_bytes(data_root, relative)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    return Response(content=content, media_type=media_type, headers=headers)


def _is_sqlite_lock_error(exc: sqlite3.OperationalError) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    return error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or any(
        marker in str(exc).lower() for marker in ("locked", "busy")
    )


def _http_error_for_value_error(exc: ValueError) -> HTTPException:
    code = getattr(exc, "code", None)
    if code in {"approval_conflict", "approval_consistency_error"}:
        return HTTPException(
            status_code=409,
            detail={"code": code, "message": str(exc)},
        )
    message = str(exc)
    status_code = 404 if "not found" in message else 400
    return HTTPException(status_code=status_code, detail=message)


def _http_error_for_credential_error(
    exc: WebCredentialError,
) -> HTTPException:
    status_by_code = {
        "invalid_credential": 400,
        "credential_requires_reentry": 409,
        "credential_store_unavailable": 503,
        "invalid_credential_key": 503,
        "credential_decryption_failed": 500,
    }
    code = exc.code
    return HTTPException(
        status_code=status_by_code.get(code, 500),
        detail={
            "code": code,
            "message": (
                "安全凭据操作失败 / "
                "Secure credential operation failed"
            ),
        },
    )


def _http_error_for_llm_error(exc) -> HTTPException:
    code = getattr(exc, "code", "llm_provider_unavailable")
    if code in {
        "llm_configuration_required",
        "credential_missing",
        "credential_changed",
        "credential_requires_reentry",
        "credential_unavailable",
    }:
        status_code = 409
    elif code in {"llm_url_invalid", "llm_host_not_allowed"}:
        status_code = 400
    elif code == "llm_test_rate_limited":
        status_code = 429
    elif code == "llm_request_timeout":
        status_code = 504
    else:
        status_code = 502
    messages = {
        "llm_configuration_required": "模型配置未完成 / LLM configuration is incomplete",
        "llm_test_rate_limited": "连接测试过于频繁 / Connection tests are rate limited",
        "llm_authentication_failed": "模型服务认证失败 / LLM authentication failed",
        "llm_request_timeout": "模型服务请求超时 / LLM request timed out",
    }
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": messages.get(
                code,
                "模型服务不可用 / LLM provider is unavailable",
            ),
        },
    )


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
        "cancel_requested_at": data["cancel_requested_at"],
        "deadline_at": data["deadline_at"],
        "has_index_artifact": bool(data["index_artifact_path"]),
        "has_zip_artifact": bool(data["zip_artifact_path"]),
    }
    try:
        llm_config = LLMRunConfig.from_json(data["llm_config_json"])
    except (LLMConfigError, KeyError):
        run["llm_mode"] = "invalid"
        run["llm_model"] = None
    else:
        run["llm_mode"] = llm_config.mode
        run["llm_model"] = llm_config.model
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
        "queue_revision": data["queue_revision"],
    }
