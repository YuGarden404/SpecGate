from __future__ import annotations

import shutil
import warnings
from pathlib import Path

from specgate.web_projects import ProjectPaths, RunPaths, web_run_paths


class RunStorageCleanupError(RuntimeError):
    pass


def initialize_run_storage(project: ProjectPaths, run_id: int) -> RunPaths:
    run = web_run_paths(project, run_id)
    project.runs.mkdir(parents=True, exist_ok=True)
    if run.root.exists():
        raise FileExistsError(f"run storage already exists: {run.root}")

    temporary_root = project.runs / f".{run_id}.tmp"
    if temporary_root.exists():
        _remove_tree_required(temporary_root, "stale run initialization cleanup failed")
    try:
        temporary_root.mkdir()
        shutil.copytree(project.workspace, temporary_root / "workspace")
        (temporary_root / "audit").mkdir()
        (temporary_root / "approvals").mkdir()
        (temporary_root / "artifacts").mkdir()
        temporary_root.rename(run.root)
    except Exception as exc:
        _add_cleanup_failure_note(exc, temporary_root, "run initialization cleanup failed")
        raise
    return run


def remove_run_storage(project: ProjectPaths, run_id: int) -> None:
    run = web_run_paths(project, run_id)
    if run.root.exists():
        shutil.rmtree(run.root)


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


def _add_cleanup_failure_note(error: Exception, path: Path, context: str) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except Exception as cleanup_error:
        error.add_note(f"{context}: {cleanup_error}")
