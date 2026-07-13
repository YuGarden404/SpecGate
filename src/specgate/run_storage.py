from __future__ import annotations

import json
import shutil
import tempfile
import warnings
from pathlib import Path

from specgate.web_projects import ProjectPaths, RunPaths, web_run_paths


class RunStorageCleanupError(RuntimeError):
    pass


class RunStorageOwnershipError(RunStorageCleanupError):
    pass


class RunStorageTargetExists(FileExistsError):
    pass


_OWNERSHIP_MARKER = ".specgate-run-owner.json"
_OWNERSHIP_SCHEMA_VERSION = 1


def initialize_run_storage(project: ProjectPaths, run_id: int) -> RunPaths:
    run = web_run_paths(project, run_id)
    project.runs.mkdir(parents=True, exist_ok=True)
    if run.root.exists():
        raise RunStorageTargetExists(f"run storage already exists: {run.root}")

    temporary_root = Path(tempfile.mkdtemp(prefix=f".{run_id}.tmp-", dir=project.runs))
    try:
        _write_ownership_marker(temporary_root, run_id)
        shutil.copytree(project.workspace, temporary_root / "workspace")
        (temporary_root / "audit").mkdir()
        (temporary_root / "approvals").mkdir()
        (temporary_root / "artifacts").mkdir()
        temporary_root.rename(run.root)
    except Exception as exc:
        _add_owned_cleanup_failure_note(
            exc,
            temporary_root,
            run_id,
            "run initialization cleanup failed",
        )
        raise
    return run


def remove_run_storage(project: ProjectPaths, run_id: int) -> None:
    run = web_run_paths(project, run_id)
    if _path_exists(run.root):
        _remove_owned_tree(run.root, run_id, "run storage cleanup failed")


def cleanup_interrupted_run_storage(project: ProjectPaths, run_id: int) -> None:
    candidates = sorted(project.runs.glob(f".{run_id}.tmp-*"))
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
        shutil.copytree(run.workspace, next_workspace)
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


def _write_ownership_marker(root: Path, run_id: int) -> None:
    (root / _OWNERSHIP_MARKER).write_text(
        json.dumps(
            {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION},
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _has_matching_ownership_marker(root: Path, run_id: int) -> bool:
    try:
        marker = json.loads((root / _OWNERSHIP_MARKER).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
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
