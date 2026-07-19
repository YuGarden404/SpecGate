from __future__ import annotations

import contextlib
import errno
import hashlib
import ntpath
import os
import secrets
import stat
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Collection, Iterator


QUARANTINE_NAME_MARKER = ".specgate-quarantine-"
MAX_QUARANTINE_ENTRIES_PER_PARENT = 8
_POSIX_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_POSIX_MKDIR_SUPPORTS_DIR_FD = os.mkdir in os.supports_dir_fd
_POSIX_STAT_SUPPORTS_DIR_FD = os.stat in os.supports_dir_fd
_POSIX_SCANDIR_SUPPORTS_FD = os.scandir in os.supports_fd
_LEGACY_UPLOAD_QUARANTINE_NAME_MARKER = ".specgate-upload-quarantine-"
_QUARANTINE_PARENT_LOCK_NAME = ".specgate-quarantine.lock"
_QUARANTINE_PARENT_LOCK_STATE = threading.local()


if os.name == "nt":
    import ctypes as _windows_ctypes
    from ctypes import wintypes as _windows_wintypes

    class _WindowsByHandleFileInformation(_windows_ctypes.Structure):
        _fields_ = (
            ("file_attributes", _windows_wintypes.DWORD),
            ("creation_time", _windows_wintypes.FILETIME),
            ("last_access_time", _windows_wintypes.FILETIME),
            ("last_write_time", _windows_wintypes.FILETIME),
            ("volume_serial_number", _windows_wintypes.DWORD),
            ("file_size_high", _windows_wintypes.DWORD),
            ("file_size_low", _windows_wintypes.DWORD),
            ("number_of_links", _windows_wintypes.DWORD),
            ("file_index_high", _windows_wintypes.DWORD),
            ("file_index_low", _windows_wintypes.DWORD),
        )

    class _WindowsUnicodeString(_windows_ctypes.Structure):
        _fields_ = (
            ("length", _windows_wintypes.USHORT),
            ("maximum_length", _windows_wintypes.USHORT),
            ("buffer", _windows_wintypes.LPWSTR),
        )

    class _WindowsObjectAttributes(_windows_ctypes.Structure):
        _fields_ = (
            ("length", _windows_wintypes.ULONG),
            ("root_directory", _windows_wintypes.HANDLE),
            ("object_name", _windows_ctypes.POINTER(_WindowsUnicodeString)),
            ("attributes", _windows_wintypes.ULONG),
            ("security_descriptor", _windows_wintypes.LPVOID),
            ("security_quality_of_service", _windows_wintypes.LPVOID),
        )

    class _WindowsIoStatusBlock(_windows_ctypes.Structure):
        _fields_ = (
            ("status", _windows_ctypes.c_ssize_t),
            ("information", _windows_ctypes.c_size_t),
        )

    class _WindowsFileId128(_windows_ctypes.Structure):
        _fields_ = (("identifier", _windows_ctypes.c_ubyte * 16),)

    class _WindowsFileIdInfo(_windows_ctypes.Structure):
        _fields_ = (
            ("volume_serial_number", _windows_ctypes.c_ulonglong),
            ("file_id", _WindowsFileId128),
        )

    class _WindowsFileIdBothDirectoryInformation(_windows_ctypes.Structure):
        _fields_ = (
            ("next_entry_offset", _windows_wintypes.DWORD),
            ("file_index", _windows_wintypes.DWORD),
            ("creation_time", _windows_ctypes.c_longlong),
            ("last_access_time", _windows_ctypes.c_longlong),
            ("last_write_time", _windows_ctypes.c_longlong),
            ("change_time", _windows_ctypes.c_longlong),
            ("end_of_file", _windows_ctypes.c_longlong),
            ("allocation_size", _windows_ctypes.c_longlong),
            ("file_attributes", _windows_wintypes.DWORD),
            ("file_name_length", _windows_wintypes.DWORD),
            ("ea_size", _windows_wintypes.DWORD),
            ("short_name_length", _windows_ctypes.c_byte),
            ("short_name", _windows_ctypes.c_wchar * 12),
            ("file_id", _windows_ctypes.c_longlong),
        )

    _WINDOWS_CREATE_FILE_ARGTYPES = (
        _windows_wintypes.LPCWSTR,
        _windows_wintypes.DWORD,
        _windows_wintypes.DWORD,
        _windows_wintypes.LPVOID,
        _windows_wintypes.DWORD,
        _windows_wintypes.DWORD,
        _windows_wintypes.HANDLE,
    )
    _WINDOWS_GET_FILE_INFORMATION_ARGTYPES = (
        _windows_wintypes.HANDLE,
        _windows_ctypes.POINTER(_WindowsByHandleFileInformation),
    )
    _WINDOWS_NT_CREATE_FILE_ARGTYPES = (
        _windows_ctypes.POINTER(_windows_wintypes.HANDLE),
        _windows_wintypes.ULONG,
        _windows_ctypes.POINTER(_WindowsObjectAttributes),
        _windows_ctypes.POINTER(_WindowsIoStatusBlock),
        _windows_ctypes.POINTER(_windows_ctypes.c_longlong),
        _windows_wintypes.ULONG,
        _windows_wintypes.ULONG,
        _windows_wintypes.ULONG,
        _windows_wintypes.ULONG,
        _windows_wintypes.LPVOID,
        _windows_wintypes.ULONG,
    )
    _WINDOWS_GET_FILE_INFORMATION_EX_ARGTYPES = (
        _windows_wintypes.HANDLE,
        _windows_ctypes.c_int,
        _windows_wintypes.LPVOID,
        _windows_wintypes.DWORD,
    )
    _WINDOWS_CLOSE_HANDLE_ARGTYPES = (_windows_wintypes.HANDLE,)
    _WINDOWS_GET_FINAL_PATH_ARGTYPES = (
        _windows_wintypes.HANDLE,
        _windows_wintypes.LPWSTR,
        _windows_wintypes.DWORD,
        _windows_wintypes.DWORD,
    )


class WorkspacePathError(ValueError):
    def __init__(
        self,
        message: str,
        rule_family: str,
        *,
        missing_path: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.rule_family = rule_family
        self.missing_path = missing_path


class QuarantineQuotaError(WorkspacePathError):
    def __init__(self) -> None:
        super().__init__("quarantine storage quota exceeded", "storage_quota")


class WorkspaceTreeRenameError(WorkspacePathError):
    def __init__(self, message: str, *, quarantined: bool):
        super().__init__(message, "path_race")
        self.renamed = True
        self.quarantined = quarantined


@dataclass(frozen=True)
class WorkspaceFileState:
    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class WorkspaceFileMetadata:
    size_bytes: int


@dataclass(frozen=True)
class WorkspaceScanRejection:
    path: str
    rule_family: str
    message: str


@dataclass(frozen=True)
class WorkspaceScanResult:
    files: list[str]
    rejections: list[WorkspaceScanRejection]


@dataclass(frozen=True)
class WorkspaceTreeBinding:
    path: Path
    trusted_path: Path
    identity: tuple[int, int]
    parent_path: Path
    trusted_parent: Path
    parent_identity: tuple[int, int]


@dataclass(frozen=True)
class _StagingOwnership:
    path: Path
    identity: tuple[int, int]
    parent_path: Path
    parent_identity: tuple[int, int]
    trusted_parent: Path
    marker_path: Path
    marker_identity: tuple[int, int]
    token: str


@dataclass(frozen=True)
class _WorkspaceRootBinding:
    path: Path
    trusted_path: Path
    identity: tuple[int, int]


class _WindowsDirectoryLock(tuple):
    handle: int

    def __new__(
        cls,
        identity: tuple[int, int],
        handle: int,
    ) -> _WindowsDirectoryLock:
        instance = super().__new__(cls, identity)
        instance.handle = handle
        return instance


def make_quarantine_name(original_name: str, *, token: str | None = None) -> str:
    base_name = original_name.lstrip(".")
    if not base_name or any(separator in base_name for separator in ("/", "\\", "\x00")):
        raise WorkspacePathError("quarantine source name is invalid", "invalid_path")
    quarantine_token = secrets.token_hex(32) if token is None else token
    if not _is_high_entropy_quarantine_token(quarantine_token):
        raise WorkspacePathError("quarantine token is invalid", "invalid_path")
    return f".{base_name}{QUARANTINE_NAME_MARKER}{quarantine_token}"


def list_workspace_child_names(binding: WorkspaceTreeBinding) -> tuple[str, ...]:
    _verify_workspace_tree_binding(binding)
    if os.name == "nt":
        with _open_windows_directory_lock(
            binding.path,
            binding.trusted_path,
            binding.identity,
            list_directory=True,
        ) as directory_lock:
            names = _list_windows_directory_names(directory_lock.handle)
    else:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = _open_posix_root_fd(binding.path, flags, binding.identity)
        try:
            names = os.listdir(descriptor)
        finally:
            os.close(descriptor)
    _verify_workspace_tree_binding(binding)
    return tuple(sorted(names))


def count_quarantine_entries(binding: WorkspaceTreeBinding) -> int:
    return sum(_is_quarantine_name(name) for name in list_workspace_child_names(binding))


def ensure_quarantine_capacity(binding: WorkspaceTreeBinding) -> None:
    if count_quarantine_entries(binding) >= MAX_QUARANTINE_ENTRIES_PER_PARENT:
        raise QuarantineQuotaError()


@contextlib.contextmanager
def quarantine_parent_lock(binding: WorkspaceTreeBinding) -> Iterator[None]:
    _verify_workspace_tree_binding(binding)
    key = (
        os.path.normcase(os.path.normpath(binding.trusted_path)),
        binding.identity,
    )
    held = getattr(_QUARANTINE_PARENT_LOCK_STATE, "held", None)
    if held is None:
        held = {}
        _QUARANTINE_PARENT_LOCK_STATE.held = held
    depth = held.get(key, 0)
    if depth:
        held[key] = depth + 1
        try:
            _verify_workspace_tree_binding(binding)
            yield
        finally:
            held[key] -= 1
        return

    root_binding = _WorkspaceRootBinding(
        binding.path,
        binding.trusted_path,
        binding.identity,
    )
    with open_workspace_file(
        binding.path,
        _QUARANTINE_PARENT_LOCK_NAME,
        "update",
        create=True,
        _binding=root_binding,
    ) as handle:
        _prepare_and_lock_quarantine_handle(handle)
        held[key] = 1
        try:
            _verify_workspace_tree_binding(binding)
            yield
        finally:
            del held[key]
            _unlock_quarantine_handle(handle)


@contextlib.contextmanager
def workspace_file_lock(
    root: str | os.PathLike[str],
    relative: str,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock backed by a safe workspace file."""
    with open_workspace_file(root, relative, "update", create=True) as handle:
        _prepare_and_lock_quarantine_handle(handle)
        try:
            yield
        finally:
            _unlock_quarantine_handle(handle)


def _prepare_and_lock_quarantine_handle(handle: BinaryIO) -> None:
    try:
        _prepare_quarantine_lock_handle(handle)
    except PermissionError as exc:
        if os.name != "nt" or exc.errno not in {errno.EACCES, errno.EAGAIN}:
            raise

        # Another process may have initialized and locked byte zero after our
        # empty-file check. Wait for that lock, then validate preparation again.
        handle.seek(0)
        _lock_quarantine_handle(handle)
        try:
            _prepare_quarantine_lock_handle(handle)
        except BaseException:
            _unlock_quarantine_handle(handle)
            raise
        return

    _lock_quarantine_handle(handle)


def _prepare_quarantine_lock_handle(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _lock_quarantine_handle(handle: BinaryIO) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    time.sleep(0.01)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        raise WorkspacePathError(
            "quarantine parent lock could not be acquired",
            "path_race",
        ) from exc


def _unlock_quarantine_handle(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise WorkspacePathError(
            "quarantine parent lock could not be released",
            "path_race",
        ) from exc


def _is_high_entropy_quarantine_token(token: str) -> bool:
    return (
        isinstance(token, str)
        and len(token) == 64
        and all(character in "0123456789abcdef" for character in token)
    )


def _is_quarantine_name(name: str) -> bool:
    recognized_formats = (
        (QUARANTINE_NAME_MARKER, {32, 64}),
        (_LEGACY_UPLOAD_QUARANTINE_NAME_MARKER, {32}),
    )
    for marker_value, token_lengths in recognized_formats:
        prefix, marker, token = name.rpartition(marker_value)
        if (
            marker
            and prefix.startswith(".")
            and len(prefix) > 1
            and len(token) in token_lengths
            and all(character in "0123456789abcdef" for character in token)
        ):
            return True
    return False


def normalize_workspace_relative(value: str) -> str:
    if not isinstance(value, str):
        raise WorkspacePathError("workspace path must be a string", "invalid_path")
    if not value or "\x00" in value:
        raise WorkspacePathError("workspace path is empty or invalid", "invalid_path")

    drive, _ = ntpath.splitdrive(value)
    if drive or value.startswith(("/", "\\")):
        raise WorkspacePathError("workspace path must be relative", "path_escape")
    if "\\" in value:
        raise WorkspacePathError("workspace path contains a backslash", "invalid_path")

    parts = value.split("/")
    if any(part == "" for part in parts):
        raise WorkspacePathError("workspace path is not normalized", "invalid_path")
    if any(part in {".", ".."} for part in parts):
        family = "path_escape" if ".." in parts else "invalid_path"
        raise WorkspacePathError("workspace path contains a dot component", family)
    return "/".join(parts)


def is_link_like(path: Path | Any) -> bool:
    if path.is_symlink():
        return True

    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True

    file_stat = path.lstat()
    if stat.S_ISLNK(file_stat.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(file_stat, "st_file_attributes", 0) & reparse_flag)


@contextlib.contextmanager
def open_workspace_file(
    root: str | os.PathLike[str],
    relative: str,
    access: str = "read",
    *,
    create: bool = False,
    _binding: _WorkspaceRootBinding | None = None,
) -> Iterator[BinaryIO]:
    normalized = normalize_workspace_relative(relative)
    if access not in {"read", "write", "update"}:
        raise WorkspacePathError("unsupported workspace file access", "invalid_path")
    if create and access not in {"write", "update"}:
        raise WorkspacePathError("create requires writable access", "invalid_path")

    descriptor = -1
    try:
        try:
            root_path, trusted_root, root_identity = _validate_root(Path(root))
            if _binding is not None:
                _validate_root_binding(
                    root_path,
                    trusted_root,
                    root_identity,
                    _binding,
                )
            parts = normalized.split("/")
            if os.name == "nt":
                descriptor = _open_windows_workspace_fd(
                    root_path,
                    trusted_root,
                    root_identity,
                    parts,
                    access,
                    create,
                )
            else:
                descriptor = _open_posix_workspace_fd(
                    root_path,
                    root_identity,
                    parts,
                    access,
                    create,
                )

            _validate_regular_file(descriptor, normalized)
            if access == "write":
                os.ftruncate(descriptor, 0)
        except WorkspacePathError:
            raise
        except OSError as exc:
            raise WorkspacePathError(
                f"workspace file could not be opened: {normalized}",
                "path_race",
            ) from exc

        mode = {"read": "rb", "write": "wb", "update": "r+b"}[access]
        try:
            buffering = 0 if access == "update" else -1
            handle = os.fdopen(descriptor, mode, buffering=buffering)
        except OSError as exc:
            raise WorkspacePathError(
                f"workspace file handle could not be opened: {normalized}",
                "path_race",
            ) from exc
        descriptor = -1
        with handle:
            yield handle
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_workspace_bytes(root: str | os.PathLike[str], relative: str) -> bytes:
    try:
        with open_workspace_file(root, relative, "read") as handle:
            return handle.read()
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be read: {relative}",
            "path_race",
        ) from exc


def workspace_file_metadata(
    root: str | os.PathLike[str],
    relative: str,
) -> WorkspaceFileMetadata:
    normalized = normalize_workspace_relative(relative)
    try:
        with open_workspace_file(root, normalized, "read") as handle:
            try:
                file_stat = os.fstat(handle.fileno())
            except OSError as exc:
                raise WorkspacePathError(
                    f"workspace file metadata could not be read: {normalized}",
                    "path_race",
                ) from exc
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file metadata could not be read: {normalized}",
            "path_race",
        ) from exc
    return WorkspaceFileMetadata(size_bytes=file_stat.st_size)


def read_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    return read_workspace_bytes(root, relative).decode(encoding, errors)


def read_optional_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str | None:
    normalized = normalize_workspace_relative(relative)
    try:
        content = read_workspace_bytes(root, normalized)
    except WorkspacePathError as exc:
        if exc.rule_family == "path_race" and exc.missing_path == normalized:
            return None
        raise
    return content.decode(encoding, errors)


def write_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    content: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> None:
    data = content.encode(encoding, errors)
    write_workspace_bytes(root, relative, data)


def append_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    content: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> None:
    data = content.encode(encoding, errors)
    try:
        with open_workspace_file(root, relative, "update", create=True) as handle:
            handle.seek(0, os.SEEK_END)
            remaining = memoryview(data)
            while remaining:
                written = handle.write(remaining)
                if written is None or written <= 0 or written > len(remaining):
                    raise OSError("workspace append made no progress")
                remaining = remaining[written:]
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be appended: {relative}",
            "path_race",
        ) from exc


def write_workspace_bytes(
    root: str | os.PathLike[str],
    relative: str,
    content: bytes,
) -> None:
    try:
        with open_workspace_file(root, relative, "write", create=True) as handle:
            handle.write(content)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be written: {relative}",
            "path_race",
        ) from exc


def write_workspace_stream(
    root: str | os.PathLike[str],
    relative: str,
    source: BinaryIO,
    *,
    max_bytes: int,
    chunk_size: int = 64 * 1024,
) -> int:
    if max_bytes < 0 or chunk_size <= 0:
        raise ValueError("stream limits must be positive")

    written = 0
    try:
        with open_workspace_file(root, relative, "write", create=True) as handle:
            while True:
                chunk = source.read(min(chunk_size, max_bytes - written + 1))
                if not chunk:
                    return written
                if written + len(chunk) > max_bytes:
                    raise WorkspacePathError(
                        "workspace stream exceeds its size limit",
                        "size_limit",
                    )
                remaining = memoryview(chunk)
                while remaining:
                    accepted = handle.write(remaining)
                    if accepted is None or accepted <= 0 or accepted > len(remaining):
                        raise OSError("workspace stream write made no progress")
                    remaining = remaining[accepted:]
                written += len(chunk)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be written: {relative}",
            "path_race",
        ) from exc


def ensure_workspace_directory(
    root: str | os.PathLike[str],
    relative: str,
) -> None:
    normalized = normalize_workspace_relative(relative)
    try:
        root_path, trusted_path, identity = _validate_root(Path(root))
        binding = _WorkspaceRootBinding(root_path, trusted_path, identity)
        _ensure_workspace_directory(root_path, normalized, _binding=binding)
        _verify_bound_root(root_path, trusted_path, identity)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace directory could not be created safely",
            "path_race",
        ) from exc


def workspace_file_state(
    root: str | os.PathLike[str],
    relative: str,
) -> WorkspaceFileState:
    normalized = normalize_workspace_relative(relative)
    try:
        content = read_workspace_bytes(root, normalized)
    except WorkspacePathError as exc:
        if exc.missing_path == normalized:
            return WorkspaceFileState(False, None)
        raise
    return WorkspaceFileState(True, hashlib.sha256(content).hexdigest())


def iter_workspace_files(root: str | os.PathLike[str]) -> Iterator[str]:
    _, files = _scan_workspace(Path(root))
    yield from files


def scan_workspace_files(
    root: str | os.PathLike[str],
    *,
    excluded_dirs: Collection[str] = (),
) -> WorkspaceScanResult:
    excluded = frozenset(excluded_dirs)
    try:
        root_path, trusted_root, root_identity = _validate_root(Path(root))
        if os.name == "nt":
            return _scan_windows_workspace_tolerant(
                root_path,
                trusted_root,
                root_identity,
                excluded,
            )
        return _scan_posix_workspace_tolerant(root_path, root_identity, excluded)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace changed or could not be opened during scan",
            "path_race",
        ) from exc


def copy_workspace_tree(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> None:
    source_path = Path(source)
    source_binding, directories, files = _scan_bound_workspace(source_path)

    destination_path = Path(os.path.abspath(destination))
    ownership: _StagingOwnership | None = None
    try:
        try:
            destination_path.lstat()
        except FileNotFoundError:
            pass
        else:
            _reject_link_like(destination_path)
            raise WorkspacePathError(
                "workspace copy destination already exists",
                "path_race",
            )
        ownership = _create_private_staging(destination_path)

        for relative in directories:
            _ensure_workspace_directory(ownership.path, relative)
        for relative in files:
            write_workspace_bytes(
                ownership.path,
                relative,
                _read_bound_workspace_bytes(source_binding, relative),
            )
        _publish_workspace_tree(ownership, destination_path)
        ownership = None
    except BaseException as copy_error:
        # Recursive path cleanup cannot bind the staging root through rmtree's
        # final removal. Retain marked staging on failure rather than risk
        # deleting an object that replaced it.
        if isinstance(copy_error, WorkspacePathError):
            raise
        if isinstance(copy_error, OSError):
            raise WorkspacePathError(
                "workspace copy failed during filesystem I/O",
                "path_race",
            ) from copy_error
        raise


def bind_workspace_tree(
    path: str | os.PathLike[str],
    *,
    missing_ok: bool = False,
) -> WorkspaceTreeBinding | None:
    tree_path = Path(os.path.abspath(path))
    parent_path, trusted_parent, parent_identity = _validate_root(tree_path.parent)
    try:
        root_path, trusted_path, identity = _validate_root(tree_path)
    except FileNotFoundError:
        _verify_bound_root(parent_path, trusted_parent, parent_identity)
        if missing_ok:
            return None
        raise WorkspacePathError(
            "workspace tree does not exist",
            "path_race",
        ) from None

    expected_path = trusted_parent / tree_path.name
    if os.path.normcase(os.path.normpath(trusted_path)) != os.path.normcase(
        os.path.normpath(expected_path)
    ):
        raise WorkspacePathError(
            "workspace tree escaped its bound parent",
            "path_race",
        )
    _verify_bound_root(parent_path, trusted_parent, parent_identity)
    _verify_tree_identity(root_path, identity)
    return WorkspaceTreeBinding(
        path=root_path,
        trusted_path=trusted_path,
        identity=identity,
        parent_path=parent_path,
        trusted_parent=trusted_parent,
        parent_identity=parent_identity,
    )


def verify_workspace_tree_binding(binding: WorkspaceTreeBinding) -> None:
    _verify_workspace_tree_binding(binding)


def rename_workspace_tree_noreplace(
    binding: WorkspaceTreeBinding,
    destination: str | os.PathLike[str],
) -> WorkspaceTreeBinding:
    destination_path = Path(os.path.abspath(destination))
    _verify_workspace_tree_binding(binding)
    if os.path.normcase(os.path.normpath(destination_path.parent)) != os.path.normcase(
        os.path.normpath(binding.parent_path)
    ):
        raise WorkspacePathError(
            "workspace tree rename must stay within its bound parent",
            "path_escape",
        )
    try:
        destination_path.lstat()
    except FileNotFoundError:
        pass
    else:
        _reject_link_like(destination_path)
        raise WorkspacePathError(
            "workspace tree rename destination already exists",
            "path_race",
        )

    try:
        for attempt in range(3):
            try:
                _platform_rename_noreplace(binding.path, destination_path)
                break
            except PermissionError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) != 5 or attempt == 2:
                    raise
                _verify_workspace_tree_binding(binding)
                try:
                    destination_path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise WorkspacePathError(
                        "workspace tree rename destination appeared",
                        "path_race",
                    ) from exc
                time.sleep(0.01 * (attempt + 1))
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace tree rename failed",
            "path_race",
        ) from exc

    try:
        moved = bind_workspace_tree(destination_path)
        if moved is None or (
            moved.identity != binding.identity
            or moved.parent_identity != binding.parent_identity
        ):
            raise WorkspacePathError(
                "workspace tree identity changed during rename",
                "path_race",
            )
    except BaseException as verification_error:
        try:
            quarantine = _quarantine_unknown_tree(destination_path)
        except BaseException as quarantine_error:
            error = WorkspaceTreeRenameError(
                "renamed workspace tree could not be quarantined after verification failure",
                quarantined=False,
            )
            error.add_note(f"workspace tree quarantine failed: {quarantine_error}")
            raise error from verification_error
        raise WorkspaceTreeRenameError(
            "renamed workspace tree was quarantined after verification failure",
            quarantined=quarantine is not None,
        ) from verification_error
    return moved


def _verify_workspace_tree_binding(binding: WorkspaceTreeBinding) -> None:
    _verify_bound_root(
        binding.parent_path,
        binding.trusted_parent,
        binding.parent_identity,
    )
    _verify_bound_root(
        binding.path,
        binding.trusted_path,
        binding.identity,
    )


def publish_workspace_snapshot(
    destination: str | os.PathLike[str],
    *,
    source_trees: Collection[tuple[str | os.PathLike[str], str]] = (),
    directories: Collection[str] = (),
    files: Collection[tuple[str, bytes]] = (),
) -> None:
    destination_path = Path(os.path.abspath(destination))
    ownership: _StagingOwnership | None = None
    try:
        try:
            destination_path.lstat()
        except FileNotFoundError:
            pass
        else:
            _reject_link_like(destination_path)
            raise WorkspacePathError(
                "workspace snapshot destination already exists",
                "path_race",
            )
        ownership = _create_private_staging(destination_path)

        for relative in directories:
            _ensure_owned_workspace_directory(ownership, relative)
        for source, prefix in source_trees:
            normalized_prefix = normalize_workspace_relative(prefix)
            source_path = Path(source)
            source_binding, source_directories, source_files = _scan_bound_workspace(source_path)
            _ensure_owned_workspace_directory(ownership, normalized_prefix)
            for relative in source_directories:
                _ensure_owned_workspace_directory(
                    ownership,
                    f"{normalized_prefix}/{relative}",
                )
            for relative in source_files:
                _write_owned_workspace_bytes(
                    ownership,
                    f"{normalized_prefix}/{relative}",
                    _read_bound_workspace_bytes(source_binding, relative),
                )
        for relative, content in files:
            _write_owned_workspace_bytes(ownership, relative, content)

        _publish_workspace_tree(ownership, destination_path)
        ownership = None
    except BaseException as publish_error:
        if isinstance(publish_error, WorkspacePathError):
            raise
        if isinstance(publish_error, OSError):
            raise WorkspacePathError(
                "workspace snapshot failed during filesystem I/O",
                "path_race",
            ) from publish_error
        raise


def publish_workspace_bytes(
    root: str | os.PathLike[str],
    relative: str,
    content: bytes,
) -> None:
    normalized = normalize_workspace_relative(relative)
    root_path, trusted_path, identity = _validate_root(Path(root))
    binding = _WorkspaceRootBinding(root_path, trusted_path, identity)
    parts = normalized.split("/")
    temporary_name = f".{parts[-1]}.specgate-publish-{secrets.token_hex(16)}"
    temporary_relative = "/".join((*parts[:-1], temporary_name))

    try:
        write_workspace_bytes(root_path, temporary_relative, content)
        _verify_bound_root(root_path, trusted_path, identity)
        if workspace_file_state(root_path, normalized).exists:
            raise WorkspacePathError(
                "workspace publication target already exists",
                "path_race",
            )
        _rename_bound_workspace_noreplace(
            binding,
            temporary_relative,
            normalized,
        )
        _verify_bound_root(root_path, trusted_path, identity)
        if _read_bound_workspace_bytes(binding, normalized) != content:
            raise WorkspacePathError(
                "workspace publication content could not be verified",
                "path_race",
            )
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace file publication failed during filesystem I/O",
            "path_race",
        ) from exc


def _rename_bound_workspace_noreplace(
    binding: _WorkspaceRootBinding,
    source_relative: str,
    target_relative: str,
) -> None:
    source = normalize_workspace_relative(source_relative)
    target = normalize_workspace_relative(target_relative)
    _verify_bound_root(binding.path, binding.trusted_path, binding.identity)
    _platform_rename_noreplace(
        binding.path.joinpath(*source.split("/")),
        binding.path.joinpath(*target.split("/")),
    )
    _verify_bound_root(binding.path, binding.trusted_path, binding.identity)


def _ensure_owned_workspace_directory(
    ownership: _StagingOwnership,
    relative: str,
) -> None:
    _verify_owned_tree(ownership.path, ownership)
    _ensure_workspace_directory(ownership.path, relative)
    _verify_owned_tree(ownership.path, ownership)


def _write_owned_workspace_bytes(
    ownership: _StagingOwnership,
    relative: str,
    content: bytes,
) -> None:
    _verify_owned_tree(ownership.path, ownership)
    write_workspace_bytes(ownership.path, relative, content)
    _verify_owned_tree(ownership.path, ownership)


def _scan_bound_workspace(
    root: Path,
) -> tuple[_WorkspaceRootBinding, list[str], list[str]]:
    root_path, trusted_path, identity = _validate_root(root)
    binding = _WorkspaceRootBinding(root_path, trusted_path, identity)
    directories, files = _scan_workspace(root_path)
    _verify_bound_root(root_path, trusted_path, identity)
    return binding, directories, files


def _read_bound_workspace_bytes(
    binding: _WorkspaceRootBinding,
    relative: str,
) -> bytes:
    try:
        with open_workspace_file(
            binding.path,
            relative,
            "read",
            _binding=binding,
        ) as handle:
            content = handle.read()
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be read: {relative}",
            "path_race",
        ) from exc
    _verify_bound_root(binding.path, binding.trusted_path, binding.identity)
    return content


def _scan_workspace(root: Path) -> tuple[list[str], list[str]]:
    try:
        root_path, trusted_root, root_identity = _validate_root(root)
        if os.name == "nt":
            return _scan_windows_workspace(root_path, trusted_root, root_identity)
        return _scan_posix_workspace(root_path, root_identity)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace changed or could not be opened during scan",
            "path_race",
        ) from exc


def _scan_posix_workspace(
    root: Path,
    root_identity: tuple[int, int],
) -> tuple[list[str], list[str]]:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and _POSIX_OPEN_SUPPORTS_DIR_FD
        and _POSIX_SCANDIR_SUPPORTS_FD
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory scanning is unavailable",
            "path_race",
        )

    directories: list[str] = []
    files: list[str] = []
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    root_fd = _open_posix_root_fd(root, directory_flags, root_identity)

    def scan(current_fd: int, prefix: str) -> None:
        with os.scandir(current_fd) as scanner:
            for entry in sorted(scanner, key=lambda item: item.name):
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                normalized = normalize_workspace_relative(relative)
                _reject_link_like(root / normalized)
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise WorkspacePathError(
                        f"workspace entry changed during scan: {normalized}",
                        "path_race",
                    ) from exc
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise WorkspacePathError(
                        f"workspace scan found a symbolic link: {normalized}",
                        "linked_path",
                    )
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if getattr(entry_stat, "st_file_attributes", 0) & reparse_flag:
                    raise WorkspacePathError(
                        f"workspace scan found a reparse point: {normalized}",
                        "reparse_point",
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    try:
                        next_fd = os.open(
                            entry.name,
                            directory_flags,
                            dir_fd=current_fd,
                        )
                    except OSError as exc:
                        _raise_posix_link_error(exc, current_fd, entry.name)
                        raise
                    try:
                        _verify_same_object(entry_stat, os.fstat(next_fd))
                    except BaseException:
                        os.close(next_fd)
                        raise
                    directories.append(normalized)
                    try:
                        scan(next_fd, normalized)
                    finally:
                        os.close(next_fd)
                elif stat.S_ISREG(entry_stat.st_mode):
                    files.append(normalized)
                else:
                    raise WorkspacePathError(
                        f"workspace scan found a non-regular entry: {normalized}",
                        "unsafe_file_type",
                    )

    try:
        scan(root_fd, "")
        return sorted(directories), sorted(files)
    finally:
        os.close(root_fd)


def _scan_windows_workspace(
    root: Path,
    trusted_root: Path,
    root_identity: tuple[int, int],
) -> tuple[list[str], list[str]]:
    directories: list[str] = []
    files: list[str] = []

    def scan(
        current: Path,
        prefix: str,
        expected_identity: tuple[int, int],
        parent_lock: _WindowsDirectoryLock | None = None,
    ) -> None:
        expected = trusted_root.joinpath(*prefix.split("/")) if prefix else trusted_root
        with _open_windows_directory_lock(
            current,
            expected,
            expected_identity,
            parent_lock=parent_lock,
            relative_name=current.name if parent_lock is not None else None,
        ) as current_lock:
            discovered: list[tuple[Path, str, tuple[int, int]]] = []
            with os.scandir(current) as scanner:
                for entry in sorted(scanner, key=lambda item: item.name):
                    relative = f"{prefix}/{entry.name}" if prefix else entry.name
                    normalized = normalize_workspace_relative(relative)
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise WorkspacePathError(
                            f"workspace entry changed during scan: {normalized}",
                            "path_race",
                        ) from exc
                    entry_path = current / entry.name
                    if stat.S_ISLNK(entry_stat.st_mode):
                        raise WorkspacePathError(
                            f"workspace scan found a symbolic link: {normalized}",
                            "linked_path",
                        )
                    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    if getattr(entry_stat, "st_file_attributes", 0) & reparse_flag:
                        raise WorkspacePathError(
                            f"workspace scan found a reparse point: {normalized}",
                            "reparse_point",
                        )
                    _reject_link_like(entry_path)
                    if stat.S_ISDIR(entry_stat.st_mode):
                        directories.append(normalized)
                        discovered.append(
                            (
                                entry_path,
                                normalized,
                                (current_lock[0], entry.inode()),
                            )
                        )
                    elif stat.S_ISREG(entry_stat.st_mode):
                        descriptor = _open_windows_workspace_fd(
                            root,
                            trusted_root,
                            root_identity,
                            normalized.split("/"),
                            "read",
                            False,
                        )
                        os.close(descriptor)
                        files.append(normalized)
                    else:
                        raise WorkspacePathError(
                            f"workspace scan found a non-regular entry: {normalized}",
                            "unsafe_file_type",
                        )
            for entry_path, relative, entry_identity in discovered:
                scan(entry_path, relative, entry_identity, current_lock)

    scan(root, "", root_identity)
    return sorted(directories), sorted(files)


def _scan_posix_workspace_tolerant(
    root: Path,
    root_identity: tuple[int, int],
    excluded_dirs: frozenset[str],
) -> WorkspaceScanResult:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and _POSIX_OPEN_SUPPORTS_DIR_FD
        and _POSIX_SCANDIR_SUPPORTS_FD
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory scanning is unavailable",
            "path_race",
        )

    files: list[str] = []
    rejections: list[WorkspaceScanRejection] = []
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    root_fd = _open_posix_root_fd(root, directory_flags, root_identity)

    def reject(path: str, rule_family: str, message: str) -> None:
        rejections.append(WorkspaceScanRejection(path, rule_family, message))

    def scan(current_fd: int, prefix: str) -> None:
        try:
            with os.scandir(current_fd) as scanner:
                entries = sorted(scanner, key=lambda item: item.name)
        except OSError as exc:
            if not prefix:
                raise WorkspacePathError(
                    "workspace root changed during scan",
                    "path_race",
                ) from exc
            reject(prefix, "path_race", "directory changed during scan")
            return

        for entry in entries:
            raw_relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                relative = normalize_workspace_relative(raw_relative)
            except WorkspacePathError as exc:
                reject(raw_relative, exc.rule_family, exc.message)
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                reject(relative, "path_race", "entry changed during scan")
                continue

            if stat.S_ISLNK(entry_stat.st_mode):
                reject(relative, "linked_path", "symbolic link rejected")
                continue
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if getattr(entry_stat, "st_file_attributes", 0) & reparse_flag:
                reject(relative, "reparse_point", "reparse point rejected")
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                if entry.name in excluded_dirs:
                    continue
                try:
                    next_fd = os.open(
                        entry.name,
                        directory_flags,
                        dir_fd=current_fd,
                    )
                except OSError as exc:
                    try:
                        _raise_posix_link_error(exc, current_fd, entry.name)
                    except WorkspacePathError as link_error:
                        reject(relative, link_error.rule_family, link_error.message)
                    else:
                        reject(relative, "path_race", "directory changed before open")
                    continue
                try:
                    _verify_same_object(entry_stat, os.fstat(next_fd))
                except WorkspacePathError as exc:
                    os.close(next_fd)
                    reject(relative, exc.rule_family, exc.message)
                    continue
                except OSError:
                    os.close(next_fd)
                    reject(relative, "path_race", "directory changed after open")
                    continue
                try:
                    scan(next_fd, relative)
                finally:
                    os.close(next_fd)
            elif stat.S_ISREG(entry_stat.st_mode):
                files.append(relative)
            else:
                reject(relative, "unsafe_file_type", "non-regular entry rejected")

    try:
        scan(root_fd, "")
    finally:
        os.close(root_fd)
    return WorkspaceScanResult(
        sorted(files),
        sorted(rejections, key=lambda item: item.path),
    )


def _scan_windows_workspace_tolerant(
    root: Path,
    trusted_root: Path,
    root_identity: tuple[int, int],
    excluded_dirs: frozenset[str],
) -> WorkspaceScanResult:
    files: list[str] = []
    rejections: list[WorkspaceScanRejection] = []

    def reject(path: str, rule_family: str, message: str) -> None:
        rejections.append(WorkspaceScanRejection(path, rule_family, message))

    def scan(
        current: Path,
        prefix: str,
        expected_identity: tuple[int, int],
        parent_lock: _WindowsDirectoryLock | None = None,
    ) -> None:
        expected = trusted_root.joinpath(*prefix.split("/")) if prefix else trusted_root
        try:
            with _open_windows_directory_lock(
                current,
                expected,
                expected_identity,
                parent_lock=parent_lock,
                relative_name=current.name if parent_lock is not None else None,
            ) as current_lock:
                try:
                    with os.scandir(current) as scanner:
                        entries = sorted(scanner, key=lambda item: item.name)
                except OSError as exc:
                    if not prefix:
                        raise WorkspacePathError(
                            "workspace root changed during scan",
                            "path_race",
                        ) from exc
                    reject(prefix, "path_race", "directory changed during scan")
                    return

                discovered: list[tuple[Path, str, tuple[int, int]]] = []
                for entry in entries:
                    raw_relative = f"{prefix}/{entry.name}" if prefix else entry.name
                    try:
                        relative = normalize_workspace_relative(raw_relative)
                    except WorkspacePathError as exc:
                        reject(raw_relative, exc.rule_family, exc.message)
                        continue
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        reject(relative, "path_race", "entry changed during scan")
                        continue

                    if stat.S_ISLNK(entry_stat.st_mode):
                        reject(relative, "linked_path", "symbolic link rejected")
                        continue
                    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    if getattr(entry_stat, "st_file_attributes", 0) & reparse_flag:
                        reject(relative, "reparse_point", "reparse point rejected")
                        continue
                    entry_path = current / entry.name
                    try:
                        _reject_link_like(entry_path)
                    except WorkspacePathError as exc:
                        reject(relative, exc.rule_family, exc.message)
                        continue

                    if stat.S_ISDIR(entry_stat.st_mode):
                        if entry.name in excluded_dirs:
                            continue
                        discovered.append(
                            (
                                entry_path,
                                relative,
                                (current_lock[0], entry_stat.st_ino),
                            )
                        )
                    elif stat.S_ISREG(entry_stat.st_mode):
                        try:
                            descriptor = _open_windows_workspace_fd(
                                root,
                                trusted_root,
                                root_identity,
                                relative.split("/"),
                                "read",
                                False,
                            )
                        except WorkspacePathError as exc:
                            reject(relative, exc.rule_family, exc.message)
                            continue
                        except OSError:
                            reject(relative, "path_race", "file changed during scan")
                            continue
                        os.close(descriptor)
                        files.append(relative)
                    else:
                        reject(relative, "unsafe_file_type", "non-regular entry rejected")

                for entry_path, relative, entry_identity in discovered:
                    scan(entry_path, relative, entry_identity, current_lock)
        except WorkspacePathError as exc:
            if not prefix:
                raise
            reject(prefix, exc.rule_family, exc.message)
        except OSError as exc:
            if not prefix:
                raise WorkspacePathError(
                    "workspace root changed during scan",
                    "path_race",
                ) from exc
            reject(prefix, "path_race", "directory changed during scan")

    scan(root, "", root_identity)
    return WorkspaceScanResult(
        sorted(files),
        sorted(rejections, key=lambda item: item.path),
    )


def _create_private_staging(destination: Path) -> _StagingOwnership:
    parent_path, trusted_parent, parent_identity = _validate_root(destination.parent)
    prefix = f".{destination.name}.specgate-copy-"
    staging = Path(tempfile.mkdtemp(prefix=prefix, dir=parent_path))
    _verify_bound_root(parent_path, trusted_parent, parent_identity)
    token = secrets.token_hex(32)
    marker_name = f".{staging.name}.owner-{secrets.token_hex(16)}"
    marker_path = parent_path / marker_name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(marker_path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as marker:
        marker.write(token.encode("ascii"))
    return _StagingOwnership(
        path=staging,
        identity=_stat_identity(staging.lstat()),
        parent_path=parent_path,
        parent_identity=parent_identity,
        trusted_parent=trusted_parent,
        marker_path=marker_path,
        marker_identity=_stat_identity(marker_path.lstat()),
        token=token,
    )


def _publish_workspace_tree(
    ownership: _StagingOwnership,
    destination: Path,
) -> None:
    _verify_owned_tree(ownership.path, ownership)
    renamed = False
    try:
        for attempt in range(3):
            try:
                _rename_staging_noreplace(ownership.path, destination)
                break
            except PermissionError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) != 5 or attempt == 2:
                    raise
                _verify_owned_tree(ownership.path, ownership)
                try:
                    destination.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise WorkspacePathError(
                        "workspace copy destination appeared during publication",
                        "path_race",
                    ) from exc
                time.sleep(0.01 * (attempt + 1))
        renamed = True
        _verify_published_tree(
            destination,
            ownership.identity,
            ownership.marker_path,
            ownership.token,
        )
        _finalize_ownership_marker(ownership)
        _verify_tree_identity(destination, ownership.identity)
        _verify_bound_root(
            ownership.parent_path,
            ownership.trusted_parent,
            ownership.parent_identity,
        )
    except BaseException as publish_error:
        if renamed:
            _quarantine_unknown_tree(destination)
        if isinstance(publish_error, WorkspacePathError):
            raise
        if isinstance(publish_error, OSError):
            raise WorkspacePathError(
                "workspace copy publication could not be verified",
                "path_race",
            ) from publish_error
        raise


def _verify_tree_identity(path: Path, expected_identity: tuple[int, int]) -> None:
    file_stat = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(file_stat.st_mode)
        or getattr(file_stat, "st_file_attributes", 0) & reparse_flag
        or not stat.S_ISDIR(file_stat.st_mode)
        or _stat_identity(file_stat) != expected_identity
    ):
        raise WorkspacePathError(
            "workspace copy tree identity is uncertain",
            "path_race",
        )


def _verify_ownership_marker(
    marker_path: Path,
    expected_identity: tuple[int, int],
    token: str,
) -> None:
    marker_stat = marker_path.lstat()
    try:
        with open_workspace_file(marker_path.parent, marker_path.name) as marker:
            opened_stat = os.fstat(marker.fileno())
            marker_content = marker.read().decode("ascii")
    except (OSError, UnicodeError) as exc:
        raise WorkspacePathError(
            "workspace copy ownership marker is uncertain",
            "path_race",
        ) from exc
    if (
        not stat.S_ISREG(marker_stat.st_mode)
        or _stat_identity(marker_stat) != expected_identity
        or _stat_identity(opened_stat) != expected_identity
        or marker_content != token
    ):
        raise WorkspacePathError(
            "workspace copy ownership marker is uncertain",
            "path_race",
        )


def _verify_owned_tree(path: Path, ownership: _StagingOwnership) -> None:
    _verify_bound_root(
        ownership.parent_path,
        ownership.trusted_parent,
        ownership.parent_identity,
    )
    _verify_tree_identity(path, ownership.identity)
    _verify_ownership_marker(
        ownership.marker_path,
        ownership.marker_identity,
        ownership.token,
    )


def _verify_bound_root(
    path: Path,
    trusted_path: Path,
    expected_identity: tuple[int, int],
) -> None:
    _, current_trusted, current_identity = _validate_root(path)
    if current_identity != expected_identity or os.path.normcase(
        os.path.normpath(current_trusted)
    ) != os.path.normcase(os.path.normpath(trusted_path)):
        raise WorkspacePathError(
            "workspace root identity changed during publication",
            "path_race",
        )


def _validate_root_binding(
    root_path: Path,
    trusted_path: Path,
    identity: tuple[int, int],
    binding: _WorkspaceRootBinding,
) -> None:
    if (
        os.path.normcase(os.path.normpath(root_path))
        != os.path.normcase(os.path.normpath(binding.path))
        or os.path.normcase(os.path.normpath(trusted_path))
        != os.path.normcase(os.path.normpath(binding.trusted_path))
        or identity != binding.identity
    ):
        raise WorkspacePathError(
            "workspace root identity changed after scan",
            "path_race",
        )


def _verify_published_tree(
    destination: Path,
    expected_identity: tuple[int, int],
    marker_path: Path,
    marker_token: str,
) -> None:
    _verify_tree_identity(destination, expected_identity)
    marker_stat = marker_path.lstat()
    _verify_ownership_marker(
        marker_path,
        _stat_identity(marker_stat),
        marker_token,
    )


def _finalize_ownership_marker(ownership: _StagingOwnership) -> None:
    _verify_ownership_marker(
        ownership.marker_path,
        ownership.marker_identity,
        ownership.token,
    )
    # POSIX has no portable unlink-by-handle primitive, so deleting this path
    # after validation would reopen the same substitution race as tree cleanup.
    # Retain the private marker as an ownership receipt instead.


def _rename_staging_noreplace(staging: Path, destination: Path) -> None:
    _platform_rename_noreplace(staging, destination)


def _quarantine_unknown_tree(destination: Path) -> Path | None:
    try:
        destination.lstat()
    except FileNotFoundError:
        return None
    parent_binding = bind_workspace_tree(destination.parent)
    if parent_binding is None:
        raise WorkspacePathError("quarantine parent is missing", "path_race")
    with quarantine_parent_lock(parent_binding):
        ensure_quarantine_capacity(parent_binding)
        quarantine = destination.parent / make_quarantine_name(destination.name)
        try:
            _platform_rename_noreplace(destination, quarantine)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkspacePathError(
                "uncertain published tree could not be quarantined",
                "path_race",
            ) from exc
    return quarantine


def _platform_rename_noreplace(staging: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(staging, destination)
        return

    try:
        import ctypes
    except ImportError as exc:
        raise WorkspacePathError(
            "atomic no-replace directory publication is unavailable",
            "path_race",
        ) from exc

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename_exclusive = 0x00000004
        renamex_np = library.renamex_np
        renamex_np.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renamex_np.restype = ctypes.c_int
        result = renamex_np(
            os.fsencode(staging),
            os.fsencode(destination),
            rename_exclusive,
        )
    elif hasattr(library, "renameat2"):
        at_fdcwd = -100
        rename_noreplace = 1
        renameat2 = library.renameat2
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            os.fsencode(staging),
            at_fdcwd,
            os.fsencode(destination),
            rename_noreplace,
        )
    else:
        raise WorkspacePathError(
            "atomic no-replace directory publication is unavailable",
            "path_race",
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


def _ensure_workspace_directory(
    root: Path,
    relative: str,
    *,
    _binding: _WorkspaceRootBinding | None = None,
) -> None:
    parts = normalize_workspace_relative(relative).split("/")
    root_path, trusted_root, root_identity = _validate_root(root)
    if _binding is not None:
        _validate_root_binding(root_path, trusted_root, root_identity, _binding)
    if os.name == "nt":
        with contextlib.ExitStack() as directory_locks:
            parent_lock = directory_locks.enter_context(
                _open_windows_directory_lock(
                    root_path,
                    trusted_root,
                    root_identity,
                )
            )
            current = root_path
            for index, part in enumerate(parts, start=1):
                current /= part
                try:
                    file_stat = current.lstat()
                except FileNotFoundError:
                    try:
                        current.mkdir()
                    except FileExistsError:
                        pass
                    file_stat = current.lstat()
                _reject_link_like(current)
                if not stat.S_ISDIR(file_stat.st_mode):
                    raise WorkspacePathError(
                        f"workspace path is not a directory: {relative}",
                        "unsafe_file_type",
                    )
                parent_lock = directory_locks.enter_context(
                    _open_windows_directory_lock(
                        current,
                        trusted_root.joinpath(*parts[:index]),
                        _stat_identity(file_stat),
                        parent_lock=parent_lock,
                        relative_name=part,
                    )
                )
            expected = ntpath.normcase(ntpath.normpath(str(trusted_root.joinpath(*parts))))
            try:
                actual = ntpath.normcase(ntpath.normpath(str(current.resolve(strict=True))))
            except OSError as exc:
                raise WorkspacePathError(
                    "workspace directory changed while creating",
                    "path_race",
                ) from exc
            if actual != expected:
                raise WorkspacePathError(
                    "workspace directory escaped while creating",
                    "path_race",
                )
        return
    _ensure_posix_workspace_directory(root_path, root_identity, parts)


def _ensure_posix_workspace_directory(
    root: Path,
    root_identity: tuple[int, int],
    parts: list[str],
) -> None:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and _POSIX_OPEN_SUPPORTS_DIR_FD
        and _POSIX_MKDIR_SUPPORTS_DIR_FD
        and _POSIX_STAT_SUPPORTS_DIR_FD
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory handles are unavailable",
            "path_race",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    current_fd = _open_posix_root_fd(root, flags, root_identity)
    current_path = root
    try:
        for part in parts:
            current_path /= part
            _reject_link_like(current_path)
            try:
                before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.mkdir(part, dir_fd=current_fd)
                except FileExistsError:
                    pass
                before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise WorkspacePathError(
                    "workspace directory is a symbolic link",
                    "linked_path",
                )
            if not stat.S_ISDIR(before.st_mode):
                raise WorkspacePathError(
                    f"workspace path is not a directory: {'/'.join(parts)}",
                    "unsafe_file_type",
                )
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as exc:
                _raise_posix_link_error(exc, current_fd, part)
                raise
            try:
                _verify_same_object(before, os.fstat(next_fd))
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
    finally:
        os.close(current_fd)


def _validate_root(root: Path) -> tuple[Path, Path, tuple[int, int]]:
    root_path = Path(os.path.abspath(root))
    try:
        root_stat = root_path.lstat()
    except FileNotFoundError:
        raise
    _reject_link_like(root_path)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise WorkspacePathError("workspace root is not a directory", "unsafe_file_type")
    try:
        trusted_root = root_path.resolve(strict=True)
    except OSError as exc:
        raise WorkspacePathError("workspace root cannot be resolved", "path_race") from exc
    return root_path, trusted_root, _stat_identity(root_stat)


def _reject_link_like(path: Path) -> None:
    try:
        linked = is_link_like(path)
    except FileNotFoundError:
        return
    if not linked:
        return

    try:
        file_stat = path.lstat()
    except OSError:
        file_stat = None
    try:
        symbolic = path.is_symlink()
    except OSError:
        symbolic = False
    if symbolic or (file_stat is not None and stat.S_ISLNK(file_stat.st_mode)):
        family = "linked_path"
    else:
        family = "reparse_point"
    raise WorkspacePathError("workspace path contains a link-like object", family)


def _validate_regular_file(descriptor: int, relative: str) -> None:
    try:
        file_stat = os.fstat(descriptor)
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file changed while opening: {relative}",
            "path_race",
        ) from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise WorkspacePathError(
            f"workspace path is not a regular file: {relative}",
            "unsafe_file_type",
        )


def _open_windows_workspace_fd(
    root: Path,
    trusted_root: Path,
    root_identity: tuple[int, int],
    parts: list[str],
    access: str,
    create: bool,
) -> int:
    descriptor = -1
    try:
        with contextlib.ExitStack() as directory_locks:
            parent_lock = directory_locks.enter_context(
                _open_windows_directory_lock(root, trusted_root, root_identity)
            )
            current = root
            for index, part in enumerate(parts[:-1], start=1):
                current /= part
                try:
                    file_stat = current.lstat()
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        current.mkdir()
                    except FileExistsError:
                        pass
                    file_stat = current.lstat()
                _reject_link_like(current)
                if not stat.S_ISDIR(file_stat.st_mode):
                    raise WorkspacePathError(
                        f"workspace parent is not a directory: {part}",
                        "unsafe_file_type",
                    )
                parent_lock = directory_locks.enter_context(
                    _open_windows_directory_lock(
                        current,
                        trusted_root.joinpath(*parts[:index]),
                        _stat_identity(file_stat),
                        parent_lock=parent_lock,
                        relative_name=part,
                    )
                )

            target = current / parts[-1]
            try:
                target_stat = target.lstat()
            except FileNotFoundError as exc:
                target_stat = None
                if not create:
                    relative = "/".join(parts)
                    raise WorkspacePathError(
                        f"workspace file does not exist: {relative}",
                        "path_race",
                        missing_path=relative,
                    ) from exc
            if target_stat is not None:
                _reject_link_like(target)
                if not stat.S_ISREG(target_stat.st_mode):
                    raise WorkspacePathError(
                        f"workspace path is not a regular file: {'/'.join(parts)}",
                        "unsafe_file_type",
                    )

            flags = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
            flags |= {
                "read": os.O_RDONLY,
                "write": os.O_WRONLY,
                "update": os.O_RDWR,
            }[access]
            if create:
                flags |= os.O_CREAT
            try:
                descriptor = _open_windows_fd(target, flags, 0o666)
            except OSError as exc:
                _recheck_link_components(root, parts)
                raise exc

            _validate_windows_final_path(descriptor, trusted_root, parts)
        result = descriptor
        descriptor = -1
        return result
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _open_windows_fd(path: Path, flags: int, mode: int = 0o666) -> int:
    return os.open(path, flags, mode)


def _validate_windows_final_path(
    descriptor: int,
    trusted_root: Path,
    parts: list[str],
) -> None:
    resolver = _windows_final_path
    if not callable(resolver):
        raise WorkspacePathError(
            "Windows final-path verification is unavailable",
            "path_race",
        )
    try:
        actual = resolver(descriptor)
    except WorkspacePathError:
        raise
    except Exception as exc:
        raise WorkspacePathError(
            "Windows final-path verification failed",
            "path_race",
        ) from exc

    expected = trusted_root.joinpath(*parts)
    actual_value = ntpath.normcase(ntpath.normpath(str(actual)))
    expected_value = ntpath.normcase(ntpath.normpath(str(expected)))
    root_value = ntpath.normcase(ntpath.normpath(str(trusted_root)))
    try:
        contained = ntpath.commonpath((root_value, actual_value)) == root_value
    except ValueError:
        contained = False
    if not contained or actual_value != expected_value:
        raise WorkspacePathError(
            "workspace file changed location while opening",
            "path_race",
        )


@contextlib.contextmanager
def _open_windows_directory_lock(
    path: Path,
    expected: Path,
    expected_identity: tuple[int, int],
    *,
    parent_lock: _WindowsDirectoryLock | None = None,
    relative_name: str | None = None,
    list_directory: bool = False,
) -> Iterator[_WindowsDirectoryLock]:
    if os.name != "nt":
        raise RuntimeError("Windows directory handles are unavailable")
    _reject_link_like(path)
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError as exc:
        raise WorkspacePathError(
            "Windows directory handle APIs are unavailable",
            "path_race",
        ) from exc

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = _WINDOWS_CREATE_FILE_ARGTYPES
    create_file.restype = wintypes.HANDLE

    get_file_information = ctypes.windll.kernel32.GetFileInformationByHandle
    get_file_information.argtypes = _WINDOWS_GET_FILE_INFORMATION_ARGTYPES
    get_file_information.restype = wintypes.BOOL

    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_share_delete = 0x00000004
    file_list_directory = 0x00000001
    file_read_attributes = 0x00000080
    desired_access = file_read_attributes
    if list_directory:
        desired_access |= file_list_directory
    share_mode = file_share_read | file_share_write
    if _is_windows_anchor(path):
        share_mode |= file_share_delete
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    if parent_lock is None:
        handle = create_file(
            str(path),
            desired_access,
            share_mode,
            None,
            open_existing,
            file_flag_backup_semantics | file_flag_open_reparse_point,
            None,
        )
    elif relative_name is None:
        raise WorkspacePathError(
            "Windows relative directory name is unavailable",
            "path_race",
        )
    else:
        handle = _open_windows_relative_directory(
            parent_lock.handle,
            relative_name,
            share_mode,
            desired_access=desired_access,
        )
    if handle == ctypes.c_void_p(-1).value:
        raise WorkspacePathError(
            "Windows directory handle could not be opened safely",
            "path_race",
        )

    try:
        information = _WindowsByHandleFileInformation()
        if not get_file_information(handle, ctypes.byref(information)):
            raise ctypes.WinError()
        file_attribute_directory = 0x00000010
        file_attribute_reparse_point = 0x00000400
        if information.file_attributes & file_attribute_reparse_point:
            raise WorkspacePathError(
                "workspace scan found a reparse directory",
                "reparse_point",
            )
        if not information.file_attributes & file_attribute_directory:
            raise WorkspacePathError(
                "workspace scan path is not a directory",
                "unsafe_file_type",
            )
        actual_identity = _windows_handle_identity(handle, information)
        if actual_identity != expected_identity:
            raise WorkspacePathError(
                "workspace directory identity changed during scan",
                "path_race",
            )
        actual = _windows_final_path_from_handle(handle)
        actual_value = ntpath.normcase(ntpath.normpath(str(actual)))
        expected_value = ntpath.normcase(ntpath.normpath(str(expected)))
        if actual_value != expected_value:
            raise WorkspacePathError(
                "workspace directory changed location during scan",
                "path_race",
            )
        yield _WindowsDirectoryLock(actual_identity, handle)
    finally:
        if not _windows_close_handle(handle):
            raise WorkspacePathError(
                "Windows directory handle could not be closed",
                "path_race",
            )


def _open_windows_relative_directory(
    parent_handle: int,
    relative_name: str,
    share_mode: int,
    *,
    desired_access: int = 0x00000080,
) -> int:
    import ctypes
    from ctypes import wintypes

    nt_create_file = ctypes.windll.ntdll.NtCreateFile
    nt_create_file.argtypes = _WINDOWS_NT_CREATE_FILE_ARGTYPES
    nt_create_file.restype = ctypes.c_long

    file_open = 0x00000001
    file_directory_file = 0x00000001
    file_open_reparse_point = 0x00200000
    obj_case_insensitive = 0x00000040
    name_buffer = ctypes.create_unicode_buffer(relative_name)
    name = _WindowsUnicodeString(
        len(relative_name) * ctypes.sizeof(ctypes.c_wchar),
        (len(relative_name) + 1) * ctypes.sizeof(ctypes.c_wchar),
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _WindowsObjectAttributes(
        ctypes.sizeof(_WindowsObjectAttributes),
        parent_handle,
        ctypes.pointer(name),
        obj_case_insensitive,
        None,
        None,
    )
    io_status = _WindowsIoStatusBlock()
    handle = wintypes.HANDLE()
    status = nt_create_file(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0,
        share_mode,
        file_open,
        file_directory_file | file_open_reparse_point,
        None,
        0,
    )
    if status < 0 or not handle.value:
        raise WorkspacePathError(
            "Windows directory could not be locked against replacement",
            "path_race",
        )
    return int(handle.value)


def _list_windows_directory_names(handle: int) -> list[str]:
    import ctypes
    from ctypes import wintypes

    get_information = ctypes.windll.kernel32.GetFileInformationByHandleEx
    get_information.argtypes = _WINDOWS_GET_FILE_INFORMATION_EX_ARGTYPES
    get_information.restype = wintypes.BOOL
    get_last_error = ctypes.windll.kernel32.GetLastError
    get_last_error.argtypes = ()
    get_last_error.restype = wintypes.DWORD
    file_id_both_directory_info = 10
    file_id_both_directory_restart_info = 11
    error_no_more_files = 18
    buffer = ctypes.create_string_buffer(64 * 1024)
    names: list[str] = []
    information_class = file_id_both_directory_restart_info
    file_name_offset = ctypes.sizeof(_WindowsFileIdBothDirectoryInformation)

    while True:
        if not get_information(
            handle,
            information_class,
            buffer,
            ctypes.sizeof(buffer),
        ):
            error = get_last_error()
            if error == error_no_more_files:
                break
            raise ctypes.WinError(error)
        information_class = file_id_both_directory_info
        offset = 0
        while True:
            entry = _WindowsFileIdBothDirectoryInformation.from_buffer(buffer, offset)
            name = ctypes.wstring_at(
                ctypes.addressof(buffer) + offset + file_name_offset,
                entry.file_name_length // ctypes.sizeof(ctypes.c_wchar),
            )
            if name not in {".", ".."}:
                names.append(name)
            if entry.next_entry_offset == 0:
                break
            offset += entry.next_entry_offset
    return names


def _is_windows_anchor(path: Path) -> bool:
    normalized = ntpath.normpath(str(path))
    drive, tail = ntpath.splitdrive(normalized)
    if not drive or not ntpath.isabs(normalized):
        return False
    if not drive.startswith("\\\\"):
        return tail == "\\"
    components = [component for component in drive.lstrip("\\").split("\\") if component]
    return len(components) == 2 and tail in {"", "\\"}


def _stat_identity(file_stat: os.stat_result | Any) -> tuple[int, int]:
    return file_stat.st_dev, file_stat.st_ino


def _windows_handle_identity(handle: int, information: Any) -> tuple[int, int]:
    file_index = (information.file_index_high << 32) | information.file_index_low
    volume_serial = _windows_handle_volume_serial(handle)
    # Python 3.13 exposes the 64-bit serial in st_dev; older releases expose its low 32 bits.
    if sys.version_info < (3, 13):
        volume_serial &= 0xFFFFFFFF
    return volume_serial, file_index


def _windows_handle_volume_serial(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    get_information = ctypes.windll.kernel32.GetFileInformationByHandleEx
    get_information.argtypes = _WINDOWS_GET_FILE_INFORMATION_EX_ARGTYPES
    get_information.restype = wintypes.BOOL
    file_id_info_class = 18
    information = _WindowsFileIdInfo()
    if not get_information(
        handle,
        file_id_info_class,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError()
    return information.volume_serial_number


def _windows_close_handle(handle: int) -> bool:
    import ctypes
    from ctypes import wintypes

    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = _WINDOWS_CLOSE_HANDLE_ARGTYPES
    close_handle.restype = wintypes.BOOL
    return bool(close_handle(handle))


def _windows_final_path(descriptor: int) -> Path:
    if os.name != "nt":
        raise RuntimeError("Windows final paths are unavailable")
    try:
        import msvcrt
    except ImportError as exc:
        raise RuntimeError("Windows handle APIs are unavailable") from exc

    handle = msvcrt.get_osfhandle(descriptor)
    return _windows_final_path_from_handle(handle)


def _windows_final_path_from_handle(handle: int) -> Path:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError as exc:
        raise RuntimeError("Windows handle APIs are unavailable") from exc

    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = _WINDOWS_GET_FINAL_PATH_ARGTYPES
    get_final_path.restype = wintypes.DWORD
    required = get_final_path(handle, None, 0, 0)
    if not required:
        raise ctypes.WinError()
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if not written or written >= len(buffer):
        raise ctypes.WinError()
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _open_posix_workspace_fd(
    root: Path,
    root_identity: tuple[int, int],
    parts: list[str],
    access: str,
    create: bool,
) -> int:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and _POSIX_OPEN_SUPPORTS_DIR_FD
        and _POSIX_MKDIR_SUPPORTS_DIR_FD
        and _POSIX_STAT_SUPPORTS_DIR_FD
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory handles are unavailable",
            "path_race",
        )

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    current_fd = _open_posix_root_fd(root, directory_flags, root_identity)
    try:
        current_path = root
        for part in parts[:-1]:
            current_path /= part
            _reject_link_like(current_path)
            try:
                before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, dir_fd=current_fd)
                except FileExistsError:
                    pass
                before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise WorkspacePathError(
                    "workspace parent is a symbolic link",
                    "linked_path",
                )
            if not stat.S_ISDIR(before.st_mode):
                raise WorkspacePathError(
                    f"workspace parent is not a directory: {part}",
                    "unsafe_file_type",
                )
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                _raise_posix_link_error(exc, current_fd, part)
                raise
            try:
                _verify_same_object(before, os.fstat(next_fd))
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd

        final_name = parts[-1]
        _reject_link_like(current_path / final_name)
        try:
            before = os.stat(final_name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            before = None
            if not create:
                relative = "/".join(parts)
                raise WorkspacePathError(
                    f"workspace file does not exist: {relative}",
                    "path_race",
                    missing_path=relative,
                ) from exc
        if before is not None:
            if stat.S_ISLNK(before.st_mode):
                raise WorkspacePathError(
                    "workspace file is a symbolic link",
                    "linked_path",
                )
            if not stat.S_ISREG(before.st_mode):
                raise WorkspacePathError(
                    f"workspace path is not a regular file: {'/'.join(parts)}",
                    "unsafe_file_type",
                )

        flags = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        flags |= {
            "read": os.O_RDONLY,
            "write": os.O_WRONLY,
            "update": os.O_RDWR,
        }[access]
        if create:
            flags |= os.O_CREAT
        try:
            descriptor = os.open(final_name, flags, 0o666, dir_fd=current_fd)
        except OSError as exc:
            _raise_posix_link_error(exc, current_fd, final_name)
            raise
        try:
            if before is not None:
                _verify_same_object(before, os.fstat(descriptor))
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(current_fd)


def _open_posix_root_fd(
    root: Path,
    flags: int,
    expected_identity: tuple[int, int],
) -> int:
    if not root.is_absolute():
        raise WorkspacePathError("workspace root must be absolute", "path_race")

    current_fd = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise WorkspacePathError(
                    "workspace root ancestor is a symbolic link",
                    "linked_path",
                )
            if not stat.S_ISDIR(before.st_mode):
                raise WorkspacePathError(
                    "workspace root ancestor is not a directory",
                    "unsafe_file_type",
                )
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as exc:
                _raise_posix_link_error(exc, current_fd, part)
                raise
            try:
                _verify_same_object(before, os.fstat(next_fd))
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd

        if _stat_identity(os.fstat(current_fd)) != expected_identity:
            raise WorkspacePathError(
                "workspace root identity changed while opening",
                "path_race",
            )
        descriptor = current_fd
        current_fd = -1
        return descriptor
    finally:
        if current_fd >= 0:
            os.close(current_fd)


def _verify_same_object(before: os.stat_result, after: os.stat_result) -> None:
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise WorkspacePathError(
            "workspace path changed while opening",
            "path_race",
        )


def _raise_posix_link_error(exc: OSError, directory_fd: int, name: str) -> None:
    if exc.errno not in {errno.ELOOP, errno.ENOTDIR}:
        return
    try:
        file_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        return
    if stat.S_ISLNK(file_stat.st_mode):
        raise WorkspacePathError(
            "workspace path contains a symbolic link",
            "linked_path",
        ) from exc


def _recheck_link_components(root: Path, parts: list[str]) -> None:
    current = root
    _reject_link_like(current)
    for part in parts:
        current /= part
        _reject_link_like(current)
