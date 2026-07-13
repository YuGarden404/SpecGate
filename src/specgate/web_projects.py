from __future__ import annotations

import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

from specgate.web_auth import utc_now
from specgate.web_db import connect_db


SPEC_FILENAMES = {"SPEC", "SPEC.md", "TASK_SPEC", "TASK_SPEC.md"}
CHECKLIST_FILENAMES = {"CHECKLIST", "CHECKLIST.md"}


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    original: Path
    workspace: Path
    artifacts: Path
    runs: Path


@dataclass(frozen=True)
class RunPaths:
    root: Path
    workspace: Path
    audit: Path
    approval_queue: Path
    artifacts: Path
    index_artifact: Path
    zip_artifact: Path


def project_paths(data_root: Path, user_id: int, project_id: int) -> ProjectPaths:
    root = data_root / "users" / str(user_id) / "projects" / str(project_id)
    return ProjectPaths(
        root=root,
        original=root / "original",
        workspace=root / "workspace",
        artifacts=root / "artifacts",
        runs=root / "runs",
    )


def web_run_paths(project: ProjectPaths, run_id: int) -> RunPaths:
    root = project.runs / str(run_id)
    artifacts = root / "artifacts"
    return RunPaths(
        root=root,
        workspace=root / "workspace",
        audit=root / "audit",
        approval_queue=root / "approvals" / "pending_approvals.json",
        artifacts=artifacts,
        index_artifact=artifacts / "index.html",
        zip_artifact=artifacts / "result.zip",
    )


def create_manual_project(
    db_path: Path,
    data_root: Path,
    user_id: int,
    *,
    name: str,
    spec_text: str,
    checklist_text: str,
    index_html: str | None,
) -> sqlite3.Row:
    project_name = _require_text(name, "name")
    spec = _require_text(spec_text, "spec_text")
    checklist = _require_text(checklist_text, "checklist_text")

    conn = connect_db(db_path)
    paths = None
    try:
        project_id = _insert_project(conn, user_id, project_name, "manual")
        paths = project_paths(data_root, user_id, project_id)
        _make_project_dirs(paths)

        for directory in (paths.original, paths.workspace):
            (directory / "TASK_SPEC.md").write_text(spec, encoding="utf-8")
            (directory / "CHECKLIST.md").write_text(checklist, encoding="utf-8")
            if index_html is not None:
                (directory / "index.html").write_text(index_html, encoding="utf-8")

        row = _finalize_project(conn, project_id, paths.root)
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        if paths is not None:
            shutil.rmtree(paths.root, ignore_errors=True)
        raise
    finally:
        conn.close()


def create_project_from_zip(
    db_path: Path,
    data_root: Path,
    user_id: int,
    name: str,
    zip_content: bytes,
) -> sqlite3.Row:
    project_name = _require_text(name, "name")
    _reject_raw_backslash_paths(zip_content)
    try:
        archive = zipfile.ZipFile(BytesIO(zip_content))
    except zipfile.BadZipFile as exc:
        raise ValueError("zip_content must be a valid zip archive") from exc

    with archive:
        members = archive.infolist()
        safe_names = [_safe_zip_name(member.filename) for member in members]
        spec_path, checklist_path = _find_required_project_files(safe_names, members)
        if spec_path is None:
            raise ValueError("zip project requires SPEC or TASK_SPEC")
        if checklist_path is None:
            raise ValueError("zip project requires CHECKLIST")

        conn = connect_db(db_path)
        paths = None
        try:
            project_id = _insert_project(conn, user_id, project_name, "zip")
            paths = project_paths(data_root, user_id, project_id)
            _make_project_dirs(paths, include_workspace=False)

            for safe_name, member in zip(safe_names, members):
                target = paths.original / safe_name
                _guard_project_destination(target, paths.original)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

            shutil.copytree(paths.original, paths.workspace)
            _normalize_workspace_inputs(paths.original, paths.workspace, spec_path, checklist_path)
            row = _finalize_project(conn, project_id, paths.root)
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            if paths is not None:
                shutil.rmtree(paths.root, ignore_errors=True)
            raise
        finally:
            conn.close()


def package_result_zip(source: Path, zip_path: Path | None = None) -> Path:
    if zip_path is None:
        artifact_dir = source
        source = artifact_dir / "latest-index.html"
        zip_path = artifact_dir / "result.zip"
    if not source.is_file():
        raise ValueError(f"{source.name} is required")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "index.html")
    return zip_path


def _insert_project(conn: sqlite3.Connection, user_id: int, name: str, create_mode: str) -> int:
    now = utc_now().isoformat()
    cursor = conn.execute(
        """
        insert into projects (user_id, name, create_mode, root_path, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (user_id, name, create_mode, "", now, now),
    )
    return int(cursor.lastrowid)


def _finalize_project(conn: sqlite3.Connection, project_id: int, root_path: Path) -> sqlite3.Row:
    conn.execute(
        "update projects set root_path = ?, updated_at = ? where id = ?",
        (str(root_path), utc_now().isoformat(), project_id),
    )
    return conn.execute("select * from projects where id = ?", (project_id,)).fetchone()


def _make_project_dirs(paths: ProjectPaths, *, include_workspace: bool = True) -> None:
    paths.original.mkdir(parents=True, exist_ok=False)
    if include_workspace:
        paths.workspace.mkdir(parents=True, exist_ok=False)
    paths.artifacts.mkdir(parents=True, exist_ok=False)
    paths.runs.mkdir(parents=True, exist_ok=False)


def _require_text(value: str, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _find_required_project_files(
    safe_names: list[str],
    members: list[zipfile.ZipInfo],
) -> tuple[str | None, str | None]:
    spec_path = None
    checklist_path = None
    for safe_name, member in zip(safe_names, members):
        if member.is_dir():
            continue
        file_name = PurePosixPath(safe_name).name
        if spec_path is None and file_name in SPEC_FILENAMES:
            spec_path = safe_name
        if checklist_path is None and file_name in CHECKLIST_FILENAMES:
            checklist_path = safe_name
    return spec_path, checklist_path


def _normalize_workspace_inputs(
    original: Path,
    workspace: Path,
    spec_path: str,
    checklist_path: str,
) -> None:
    (workspace / "TASK_SPEC.md").write_bytes((original / spec_path).read_bytes())
    (workspace / "CHECKLIST.md").write_bytes((original / checklist_path).read_bytes())


def _guard_project_destination(destination: Path, root: Path) -> None:
    try:
        destination.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("zip archive contains an unsafe path") from exc


def _reject_raw_backslash_paths(zip_content: bytes) -> None:
    eocd = zip_content.rfind(b"PK\x05\x06", max(0, len(zip_content) - 65_557))
    if eocd < 0 or eocd + 22 > len(zip_content):
        return

    central_size = int.from_bytes(zip_content[eocd + 12 : eocd + 16], "little")
    central_offset = int.from_bytes(zip_content[eocd + 16 : eocd + 20], "little")
    cursor = central_offset
    end = central_offset + central_size

    while cursor < end and cursor + 46 <= len(zip_content):
        if zip_content[cursor : cursor + 4] != b"PK\x01\x02":
            return
        filename_length = int.from_bytes(zip_content[cursor + 28 : cursor + 30], "little")
        extra_length = int.from_bytes(zip_content[cursor + 30 : cursor + 32], "little")
        comment_length = int.from_bytes(zip_content[cursor + 32 : cursor + 34], "little")
        filename_start = cursor + 46
        filename_end = filename_start + filename_length
        if b"\\" in zip_content[filename_start:filename_end]:
            raise ValueError("zip archive contains an unsafe path")
        cursor = filename_end + extra_length + comment_length


def _safe_zip_name(name: str) -> str:
    if "\\" in name:
        raise ValueError("zip archive contains an unsafe path")
    normalized = name
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(name)
    if (
        normalized in ("", ".")
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in posix_path.parts)
    ):
        raise ValueError("zip archive contains an unsafe path")
    return normalized
