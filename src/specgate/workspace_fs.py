from __future__ import annotations

import contextlib
import errno
import hashlib
import ntpath
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator


class WorkspacePathError(ValueError):
    def __init__(self, message: str, rule_family: str):
        super().__init__(message)
        self.message = message
        self.rule_family = rule_family


@dataclass(frozen=True)
class WorkspaceFileState:
    exists: bool
    sha256: str | None


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
) -> Iterator[BinaryIO]:
    normalized = normalize_workspace_relative(relative)
    if access not in {"read", "write"}:
        raise WorkspacePathError("unsupported workspace file access", "invalid_path")
    if create and access != "write":
        raise WorkspacePathError("create requires write access", "invalid_path")

    descriptor = -1
    try:
        try:
            root_path, trusted_root = _validate_root(Path(root))
            parts = normalized.split("/")
            if os.name == "nt":
                descriptor = _open_windows_workspace_fd(
                    root_path,
                    trusted_root,
                    parts,
                    access,
                    create,
                )
            else:
                descriptor = _open_posix_workspace_fd(root_path, parts, access, create)

            _validate_regular_file(descriptor, normalized)
            if access == "write":
                os.ftruncate(descriptor, 0)
        except (WorkspacePathError, FileNotFoundError):
            raise
        except OSError as exc:
            raise WorkspacePathError(
                f"workspace file could not be opened: {normalized}",
                "path_race",
            ) from exc

        mode = "rb" if access == "read" else "wb"
        try:
            handle = os.fdopen(descriptor, mode)
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
    with open_workspace_file(root, relative, "read") as handle:
        return handle.read()


def read_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    return read_workspace_bytes(root, relative).decode(encoding, errors)


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


def write_workspace_bytes(
    root: str | os.PathLike[str],
    relative: str,
    content: bytes,
) -> None:
    with open_workspace_file(root, relative, "write", create=True) as handle:
        handle.write(content)


def workspace_file_state(
    root: str | os.PathLike[str],
    relative: str,
) -> WorkspaceFileState:
    try:
        content = read_workspace_bytes(root, relative)
    except FileNotFoundError:
        return WorkspaceFileState(False, None)
    return WorkspaceFileState(True, hashlib.sha256(content).hexdigest())


def iter_workspace_files(root: str | os.PathLike[str]) -> Iterator[str]:
    _, files = _scan_workspace(Path(root))
    yield from files


def copy_workspace_tree(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> None:
    source_path = Path(source)
    directories, files = _scan_workspace(source_path)

    destination_path = Path(os.path.abspath(destination))
    try:
        destination_path.lstat()
    except FileNotFoundError:
        pass
    else:
        _reject_link_like(destination_path)
        raise FileExistsError(destination_path)
    destination_path.mkdir()

    try:
        for relative in directories:
            _ensure_workspace_directory(destination_path, relative)
        for relative in files:
            write_workspace_bytes(
                destination_path,
                relative,
                read_workspace_bytes(source_path, relative),
            )
    except BaseException:
        try:
            _remove_created_destination(destination_path)
        except OSError as exc:
            raise WorkspacePathError(
                "workspace copy failed and destination cleanup was incomplete",
                "path_race",
            ) from exc
        raise


def _scan_workspace(root: Path) -> tuple[list[str], list[str]]:
    try:
        root_path, trusted_root = _validate_root(root)
        if os.name == "nt":
            return _scan_windows_workspace(root_path, trusted_root)
        return _scan_posix_workspace(root_path)
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            "workspace changed or could not be opened during scan",
            "path_race",
        ) from exc


def _scan_posix_workspace(root: Path) -> tuple[list[str], list[str]]:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.scandir in os.supports_fd
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
    root_before = root.lstat()
    root_fd = os.open(root, directory_flags)

    def scan(current_fd: int, prefix: str) -> None:
        with os.scandir(current_fd) as scanner:
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
        _verify_same_object(root_before, os.fstat(root_fd))
        scan(root_fd, "")
        return sorted(directories), sorted(files)
    finally:
        os.close(root_fd)


def _scan_windows_workspace(
    root: Path,
    trusted_root: Path,
) -> tuple[list[str], list[str]]:
    directories: list[str] = []
    files: list[str] = []

    def scan(current: Path, prefix: str) -> None:
        expected = trusted_root.joinpath(*prefix.split("/")) if prefix else trusted_root
        with _open_windows_directory_lock(current, expected):
            discovered: list[tuple[Path, str]] = []
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
                        discovered.append((entry_path, normalized))
                    elif stat.S_ISREG(entry_stat.st_mode):
                        descriptor = _open_windows_workspace_fd(
                            root,
                            trusted_root,
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
            for entry_path, relative in discovered:
                scan(entry_path, relative)

    scan(root, "")
    return sorted(directories), sorted(files)


def _remove_created_destination(destination: Path) -> None:
    try:
        file_stat = destination.lstat()
    except FileNotFoundError:
        return
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(file_stat.st_mode):
        destination.unlink()
    elif getattr(file_stat, "st_file_attributes", 0) & reparse_flag:
        destination.rmdir()
    else:
        shutil.rmtree(destination)


def _ensure_workspace_directory(root: Path, relative: str) -> None:
    parts = normalize_workspace_relative(relative).split("/")
    root_path, trusted_root = _validate_root(root)
    if os.name == "nt":
        current = root_path
        for part in parts:
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
    _ensure_posix_workspace_directory(root_path, parts)


def _ensure_posix_workspace_directory(root: Path, parts: list[str]) -> None:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory handles are unavailable",
            "path_race",
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    current_fd = os.open(root, flags)
    try:
        for part in parts:
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


def _validate_root(root: Path) -> tuple[Path, Path]:
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
    return root_path, trusted_root


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
    parts: list[str],
    access: str,
    create: bool,
) -> int:
    current = root
    for part in parts[:-1]:
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

    target = current / parts[-1]
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
        if not create:
            raise
    if target_stat is not None:
        _reject_link_like(target)
        if not stat.S_ISREG(target_stat.st_mode):
            raise WorkspacePathError(
                f"workspace path is not a regular file: {'/'.join(parts)}",
                "unsafe_file_type",
            )

    flags = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    flags |= os.O_RDONLY if access == "read" else os.O_WRONLY
    if create:
        flags |= os.O_CREAT
    try:
        descriptor = _open_windows_fd(target, flags, 0o666)
    except OSError as exc:
        _recheck_link_components(root, parts)
        raise exc

    try:
        _validate_windows_final_path(descriptor, trusted_root, parts)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


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
def _open_windows_directory_lock(path: Path, expected: Path) -> Iterator[None]:
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
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        )

    get_file_information = ctypes.windll.kernel32.GetFileInformationByHandle
    get_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    )
    get_file_information.restype = wintypes.BOOL

    file_read_attributes = 0x0080
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        file_read_attributes,
        file_share_read | file_share_write,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()

    try:
        information = ByHandleFileInformation()
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
        actual = _windows_final_path_from_handle(handle)
        actual_value = ntpath.normcase(ntpath.normpath(str(actual)))
        expected_value = ntpath.normcase(ntpath.normpath(str(expected)))
        if actual_value != expected_value:
            raise WorkspacePathError(
                "workspace directory changed location during scan",
                "path_race",
            )
        yield
    finally:
        close_handle(handle)


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
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
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
    parts: list[str],
    access: str,
    create: bool,
) -> int:
    required = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
    )
    if not required:
        raise WorkspacePathError(
            "secure POSIX directory handles are unavailable",
            "path_race",
        )

    root_before = root.lstat()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    current_fd = os.open(root, directory_flags)
    try:
        _verify_same_object(root_before, os.fstat(current_fd))
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
        except FileNotFoundError:
            before = None
            if not create:
                raise
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
        flags |= os.O_RDONLY if access == "read" else os.O_WRONLY
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
