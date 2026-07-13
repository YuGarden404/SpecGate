from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from specgate.web_projects import ProjectPaths, RunPaths, web_run_paths


def initialize_run_storage(project: ProjectPaths, run_id: int) -> RunPaths:
    run = web_run_paths(project, run_id)
    project.runs.mkdir(parents=True, exist_ok=True)
    if run.root.exists():
        raise FileExistsError(f"run storage already exists: {run.root}")

    temporary_root = Path(tempfile.mkdtemp(prefix=f".{run_id}.tmp-", dir=project.runs))
    try:
        shutil.copytree(project.workspace, temporary_root / "workspace")
        (temporary_root / "audit").mkdir()
        (temporary_root / "approvals").mkdir()
        (temporary_root / "artifacts").mkdir()
        temporary_root.rename(run.root)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
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

    for path in (next_workspace, backup_workspace):
        if path.exists():
            raise FileExistsError(f"workspace promotion path already exists: {path}")

    try:
        shutil.copytree(run.workspace, next_workspace)
        project.workspace.rename(backup_workspace)
        try:
            next_workspace.rename(project.workspace)
        except Exception:
            backup_workspace.rename(project.workspace)
            raise
        shutil.rmtree(backup_workspace)
    except Exception:
        if next_workspace.exists():
            shutil.rmtree(next_workspace, ignore_errors=True)
        raise
