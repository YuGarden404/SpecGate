from __future__ import annotations

import contextlib
import errno
import json
import os
import secrets
import warnings
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from specgate.web_projects import ProjectPaths, RunPaths, web_run_paths
from specgate.workspace_fs import (
    QuarantineQuotaError,
    WorkspaceTreeBinding,
    WorkspacePathError,
    bind_workspace_tree,
    ensure_quarantine_capacity,
    copy_workspace_tree,
    ensure_workspace_directory,
    open_workspace_file,
    publish_workspace_bytes,
    publish_workspace_snapshot,
    quarantine_parent_lock,
    read_optional_workspace_text,
    read_workspace_text,
    rename_workspace_tree_noreplace,
    make_quarantine_name,
    verify_workspace_tree_binding,
)


class RunStorageCleanupError(RuntimeError):
    pass


class RunStorageQuotaError(RunStorageCleanupError):
    pass


class RunStorageOwnershipError(RunStorageCleanupError):
    pass


class RunStoragePostRenameError(RunStorageOwnershipError):
    pass


class RunStorageTargetExists(FileExistsError):
    pass


class RunInitializationLockError(RuntimeError):
    pass


class RunPublicationLockError(RuntimeError):
    pass


_OWNERSHIP_MARKER = ".specgate-run-owner.json"
_OWNERSHIP_SCHEMA_VERSION = 1
_PROMOTION_MARKER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _PromotionPhaseState:
    path: Path
    marker_path: Path
    marker: dict[str, object] | None
    binding: WorkspaceTreeBinding | None


class _RunPhaseLock:
    def __init__(
        self,
        project: ProjectPaths,
        run_id: int,
        phase: str,
        description: str,
        error_type: type[RuntimeError],
    ) -> None:
        self._root = project.root
        self._relative = f"runs/.{run_id}.{phase}.lock"
        self.path = project.runs / f".{run_id}.{phase}.lock"
        self._description = description
        self._error_type = error_type
        self._handle = None
        self._handle_context = None

    def acquire(self) -> None:
        if not self.try_acquire():
            raise self._error_type(f"run {self._description} lock is already held: {self.path}")

    def try_acquire(self) -> bool:
        if self._handle is not None:
            return True

        ensure_workspace_directory(self._root, "runs")
        handle_context = open_workspace_file(
            self._root,
            self._relative,
            "update",
            create=True,
        )
        handle = handle_context.__enter__()
        try:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            handle.seek(0)
            _lock_handle_nonblocking(handle)
        except BaseException as exc:
            handle_context.__exit__(None, None, None)
            if isinstance(exc, OSError) and _is_lock_contention(exc):
                return False
            raise
        self._handle = handle
        self._handle_context = handle_context
        return True

    def release(self) -> None:
        handle = self._handle
        handle_context = self._handle_context
        if handle is None:
            return
        assert handle_context is not None
        self._handle = None
        self._handle_context = None
        try:
            handle.seek(0)
            _unlock_handle(handle)
        finally:
            handle_context.__exit__(None, None, None)

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
    ensure_workspace_directory(project.root, "runs")
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
    runs_binding = _bind_cleanup_parent(project.runs)
    if runs_binding is None:
        return
    _remove_owned_tree(
        run.root,
        run_id,
        "run storage cleanup failed",
        parent_binding=runs_binding,
        missing_ok=True,
    )


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
    runs_binding = _bind_cleanup_parent(project.runs)
    if runs_binding is None:
        return
    try:
        verify_workspace_tree_binding(runs_binding)
        candidates = sorted(
            (
                *project.runs.glob(f".{run_id}.tmp-*"),
                *project.runs.glob(f".{run_id}.specgate-copy-*"),
            )
        )
        verify_workspace_tree_binding(runs_binding)
    except (OSError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("unowned run storage retained") from exc
    candidates.append(web_run_paths(project, run_id).root)

    retained_unowned = False
    for path in candidates:
        try:
            _remove_owned_tree(
                path,
                run_id,
                "interrupted run storage cleanup failed",
                parent_binding=runs_binding,
                missing_ok=True,
            )
        except RunStorageOwnershipError:
            retained_unowned = True

    if retained_unowned:
        raise RunStorageOwnershipError("unowned run storage retained")


def promote_run_workspace(project: ProjectPaths, run_id: int) -> None:
    validate_run_storage_ownership(project, run_id)
    parent_binding = _bind_cleanup_parent(project.root)
    if parent_binding is None:
        raise RunStorageOwnershipError("quarantine parent is missing")
    with quarantine_parent_lock(parent_binding):
        _require_quarantine_capacity(project.root, binding=parent_binding)
        _promote_run_workspace_locked(project, run_id)


def _promote_run_workspace_locked(project: ProjectPaths, run_id: int) -> None:
    run = web_run_paths(project, run_id)
    token = _load_promotion_transaction(project.workspace, run_id)
    if token is None:
        token = secrets.token_hex(32)
        next_workspace, backup_workspace = _promotion_paths(project.workspace, run_id, token)
        next_state = _load_promotion_phase(next_workspace, run_id, "next")
        backup_state = _load_promotion_phase(backup_workspace, run_id, "backup")
        if next_state.marker is not None or backup_state.marker is not None:
            raise RunStorageOwnershipError("unowned workspace promotion marker retained")
        _write_promotion_transaction(project.workspace, run_id, token)
    else:
        next_workspace, backup_workspace = _promotion_paths(project.workspace, run_id, token)

    next_state = _load_promotion_phase(next_workspace, run_id, "next")
    backup_state = _load_promotion_phase(backup_workspace, run_id, "backup")
    if next_state.marker is not None or backup_state.marker is not None:
        _recover_workspace_promotion(
            project.workspace,
            next_state,
            backup_state,
            run_id,
            token,
        )
        return
    if next_state.binding is not None or backup_state.binding is not None:
        raise RunStorageOwnershipError("unowned workspace promotion path retained")

    copy_workspace_tree(run.workspace, next_workspace)
    next_binding = _require_tree_binding(next_workspace, "next workspace")
    _write_promotion_marker(next_workspace, run_id, "next", token, next_binding)
    current_binding = _require_tree_binding(project.workspace, "current workspace")
    _write_promotion_marker(backup_workspace, run_id, "backup", token, current_binding)
    _commit_workspace_promotion(
        current_binding,
        next_binding,
        backup_workspace,
        run_id,
        token,
    )


def _recover_workspace_promotion(
    current: Path,
    next_state: _PromotionPhaseState,
    backup_state: _PromotionPhaseState,
    run_id: int,
    transaction_token: str,
) -> None:
    if next_state.marker is None:
        raise RunStorageOwnershipError("workspace next ownership marker is missing")
    token = _promotion_marker_token(next_state.marker)
    if token != transaction_token:
        raise RunStorageOwnershipError("workspace next transaction token does not match")
    if backup_state.marker is None:
        if backup_state.binding is not None:
            raise RunStorageOwnershipError("workspace backup ownership marker is missing")
        current_binding = _require_tree_binding(current, "current workspace")
        _write_promotion_marker(
            backup_state.path,
            run_id,
            "backup",
            token,
            current_binding,
        )
        backup_state = _load_promotion_phase(backup_state.path, run_id, "backup")

    if _promotion_marker_token(backup_state.marker) != transaction_token:
        raise RunStorageOwnershipError("workspace promotion transaction token does not match")
    next_identity = _promotion_marker_identity(next_state.marker)
    backup_identity = _promotion_marker_identity(backup_state.marker)
    if _promotion_marker_parent_identity(next_state.marker) != (
        _promotion_marker_parent_identity(backup_state.marker)
    ):
        raise RunStorageOwnershipError("workspace promotion parent identity does not match")
    expected_parent_identity = _promotion_marker_parent_identity(next_state.marker)

    current_binding = _optional_tree_binding(current, "current workspace")
    if (
        current_binding is not None
        and current_binding.parent_identity != expected_parent_identity
    ):
        raise RunStorageOwnershipError("current workspace parent identity does not match marker")
    if current_binding is not None and current_binding.identity == next_identity:
        try:
            if next_state.binding is not None and not _quarantine_committed_phase(next_state, token):
                return
            if backup_state.binding is not None:
                _quarantine_committed_phase(backup_state, token)
        except RunStorageQuotaError as exc:
            raise RunStoragePostRenameError(
                "workspace promotion committed; quarantine storage quota exceeded"
            ) from exc
        return

    if current_binding is not None and current_binding.identity == backup_identity:
        if backup_state.binding is not None or next_state.binding is None:
            raise RunStorageOwnershipError("workspace promotion recovery state is uncertain")
        _commit_workspace_promotion(
            current_binding,
            next_state.binding,
            backup_state.path,
            run_id,
            token,
        )
        return

    if current_binding is None:
        if backup_state.binding is None or next_state.binding is None:
            raise RunStorageOwnershipError("workspace promotion recovery paths are incomplete")
        moved_current = rename_workspace_tree_noreplace(next_state.binding, current)
        try:
            _validate_published_workspace(
                moved_current,
                next_state.binding,
                run_id,
                transaction_token,
            )
        except Exception as exc:
            error = RunStoragePostRenameError(str(exc))
            _quarantine_published_workspace(moved_current.path, error)
            raise error from exc
        try:
            _quarantine_committed_phase(backup_state, token)
        except RunStorageQuotaError as exc:
            raise RunStoragePostRenameError(
                "workspace promotion committed; quarantine storage quota exceeded"
            ) from exc
        return

    raise RunStorageOwnershipError("current workspace identity does not match promotion markers")


def _commit_workspace_promotion(
    current_binding: WorkspaceTreeBinding,
    next_binding: WorkspaceTreeBinding,
    backup_workspace: Path,
    run_id: int,
    token: str,
) -> None:
    next_binding = _validate_promotion_commit(
        current_binding,
        next_binding,
        backup_workspace,
        run_id,
        token,
    )
    moved_backup = rename_workspace_tree_noreplace(current_binding, backup_workspace)
    moved_current = None
    try:
        moved_current = rename_workspace_tree_noreplace(next_binding, current_binding.path)
        try:
            _validate_published_workspace(moved_current, next_binding, run_id, token)
        except Exception as exc:
            raise RunStoragePostRenameError(str(exc)) from exc
    except BaseException as publish_error:
        if moved_current is not None:
            _quarantine_published_workspace(moved_current.path, publish_error)
        try:
            rename_workspace_tree_noreplace(moved_backup, current_binding.path)
        except BaseException as rollback_error:
            publish_error.add_note(f"workspace promotion rollback failed: {rollback_error}")
            if isinstance(publish_error, Exception) and isinstance(rollback_error, Exception):
                uncertain = RunStoragePostRenameError(
                    "workspace promotion state is uncertain; "
                    f"publish rename failed: {publish_error}; "
                    f"rollback rename failed: {rollback_error}"
                )
                uncertain.add_note(f"workspace promotion rollback failed: {rollback_error}")
                raise uncertain from publish_error
        else:
            try:
                next_state = _load_promotion_phase(next_binding.path, run_id, "next")
                if _promotion_marker_token(next_state.marker) != token:
                    raise RunStorageOwnershipError(
                        "workspace next cleanup transaction token does not match"
                    )
                if next_state.binding is None:
                    raise RunStorageOwnershipError("workspace next cleanup path is missing")
                quarantine = _promotion_quarantine_path(next_state.path, token)
                _quarantine_bound_tree(next_state.binding, quarantine)
            except BaseException as cleanup_error:
                publish_error.add_note(f"workspace promotion next quarantine failed: {cleanup_error}")
        raise
    backup_state = _load_promotion_phase(backup_workspace, run_id, "backup")
    if backup_state.binding is not None:
        try:
            _quarantine_committed_phase(backup_state, token)
        except RunStorageQuotaError as exc:
            raise RunStoragePostRenameError(
                "workspace promotion committed; quarantine storage quota exceeded"
            ) from exc


def _quarantine_published_workspace(path: Path, error: BaseException) -> None:
    try:
        observed_current = _optional_tree_binding(path, "published workspace")
        if observed_current is not None:
            quarantine = _random_promotion_quarantine_path(path)
            _quarantine_bound_tree(observed_current, quarantine)
    except RunStorageQuotaError as quota_error:
        uncertain = RunStoragePostRenameError(
            "workspace promotion state is uncertain; "
            "published workspace quarantine quota exceeded"
        )
        uncertain.add_note(f"published workspace quarantine failed: {quota_error}")
        raise uncertain from error
    except BaseException as quarantine_error:
        error.add_note(f"published workspace quarantine failed: {quarantine_error}")


def _validate_published_workspace(
    current_binding: WorkspaceTreeBinding,
    next_binding: WorkspaceTreeBinding,
    run_id: int,
    token: str,
) -> None:
    next_state = _load_promotion_phase(next_binding.path, run_id, "next")
    if next_state.binding is not None:
        raise RunStorageOwnershipError("workspace next path reappeared after publication")
    if next_state.marker is None or _promotion_marker_token(next_state.marker) != token:
        raise RunStorageOwnershipError("published workspace transaction token does not match")
    expected_identity = _promotion_marker_identity(next_state.marker)
    expected_parent = _promotion_marker_parent_identity(next_state.marker)
    observed_current = _require_tree_binding(current_binding.path, "published workspace")
    if (
        observed_current.identity != current_binding.identity
        or observed_current.identity != next_binding.identity
        or observed_current.identity != expected_identity
        or observed_current.parent_identity != current_binding.parent_identity
        or observed_current.parent_identity != next_binding.parent_identity
        or observed_current.parent_identity != expected_parent
    ):
        raise RunStorageOwnershipError("published workspace ownership does not match transaction")


def _validate_promotion_commit(
    current_binding: WorkspaceTreeBinding,
    next_binding: WorkspaceTreeBinding,
    backup_workspace: Path,
    run_id: int,
    token: str,
) -> WorkspaceTreeBinding:
    next_state = _load_promotion_phase(next_binding.path, run_id, "next")
    backup_state = _load_promotion_phase(backup_workspace, run_id, "backup")
    if next_state.binding is None or backup_state.marker is None:
        raise RunStorageOwnershipError("workspace promotion commit ownership is incomplete")
    if backup_state.binding is not None:
        raise RunStorageOwnershipError("workspace promotion backup destination already exists")
    if (
        _promotion_marker_token(next_state.marker) != token
        or _promotion_marker_token(backup_state.marker) != token
    ):
        raise RunStorageOwnershipError("workspace promotion commit token does not match")
    if (
        next_state.binding.identity != next_binding.identity
        or _promotion_marker_identity(backup_state.marker) != current_binding.identity
    ):
        raise RunStorageOwnershipError("workspace promotion commit directory identity does not match")
    expected_parent = current_binding.parent_identity
    if (
        next_state.binding.parent_identity != expected_parent
        or _promotion_marker_parent_identity(next_state.marker) != expected_parent
        or _promotion_marker_parent_identity(backup_state.marker) != expected_parent
    ):
        raise RunStorageOwnershipError("workspace promotion commit parent identity does not match")
    return next_state.binding


def _quarantine_committed_phase(state: _PromotionPhaseState, token: str) -> bool:
    try:
        if state.marker is None:
            raise RunStorageOwnershipError("workspace promotion cleanup marker is missing")
        marker_run_id = state.marker.get("run_id")
        marker_phase = state.marker.get("phase")
        if not isinstance(marker_run_id, int) or not isinstance(marker_phase, str):
            raise RunStorageOwnershipError("workspace promotion cleanup marker is invalid")
        original_identity = _promotion_marker_identity(state.marker)
        original_parent_identity = _promotion_marker_parent_identity(state.marker)
        fresh_state = _load_promotion_phase(state.path, marker_run_id, marker_phase)
        if _promotion_marker_token(fresh_state.marker) != token:
            raise RunStorageOwnershipError(
                "workspace promotion cleanup transaction token does not match"
            )
        if (
            _promotion_marker_identity(fresh_state.marker) != original_identity
            or _promotion_marker_parent_identity(fresh_state.marker)
            != original_parent_identity
        ):
            raise RunStorageOwnershipError(
                "workspace promotion cleanup marker ownership changed before quarantine"
            )
        if fresh_state.binding is None:
            return True
        if state.binding is None:
            raise RunStorageOwnershipError("workspace promotion cleanup path unexpectedly appeared")
        if (
            fresh_state.binding.identity != state.binding.identity
            or fresh_state.binding.parent_identity != state.binding.parent_identity
            or fresh_state.binding.identity != original_identity
            or fresh_state.binding.parent_identity != original_parent_identity
        ):
            raise RunStorageOwnershipError(
                "workspace promotion cleanup ownership changed before quarantine"
            )
        quarantine = _promotion_quarantine_path(fresh_state.path, token)
        _quarantine_bound_tree(fresh_state.binding, quarantine)
    except RunStorageQuotaError:
        raise
    except Exception as exc:
        warnings.warn(
            f"workspace promotion committed; {state.path.name} quarantine failed: {exc}",
            RuntimeWarning,
            stacklevel=3,
        )
        return False
    return True


def _promotion_marker_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.specgate-owner.json")


def _promotion_transaction_path(current: Path, run_id: int) -> Path:
    return current.with_name(f".workspace.promotion-{run_id}.json")


def _promotion_paths(current: Path, run_id: int, token: str) -> tuple[Path, Path]:
    return (
        current.with_name(f"workspace.next-{run_id}-{token}"),
        current.with_name(f"workspace.backup-{run_id}-{token}"),
    )


def _load_promotion_transaction(current: Path, run_id: int) -> str | None:
    path = _promotion_transaction_path(current, run_id)
    try:
        raw_marker = read_optional_workspace_text(path.parent, path.name)
    except (OSError, UnicodeError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("workspace promotion transaction is unsafe") from exc
    if raw_marker is None:
        return None
    try:
        marker = json.loads(raw_marker)
    except json.JSONDecodeError as exc:
        raise RunStorageOwnershipError("workspace promotion transaction is invalid") from exc
    if not isinstance(marker, dict) or set(marker) != {
        "schema_version",
        "run_id",
        "transaction_token",
    }:
        raise RunStorageOwnershipError("workspace promotion transaction is invalid")
    token = marker.get("transaction_token")
    if (
        marker.get("schema_version") != _PROMOTION_MARKER_SCHEMA_VERSION
        or marker.get("run_id") != run_id
        or not isinstance(token, str)
        or len(token) != 64
        or any(character not in "0123456789abcdef" for character in token)
    ):
        raise RunStorageOwnershipError("workspace promotion transaction does not match run")
    return token


def _write_promotion_transaction(current: Path, run_id: int, token: str) -> None:
    path = _promotion_transaction_path(current, run_id)
    marker = {
        "schema_version": _PROMOTION_MARKER_SCHEMA_VERSION,
        "run_id": run_id,
        "transaction_token": token,
    }
    try:
        publish_workspace_bytes(
            path.parent,
            path.name,
            json.dumps(marker, sort_keys=True).encode("utf-8"),
        )
    except WorkspacePathError as exc:
        raise RunStorageOwnershipError("workspace promotion transaction could not be published") from exc


def _promotion_quarantine_path(path: Path, token: str) -> Path:
    return path.with_name(make_quarantine_name(path.name, token=token))


def _random_promotion_quarantine_path(path: Path) -> Path:
    return path.with_name(make_quarantine_name(path.name))


def _write_promotion_marker(
    path: Path,
    run_id: int,
    phase: str,
    token: str,
    binding: WorkspaceTreeBinding,
) -> None:
    marker = {
        "schema_version": _PROMOTION_MARKER_SCHEMA_VERSION,
        "run_id": run_id,
        "phase": phase,
        "transaction_token": token,
        "directory_identity": list(binding.identity),
        "parent_identity": list(binding.parent_identity),
    }
    marker_path = _promotion_marker_path(path)
    try:
        publish_workspace_bytes(
            marker_path.parent,
            marker_path.name,
            json.dumps(marker, sort_keys=True).encode("utf-8"),
        )
    except WorkspacePathError as exc:
        raise RunStorageOwnershipError("workspace promotion marker could not be published") from exc


def _load_promotion_phase(path: Path, run_id: int, phase: str) -> _PromotionPhaseState:
    marker_path = _promotion_marker_path(path)
    try:
        raw_marker = read_optional_workspace_text(marker_path.parent, marker_path.name)
    except (OSError, UnicodeError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("workspace promotion marker is unsafe") from exc
    marker = None
    if raw_marker is not None:
        try:
            marker = json.loads(raw_marker)
        except json.JSONDecodeError as exc:
            raise RunStorageOwnershipError("workspace promotion marker is invalid") from exc
        _validate_promotion_marker(marker, run_id, phase)

    binding = _optional_tree_binding(path, f"{phase} workspace")
    if binding is not None:
        if marker is None:
            raise RunStorageOwnershipError(f"workspace {phase} ownership marker is missing")
        if binding.identity != _promotion_marker_identity(marker) or binding.parent_identity != (
            _promotion_marker_parent_identity(marker)
        ):
            raise RunStorageOwnershipError(f"workspace {phase} ownership identity does not match")
    return _PromotionPhaseState(path, marker_path, marker, binding)


def _validate_promotion_marker(marker: object, run_id: int, phase: str) -> None:
    if not isinstance(marker, dict):
        raise RunStorageOwnershipError("workspace promotion marker is invalid")
    required = {
        "schema_version",
        "run_id",
        "phase",
        "transaction_token",
        "directory_identity",
        "parent_identity",
    }
    if set(marker) != required or (
        marker.get("schema_version") != _PROMOTION_MARKER_SCHEMA_VERSION
        or marker.get("run_id") != run_id
        or marker.get("phase") != phase
        or not isinstance(marker.get("transaction_token"), str)
        or not marker.get("transaction_token")
    ):
        raise RunStorageOwnershipError("workspace promotion marker does not match run phase")
    _promotion_marker_identity(marker)
    _promotion_marker_parent_identity(marker)


def _promotion_marker_identity(marker: dict[str, object]) -> tuple[int, int]:
    return _marker_identity(marker.get("directory_identity"), "directory")


def _promotion_marker_parent_identity(marker: dict[str, object]) -> tuple[int, int]:
    return _marker_identity(marker.get("parent_identity"), "parent")


def _marker_identity(value: object, description: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, int) for item in value)
    ):
        raise RunStorageOwnershipError(f"workspace promotion {description} identity is invalid")
    return value[0], value[1]


def _promotion_marker_token(marker: dict[str, object] | None) -> str:
    if marker is None or not isinstance(marker.get("transaction_token"), str):
        raise RunStorageOwnershipError("workspace promotion transaction token is invalid")
    return marker["transaction_token"]


def _optional_tree_binding(path: Path, description: str) -> WorkspaceTreeBinding | None:
    try:
        return bind_workspace_tree(path, missing_ok=True)
    except (OSError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError(f"{description} is unsafe") from exc


def _require_tree_binding(path: Path, description: str) -> WorkspaceTreeBinding:
    binding = _optional_tree_binding(path, description)
    if binding is None:
        raise RunStorageOwnershipError(f"{description} is missing")
    return binding


def _bind_cleanup_parent(path: Path) -> WorkspaceTreeBinding | None:
    try:
        return bind_workspace_tree(path, missing_ok=True)
    except (OSError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("unowned run storage retained") from exc


def _ownership_marker_bytes(run_id: int) -> bytes:
    return json.dumps(
        {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION},
        sort_keys=True,
    ).encode("utf-8")


def _remove_owned_tree(
    path: Path,
    run_id: int,
    context: str,
    *,
    parent_binding: WorkspaceTreeBinding | None = None,
    missing_ok: bool = False,
) -> bool:
    if parent_binding is None:
        parent_binding = _bind_cleanup_parent(path.parent)
        if parent_binding is None:
            if missing_ok:
                return False
            raise RunStorageOwnershipError("unowned run storage retained")
    try:
        binding = bind_workspace_tree(path, missing_ok=missing_ok)
        if binding is None:
            return False
        if (
            binding.parent_identity != parent_binding.identity
            or os.path.normcase(os.path.normpath(binding.trusted_parent))
            != os.path.normcase(os.path.normpath(parent_binding.trusted_path))
        ):
            raise RunStorageOwnershipError("unowned run storage retained")
        marker = json.loads(read_workspace_text(binding.path, _OWNERSHIP_MARKER))
        expected = {"run_id": run_id, "schema_version": _OWNERSHIP_SCHEMA_VERSION}
        if marker != expected:
            raise RunStorageOwnershipError("unowned run storage retained")
        verify_workspace_tree_binding(binding)
    except RunStorageOwnershipError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, WorkspacePathError) as exc:
        raise RunStorageOwnershipError("unowned run storage retained") from exc

    quarantine = path.with_name(make_quarantine_name(path.name))
    try:
        _quarantine_bound_tree(
            binding,
            quarantine,
            parent_binding=parent_binding,
        )
    except RunStorageQuotaError:
        raise
    except Exception as exc:
        raise RunStorageCleanupError(f"{context}: {exc}") from exc
    return True


def ensure_run_quarantine_capacity(project: ProjectPaths) -> None:
    with run_quarantine_capacity_guard(project):
        return


@contextlib.contextmanager
def run_quarantine_capacity_guard(project: ProjectPaths):
    with contextlib.ExitStack() as locks:
        for parent in (project.root, project.runs):
            parent_binding = _bind_cleanup_parent(parent)
            if parent_binding is None:
                raise RunStorageOwnershipError("quarantine parent is missing")
            locks.enter_context(quarantine_parent_lock(parent_binding))
            _require_quarantine_capacity(parent, binding=parent_binding)
        yield


def _quarantine_bound_tree(
    binding: WorkspaceTreeBinding,
    destination: Path,
    *,
    parent_binding: WorkspaceTreeBinding | None = None,
) -> WorkspaceTreeBinding:
    locked_parent = parent_binding
    if locked_parent is None:
        locked_parent = _bind_cleanup_parent(binding.parent_path)
    if locked_parent is None:
        raise RunStorageOwnershipError("quarantine parent is missing")
    with quarantine_parent_lock(locked_parent):
        _require_quarantine_capacity(binding.parent_path, binding=locked_parent)
        return rename_workspace_tree_noreplace(binding, destination)


def _require_quarantine_capacity(
    parent: Path,
    *,
    binding: WorkspaceTreeBinding | None = None,
) -> None:
    parent_binding = binding if binding is not None else _bind_cleanup_parent(parent)
    if parent_binding is None:
        raise RunStorageOwnershipError("quarantine parent is missing")
    try:
        ensure_quarantine_capacity(parent_binding)
    except QuarantineQuotaError as exc:
        raise RunStorageQuotaError(str(exc)) from exc


def _add_owned_cleanup_failure_note(
    error: Exception,
    path: Path,
    run_id: int,
    context: str,
) -> None:
    try:
        _remove_owned_tree(path, run_id, context, missing_ok=True)
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
