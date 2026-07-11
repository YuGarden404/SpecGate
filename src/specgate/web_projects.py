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


def project_paths(data_root: Path, user_id: int, project_id: int) -> ProjectPaths:
    root = data_root / "users" / str(user_id) / "projects" / str(project_id)
    return ProjectPaths(
        root=root,
        original=root / "original",
        workspace=root / "workspace",
        artifacts=root / "artifacts",
        runs=root / "runs",
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
            (directory / "SPEC.md").write_text(spec, encoding="utf-8")
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
    try:
        archive = zipfile.ZipFile(BytesIO(zip_content))
    except zipfile.BadZipFile as exc:
        raise ValueError("zip_content must be a valid zip archive") from exc

    with archive:
        members = archive.infolist()
        safe_names = [_safe_zip_name(member.filename) for member in members]
        file_names = {
            Path(safe_name).name
            for safe_name, member in zip(safe_names, members)
            if not member.is_dir()
        }
        if SPEC_FILENAMES.isdisjoint(file_names):
            raise ValueError("zip project requires SPEC or TASK_SPEC")
        if CHECKLIST_FILENAMES.isdisjoint(file_names):
            raise ValueError("zip project requires CHECKLIST")

        conn = connect_db(db_path)
        paths = None
        try:
            project_id = _insert_project(conn, user_id, project_name, "zip")
            paths = project_paths(data_root, user_id, project_id)
            _make_project_dirs(paths, include_workspace=False)

            for safe_name, member in zip(safe_names, members):
                target = paths.original / safe_name
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

            shutil.copytree(paths.original, paths.workspace)
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


def package_result_zip(artifact_dir: Path) -> Path:
    source = artifact_dir / "latest-index.html"
    if not source.is_file():
        raise ValueError("latest-index.html is required")

    zip_path = artifact_dir / "result.zip"
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


def _safe_zip_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(name)
    if (
        not normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or any(part in ("", "..") for part in posix_path.parts)
    ):
        raise ValueError("zip archive contains an unsafe path")
    return normalized
