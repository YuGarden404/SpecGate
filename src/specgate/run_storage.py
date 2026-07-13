from __future__ import annotations

import errno
import json
import os
import shutil
import warnings
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from specgate.web_projects import ProjectPaths, RunPaths, web_run_paths
from specgate.workspace_fs import (
    WorkspacePathError,
    copy_workspace_tree,
    publish_workspace_snapshot,
    read_workspace_text,
)


class RunStorageCleanupError(RuntimeError):
    pass


class RunStorageOwnershipError(RunStorageCleanupError):
    pass


class RunStorageTargetExists(FileExistsError):
    pass


class RunInitializationLockError(RuntimeError):
    pass


class RunPublicationLockError(RuntimeError):
    pass


_OWNERSHIP_MARKER = ".specgate-run-owner.json"
_OWNERSHIP_SCHEMA_VERSION = 1


class _RunPhaseLock:
    def __init__(
        self,
        project: ProjectPaths,
        run_id: int,
        phase: str,
        description: str,
        error_type: type[RuntimeError],
    ) -> None:
        self.path = project.runs / f".{run_id}.{phase}.lock"
        self._description = description
        self._error_type = error_type
        self._handle = None

    def acquire(self) -> None:
        if not self.try_acquire():
            raise self._error_type(f"run {self._description} lock is already held: {self.path}")

    def try_acquire(self) -> bool:
        if self._handle is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_handle_nonblocking(handle)
        except OSError as exc:
            handle.close()
            if _is_lock_contention(exc):
                return False
            raise
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            handle.seek(0)
            _unlock_handle(handle)
        finally:
            handle.close()

    def __enter__(self) -> _RunPhaseLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.release()
        return False


class RunInitializationLock(_RunPhaseLock):
    def __init__(self, project: ProjectPaths, run_id: int) -> None:
        super().__init__(project, run_id, "init", "initialization", RunInitializationLockError)


class RunPublicationLock(_RunPhaseLock):
    def __init__(self, project: ProjectPaths, run_id: int) -> None:
        super().__init__(project, run_id, "publish", "publication", RunPublicationLockError)


def initialize_run_storage(project: ProjectPaths, run_id: int) -> RunPaths:
    run = web_run_paths(project, run_id)
    project.runs.mkdir(parents=True, exist_ok=True)
    try:
        publish_workspace_snapshot(
            run.root,
            source_trees=((project.workspace, "workspace"),),
            directories=("audit", "approvals", "artifacts"),
            files=((_OWNERSHIP_MARKER, _ownership_marker_bytes(run_id)),),
        )
    except (FileExistsError, WorkspacePathError) as exc:
        if isinstance(exc, WorkspacePathError) and str(exc) != (
            "workspace snapshot destination already exists"
        ):
            raise
        raise RunStorageTargetExists(f"run storage already exists: {run.root}") from exc
    except Exception as exc:
        _add_owned_cleanup_failure_note(
            exc,
            run.root,
            run_id,
            "run initialization cleanup failed",
        )
        raise
    return run


def remove_run_storage(project: ProjectPaths, run_id: int) -> None:
    run = web_run_paths(project, run_id)
    if _path_exists(run.root):
        _remove_owned_tree(run.root, run_id, "run storage cleanup failed")


def validate_run_storage_ownership(project: ProjectPaths, run_id: int) -> dict[str, int]:
    run = web_run_paths(project, run_id)
    try:
        marker = json.loads(read_workspace_text(run.root, _OWNERSHIP_MARKER))
    except (OSError, UnicodeError, json.JSONDecodeError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("run storage ownership marker is invalid") from exc
    expected = {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION}
    if marker != expected:
        raise RunStorageOwnershipError("run storage ownership marker does not match run")
    return marker


def cleanup_interrupted_run_storage(project: ProjectPaths, run_id: int) -> None:
    candidates = sorted(
        (*project.runs.glob(f".{run_id}.tmp-*"), *project.runs.glob(f".{run_id}.specgate-copy-*"))
    )
    run = web_run_paths(project, run_id)
    if _path_exists(run.root):
        candidates.append(run.root)

    retained_unowned = False
    for path in candidates:
        if not _has_matching_ownership_marker(path, run_id):
            retained_unowned = True
            continue
        _remove_tree_required(path, "interrupted run storage cleanup failed")

    if retained_unowned:
        raise RunStorageOwnershipError("unowned run storage retained")


def promote_run_workspace(project: ProjectPaths, run_id: int) -> None:
    run = web_run_paths(project, run_id)
    next_workspace = project.workspace.with_name(f"workspace.next-{run_id}")
    backup_workspace = project.workspace.with_name(f"workspace.backup-{run_id}")

    if _recover_workspace_promotion(project.workspace, next_workspace, backup_workspace):
        return

    try:
        copy_workspace_tree(run.workspace, next_workspace)
        project.workspace.rename(backup_workspace)
        try:
            next_workspace.rename(project.workspace)
        except Exception:
            backup_workspace.rename(project.workspace)
            raise
        _cleanup_committed_path(backup_workspace)
    except Exception as exc:
        _add_cleanup_failure_note(exc, next_workspace, "workspace promotion cleanup failed")
        raise


def _recover_workspace_promotion(current: Path, next_workspace: Path, backup_workspace: Path) -> bool:
    if backup_workspace.exists():
        if current.exists():
            if _cleanup_committed_path(next_workspace):
                _cleanup_committed_path(backup_workspace)
            return True

        backup_workspace.rename(current)
        if next_workspace.exists():
            _remove_tree_required(next_workspace, "workspace promotion recovery cleanup failed")
        return False

    if next_workspace.exists():
        if not current.exists():
            raise RuntimeError("workspace promotion cannot recover without current or backup workspace")
        _remove_tree_required(next_workspace, "workspace promotion recovery cleanup failed")
    return False


def _cleanup_committed_path(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
    except Exception as exc:
        warnings.warn(
            f"workspace promotion committed; {path.name} cleanup failed: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )
        return False
    return True


def _remove_tree_required(path: Path, context: str) -> None:
    try:
        shutil.rmtree(path)
    except Exception as exc:
        raise RunStorageCleanupError(f"{context}: {exc}") from exc


def _ownership_marker_bytes(run_id: int) -> bytes:
    return json.dumps(
        {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION},
        sort_keys=True,
    ).encode("utf-8")


def _has_matching_ownership_marker(root: Path, run_id: int) -> bool:
    try:
        marker = json.loads(read_workspace_text(root, _OWNERSHIP_MARKER))
    except (OSError, UnicodeError, json.JSONDecodeError, WorkspacePathError):
        return False
    return marker == {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION}


def _remove_owned_tree(path: Path, run_id: int, context: str) -> None:
    if not _has_matching_ownership_marker(path, run_id):
        raise RunStorageOwnershipError("unowned run storage retained")
    _remove_tree_required(path, context)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _add_owned_cleanup_failure_note(
    error: Exception,
    path: Path,
    run_id: int,
    context: str,
) -> None:
    if not _path_exists(path):
        return
    try:
        _remove_owned_tree(path, run_id, context)
    except Exception as cleanup_error:
        error.add_note(f"{context}: {cleanup_error}")


def _add_cleanup_failure_note(error: Exception, path: Path, context: str) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except Exception as cleanup_error:
        error.add_note(f"{context}: {cleanup_error}")


def _lock_handle_nonblocking(handle) -> None:
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle) -> None:
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _is_lock_contention(exc: OSError) -> bool:
    if isinstance(exc, BlockingIOError):
        return True
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
        exc,
        "winerror",
        None,
    ) in {33, 36}
