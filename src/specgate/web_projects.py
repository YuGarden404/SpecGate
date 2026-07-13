from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
import stat
import tempfile
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

from specgate.web_auth import utc_now
from specgate.web_db import connect_db
from specgate.workspace_fs import (
    WorkspacePathError,
    WorkspaceTreeBinding,
    bind_workspace_tree,
    copy_workspace_tree,
    ensure_quarantine_capacity,
    ensure_workspace_directory,
    make_quarantine_name,
    read_workspace_bytes,
    rename_workspace_tree_noreplace,
    verify_workspace_tree_binding,
    write_workspace_bytes,
    write_workspace_stream,
)


SPEC_FILENAMES = {"SPEC", "SPEC.md", "TASK_SPEC", "TASK_SPEC.md"}
CHECKLIST_FILENAMES = {"CHECKLIST", "CHECKLIST.md"}
MAX_ZIP_FILES = 1_000
MAX_ZIP_DIRECTORIES = 1_000
MAX_ZIP_FILE_BYTES = 10 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
ZIP_READ_CHUNK_BYTES = 64 * 1024
SUPPORTED_ZIP_COMPRESSION = frozenset(
    {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        zipfile.ZIP_BZIP2,
        zipfile.ZIP_LZMA,
    }
)
INVALID_ARCHIVE_MESSAGE = "zip archive is invalid or unsafe"
ARCHIVE_LIMIT_MESSAGE = "zip archive exceeds safety limits"
_UPLOAD_LOCKS_GUARD = threading.Lock()
_UPLOAD_LOCKS: dict[tuple[str, int], threading.Lock] = {}
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class ArchiveValidationError(ValueError):
    pass


class ArchiveLimitError(ArchiveValidationError):
    pass


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


@dataclass(frozen=True)
class _ValidatedArchiveMember:
    info: zipfile.ZipInfo
    path: str


@dataclass(frozen=True)
class _ArchivePlan:
    members: tuple[_ValidatedArchiveMember, ...]
    spec_path: str
    checklist_path: str


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
    _reject_unsafe_raw_names(zip_content)
    try:
        archive = zipfile.ZipFile(BytesIO(zip_content))
    except (zipfile.BadZipFile, UnicodeError, ValueError) as exc:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE) from exc

    with archive:
        plan = _preflight_archive(archive)
        _verify_archive_contents(archive, plan.members)

        conn: sqlite3.Connection | None = None
        paths: ProjectPaths | None = None
        staging_paths: ProjectPaths | None = None
        staging_binding: WorkspaceTreeBinding | None = None
        staging_identity: tuple[int, int] | None = None
        published_identity: tuple[int, int] | None = None
        upload_lock = _upload_lock_for(data_root, user_id)
        upload_lock.acquire()
        try:
            projects_relative = f"users/{user_id}/projects"
            ensure_workspace_directory(data_root, projects_relative)
            projects_root = data_root.joinpath(*projects_relative.split("/"))
            projects_binding = bind_workspace_tree(projects_root)
            if projects_binding is None:
                raise WorkspacePathError("upload projects root is missing", "path_race")
            ensure_quarantine_capacity(projects_binding)
            staging_root = Path(
                tempfile.mkdtemp(
                    prefix=f".specgate-upload-{secrets.token_hex(16)}-",
                    dir=projects_root,
                )
            )
            staging_binding = bind_workspace_tree(staging_root)
            if staging_binding is None:
                raise WorkspacePathError("upload staging root is missing", "path_race")
            staging_identity = staging_binding.identity
            staging_paths = _paths_for_root(staging_root)
            for relative in (
                "original",
                "artifacts",
                "runs",
            ):
                verify_workspace_tree_binding(staging_binding)
                ensure_workspace_directory(staging_root, relative)
                verify_workspace_tree_binding(staging_binding)

            _extract_archive(
                archive,
                plan.members,
                staging_paths.original,
                staging_binding=staging_binding,
            )
            verify_workspace_tree_binding(staging_binding)
            copy_workspace_tree(staging_paths.original, staging_paths.workspace)
            verify_workspace_tree_binding(staging_binding)
            verify_workspace_tree_binding(staging_binding)
            _normalize_workspace_inputs(
                staging_paths.original,
                staging_paths.workspace,
                plan.spec_path,
                plan.checklist_path,
            )
            verify_workspace_tree_binding(staging_binding)

            conn = connect_db(db_path)
            conn.execute("BEGIN IMMEDIATE")
            project_id = _insert_project(conn, user_id, project_name, "zip")
            paths = project_paths(data_root, user_id, project_id)
            published = rename_workspace_tree_noreplace(staging_binding, paths.root)
            published_identity = published.identity
            staging_paths = None
            row = _finalize_project(conn, project_id, paths.root)
            conn.commit()
            return row
        except Exception as project_error:
            if conn is not None:
                conn.rollback()
            cleanup_errors: list[Exception] = []
            cleanup_targets: list[tuple[Path, tuple[int, int] | None]] = []
            if staging_paths is not None:
                cleanup_targets.append((staging_paths.root, staging_identity))
            if paths is not None and published_identity is not None:
                cleanup_targets.append((paths.root, published_identity))
            for cleanup_path, expected_identity in cleanup_targets:
                try:
                    _quarantine_owned_upload_tree(cleanup_path, expected_identity)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                    project_error.add_note(f"upload cleanup failed: {cleanup_error}")
            if cleanup_errors:
                raise project_error from cleanup_errors[0]
            raise
        finally:
            if conn is not None:
                conn.close()
            upload_lock.release()


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


def _paths_for_root(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        original=root / "original",
        workspace=root / "workspace",
        artifacts=root / "artifacts",
        runs=root / "runs",
    )


def _require_text(value: str, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _preflight_archive(archive: zipfile.ZipFile) -> _ArchivePlan:
    validated: list[_ValidatedArchiveMember] = []
    files: set[str] = set()
    directories: set[str] = set()
    normalized_paths: set[str] = set()
    casefold_paths: dict[str, str] = {}
    total_size = 0
    total_compressed = 0

    for info in archive.infolist():
        path = _safe_zip_name(info.orig_filename)
        _validate_member_type(info)
        if info.flag_bits & 0x2041:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
        if info.compress_type not in SUPPORTED_ZIP_COMPRESSION:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
        if info.file_size < 0 or info.compress_size < 0:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
        if info.is_dir() and info.file_size != 0:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)

        logical_path = path[:-1] if info.is_dir() else path
        if logical_path in normalized_paths:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
        normalized_paths.add(logical_path)
        parents = _parent_paths(logical_path)
        for effective_path in (*parents, logical_path):
            casefolded = effective_path.casefold()
            existing_path = casefold_paths.get(casefolded)
            if existing_path is not None and existing_path != effective_path:
                raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
            casefold_paths[casefolded] = effective_path
        directories.update(parents)
        if info.is_dir():
            directories.add(logical_path)
        else:
            files.add(logical_path)
            if info.file_size > MAX_ZIP_FILE_BYTES:
                raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)
            total_size += info.file_size
            total_compressed += info.compress_size
            if _compression_ratio_exceeded(info.file_size, info.compress_size):
                raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)

        if len(files) > MAX_ZIP_FILES or len(directories) > MAX_ZIP_DIRECTORIES:
            raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)
        if total_size > MAX_ZIP_TOTAL_BYTES:
            raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)
        validated.append(_ValidatedArchiveMember(info=info, path=path))

    if total_size and _compression_ratio_exceeded(total_size, total_compressed):
        raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)

    folded_files = {path.casefold() for path in files}
    folded_directories = {path.casefold() for path in directories}
    if folded_files & folded_directories:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)

    spec_path, checklist_path = _find_required_project_files(
        [member.path for member in validated],
        [member.info for member in validated],
    )
    if spec_path is None:
        raise ArchiveValidationError("zip project requires SPEC or TASK_SPEC")
    if checklist_path is None:
        raise ArchiveValidationError("zip project requires CHECKLIST")
    return _ArchivePlan(tuple(validated), spec_path, checklist_path)


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    unix_type = stat.S_IFMT(unix_mode)
    if unix_type:
        expected_type = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if unix_type != expected_type:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)

    dos_directory = bool(info.external_attr & 0x10)
    if dos_directory and not info.is_dir():
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)


def _parent_paths(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    return tuple("/".join(parts[:index]) for index in range(1, len(parts)))


def _compression_ratio_exceeded(size: int, compressed_size: int) -> bool:
    if size == 0:
        return False
    if compressed_size == 0:
        return True
    return size > compressed_size * MAX_ZIP_COMPRESSION_RATIO


def _verify_archive_contents(
    archive: zipfile.ZipFile,
    members: tuple[_ValidatedArchiveMember, ...],
) -> None:
    actual_total = 0
    try:
        for member in members:
            if member.info.is_dir():
                continue
            with archive.open(member.info, "r") as source:
                actual_size = _consume_member(source, member.info.file_size)
            if actual_size != member.info.file_size:
                raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
            actual_total += actual_size
            if actual_total > MAX_ZIP_TOTAL_BYTES:
                raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)
    except ArchiveValidationError:
        raise
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, OSError) as exc:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE) from exc


def _consume_member(source, declared_size: int) -> int:
    actual_size = 0
    while True:
        chunk = source.read(min(ZIP_READ_CHUNK_BYTES, declared_size - actual_size + 1))
        if not chunk:
            return actual_size
        actual_size += len(chunk)
        if actual_size > declared_size:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)


def _extract_archive(
    archive: zipfile.ZipFile,
    members: tuple[_ValidatedArchiveMember, ...],
    destination: Path,
    *,
    staging_binding: WorkspaceTreeBinding | None = None,
) -> None:
    extracted_total = 0
    try:
        for member in members:
            if member.info.is_dir():
                if staging_binding is not None:
                    verify_workspace_tree_binding(staging_binding)
                ensure_workspace_directory(destination, member.path[:-1])
                if staging_binding is not None:
                    verify_workspace_tree_binding(staging_binding)
                continue
            if staging_binding is not None:
                verify_workspace_tree_binding(staging_binding)
            with archive.open(member.info, "r") as source:
                written = write_workspace_stream(
                    destination,
                    member.path,
                    source,
                    max_bytes=member.info.file_size,
                    chunk_size=ZIP_READ_CHUNK_BYTES,
                )
            if staging_binding is not None:
                verify_workspace_tree_binding(staging_binding)
            if written != member.info.file_size:
                raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
            extracted_total += written
            if extracted_total > MAX_ZIP_TOTAL_BYTES:
                raise ArchiveLimitError(ARCHIVE_LIMIT_MESSAGE)
    except (ArchiveValidationError, WorkspacePathError):
        raise
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, OSError) as exc:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE) from exc


def _quarantine_owned_upload_tree(
    path: Path,
    expected_identity: tuple[int, int] | None,
) -> Path | None:
    if expected_identity is None:
        raise WorkspacePathError(
            "upload cleanup identity is unavailable",
            "path_race",
        )
    try:
        binding = bind_workspace_tree(path, missing_ok=True)
        if binding is None:
            return None
        if binding.identity != expected_identity:
            raise WorkspacePathError(
                "upload cleanup root identity changed",
                "path_race",
            )
        parent_binding = bind_workspace_tree(path.parent)
        if parent_binding is None:
            raise WorkspacePathError("upload quarantine parent is missing", "path_race")
        ensure_quarantine_capacity(parent_binding)
        quarantine = path.parent / make_quarantine_name(path.name)
        return rename_workspace_tree_noreplace(binding, quarantine).path
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "upload cleanup could not be quarantined",
            "path_race",
        ) from exc


def _upload_lock_for(data_root: Path, user_id: int) -> threading.Lock:
    key = (os.path.normcase(os.path.abspath(data_root)), user_id)
    with _UPLOAD_LOCKS_GUARD:
        lock = _UPLOAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _UPLOAD_LOCKS[key] = lock
        return lock


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
    write_workspace_bytes(
        workspace,
        "TASK_SPEC.md",
        read_workspace_bytes(original, spec_path),
    )
    write_workspace_bytes(
        workspace,
        "CHECKLIST.md",
        read_workspace_bytes(original, checklist_path),
    )


def _reject_unsafe_raw_names(zip_content: bytes) -> None:
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
        raw_name = zip_content[filename_start:filename_end]
        if b"\\" in raw_name or b"\x00" in raw_name:
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
        cursor = filename_end + extra_length + comment_length


def _safe_zip_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
    if unicodedata.normalize("NFC", name) != name:
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)

    normalized = name[:-1] if name.endswith("/") else name
    if not normalized or normalized.endswith("/"):
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(name)
    if (
        normalized == "."
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or name.startswith("//")
    ):
        raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)

    parts = normalized.split("/")
    for part in parts:
        stem = part.split(".", 1)[0].upper()
        if (
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or ":" in part
            or any(character in '<>"|?*' for character in part)
            or any(ord(character) < 32 for character in part)
            or stem in _WINDOWS_RESERVED_NAMES
        ):
            raise ArchiveValidationError(INVALID_ARCHIVE_MESSAGE)
    return name
