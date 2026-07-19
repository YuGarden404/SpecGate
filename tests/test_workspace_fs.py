from __future__ import annotations

import ctypes
import errno
import hashlib
import io
import os
import shutil
import stat
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import specgate.workspace_fs as workspace_fs
from specgate.workspace_fs import (
    WorkspacePathError,
    append_workspace_text,
    copy_workspace_tree,
    iter_workspace_files,
    is_link_like,
    normalize_workspace_relative,
    open_workspace_file,
    publish_workspace_bytes,
    publish_workspace_snapshot,
    read_workspace_bytes,
    read_workspace_text,
    workspace_file_state,
    write_workspace_bytes,
    write_workspace_stream,
    write_workspace_text,
)


class WorkspacePathErrorTests(unittest.TestCase):
    def test_exposes_message_and_rule_family(self):
        error = WorkspacePathError("unsafe path", "linked_path")

        self.assertEqual(str(error), "unsafe path")
        self.assertEqual(error.rule_family, "linked_path")


class WorkspaceDirectChildTests(unittest.TestCase):
    def make_bound_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "root"
        root.mkdir()
        binding = workspace_fs.bind_workspace_tree(root)
        self.assertIsNotNone(binding)
        return root, binding

    def test_quarantine_names_use_public_high_entropy_marker(self):
        name = workspace_fs.make_quarantine_name("workspace")

        self.assertIn(workspace_fs.QUARANTINE_NAME_MARKER, name)
        token = name.rsplit(workspace_fs.QUARANTINE_NAME_MARKER, 1)[-1]
        self.assertEqual(len(token), 64)
        int(token, 16)
        self.assertEqual(workspace_fs.MAX_QUARANTINE_ENTRIES_PER_PARENT, 8)

    def test_lists_only_direct_child_names_without_path_scandir(self):
        root, binding = self.make_bound_root()
        (root / "file.txt").write_text("file", encoding="utf-8")
        (root / "directory").mkdir()
        (root / "directory" / "nested.txt").write_text("nested", encoding="utf-8")

        with mock.patch("os.scandir", side_effect=AssertionError("path scandir used")):
            names = workspace_fs.list_workspace_child_names(binding)

        self.assertEqual(names, ("directory", "file.txt"))

    def test_counts_only_well_formed_direct_quarantine_names(self):
        root, binding = self.make_bound_root()
        valid_names = [
            workspace_fs.make_quarantine_name(f"tree-{index}")
            for index in range(3)
        ]
        for name in valid_names:
            (root / name).mkdir()
        (root / "ordinary").mkdir()
        (root / f"fake{workspace_fs.QUARANTINE_NAME_MARKER}short").mkdir()
        nested = root / "ordinary" / workspace_fs.make_quarantine_name("nested")
        nested.mkdir()

        self.assertEqual(workspace_fs.count_quarantine_entries(binding), 3)

    def test_counts_legacy_run_and_upload_quarantine_names_after_upgrade(self):
        root, binding = self.make_bound_root()
        legacy_names = (
            f".workspace.specgate-quarantine-{'a' * 32}",
            f".specgate-upload-old.specgate-upload-quarantine-{'b' * 32}",
        )
        invalid_names = (
            f".workspace.specgate-quarantine-{'c' * 31}",
            f".workspace.specgate-quarantine-{'z' * 32}",
            f".specgate-upload-old.specgate-upload-quarantine-{'d' * 64}",
            f"workspace.specgate-quarantine-{'e' * 32}",
        )
        for name in (*legacy_names, *invalid_names):
            (root / name).mkdir()

        self.assertEqual(workspace_fs.count_quarantine_entries(binding), 2)


class WorkspaceFileLockTests(unittest.TestCase):
    @staticmethod
    def opened_handle():
        handle = mock.MagicMock()
        opened = mock.MagicMock()
        opened.__enter__.return_value = handle
        opened.__exit__.return_value = None
        return handle, opened

    def test_windows_initialization_contention_waits_then_prepares_under_lock(self):
        handle, opened = self.opened_handle()
        events = []
        prepare_calls = 0

        def prepare(actual_handle):
            nonlocal prepare_calls
            self.assertIs(actual_handle, handle)
            prepare_calls += 1
            if prepare_calls == 1:
                events.append("prepare-contended")
                raise PermissionError(errno.EACCES, "lock byte is already held")
            events.append("prepare-after-lock")

        handle.seek.side_effect = lambda offset: events.append(f"seek-{offset}")
        with (
            mock.patch.object(workspace_fs.os, "name", "nt"),
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened),
            mock.patch.object(
                workspace_fs,
                "_prepare_quarantine_lock_handle",
                side_effect=prepare,
            ),
            mock.patch.object(
                workspace_fs,
                "_lock_quarantine_handle",
                side_effect=lambda actual: events.append("lock"),
            ),
            mock.patch.object(
                workspace_fs,
                "_unlock_quarantine_handle",
                side_effect=lambda actual: events.append("unlock"),
            ),
        ):
            with workspace_fs.workspace_file_lock("unused", "approval.lock"):
                events.append("yield")

        self.assertEqual(
            events,
            [
                "prepare-contended",
                "seek-0",
                "lock",
                "prepare-after-lock",
                "yield",
                "unlock",
            ],
        )

    def test_windows_second_preparation_failure_releases_acquired_lock(self):
        handle, opened = self.opened_handle()
        events = []
        prepare_errors = iter(
            (
                PermissionError(errno.EAGAIN, "lock byte is already held"),
                RuntimeError("sentinel preparation failed"),
            )
        )

        def prepare(actual_handle):
            events.append("prepare")
            raise next(prepare_errors)

        handle.seek.side_effect = lambda offset: events.append(f"seek-{offset}")
        with (
            mock.patch.object(workspace_fs.os, "name", "nt"),
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened),
            mock.patch.object(
                workspace_fs,
                "_prepare_quarantine_lock_handle",
                side_effect=prepare,
            ),
            mock.patch.object(
                workspace_fs,
                "_lock_quarantine_handle",
                side_effect=lambda actual: events.append("lock"),
            ),
            mock.patch.object(
                workspace_fs,
                "_unlock_quarantine_handle",
                side_effect=lambda actual: events.append("unlock"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "sentinel preparation failed"):
                with workspace_fs.workspace_file_lock("unused", "approval.lock"):
                    self.fail("lock context yielded after failed preparation")

        self.assertEqual(
            events,
            ["prepare", "seek-0", "lock", "prepare", "unlock"],
        )

    def test_windows_unexpected_preparation_permission_error_propagates(self):
        handle, opened = self.opened_handle()
        unexpected = PermissionError(errno.EPERM, "unexpected permission failure")
        with (
            mock.patch.object(workspace_fs.os, "name", "nt"),
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened),
            mock.patch.object(
                workspace_fs,
                "_prepare_quarantine_lock_handle",
                side_effect=unexpected,
            ),
            mock.patch.object(workspace_fs, "_lock_quarantine_handle") as acquire,
            mock.patch.object(workspace_fs, "_unlock_quarantine_handle") as release,
        ):
            with self.assertRaises(PermissionError) as raised:
                with workspace_fs.workspace_file_lock("unused", "approval.lock"):
                    self.fail("lock context yielded after failed preparation")

        self.assertIs(raised.exception, unexpected)
        acquire.assert_not_called()
        release.assert_not_called()

    def test_non_windows_preparation_permission_error_propagates(self):
        handle, opened = self.opened_handle()
        contention = PermissionError(errno.EACCES, "permission failure")
        with (
            mock.patch.object(workspace_fs.os, "name", "posix"),
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened),
            mock.patch.object(
                workspace_fs,
                "_prepare_quarantine_lock_handle",
                side_effect=contention,
            ),
            mock.patch.object(workspace_fs, "_lock_quarantine_handle") as acquire,
            mock.patch.object(workspace_fs, "_unlock_quarantine_handle") as release,
        ):
            with self.assertRaises(PermissionError) as raised:
                with workspace_fs.workspace_file_lock("unused", "approval.lock"):
                    self.fail("lock context yielded after failed preparation")

        self.assertIs(raised.exception, contention)
        acquire.assert_not_called()
        release.assert_not_called()

    def test_quarantine_parent_lock_uses_windows_contention_recovery(self):
        handle, opened = self.opened_handle()
        binding = types.SimpleNamespace(
            path=Path("unused"),
            trusted_path=Path("unused"),
            identity=(1, 2),
        )
        events = []
        prepare_calls = 0

        def prepare(actual_handle):
            nonlocal prepare_calls
            prepare_calls += 1
            if prepare_calls == 1:
                events.append("prepare-contended")
                raise PermissionError(errno.EACCES, "lock byte is already held")
            events.append("prepare-after-lock")

        handle.seek.side_effect = lambda offset: events.append(f"seek-{offset}")
        with (
            mock.patch.object(workspace_fs.os, "name", "nt"),
            mock.patch.object(workspace_fs, "_verify_workspace_tree_binding"),
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened),
            mock.patch.object(
                workspace_fs,
                "_prepare_quarantine_lock_handle",
                side_effect=prepare,
            ),
            mock.patch.object(
                workspace_fs,
                "_lock_quarantine_handle",
                side_effect=lambda actual: events.append("lock"),
            ),
            mock.patch.object(
                workspace_fs,
                "_unlock_quarantine_handle",
                side_effect=lambda actual: events.append("unlock"),
            ),
        ):
            with workspace_fs.quarantine_parent_lock(binding):
                events.append("yield")

        self.assertEqual(
            events,
            [
                "prepare-contended",
                "seek-0",
                "lock",
                "prepare-after-lock",
                "yield",
                "unlock",
            ],
        )


class NormalizeWorkspaceRelativeTests(unittest.TestCase):
    def test_preserves_normal_nested_path(self):
        self.assertEqual(normalize_workspace_relative("docs/a.txt"), "docs/a.txt")

    def test_rejects_invalid_or_ambiguous_paths(self):
        invalid_paths = (
            "",
            ".",
            "./a.txt",
            "docs/./a.txt",
            "..",
            "../a.txt",
            "docs/../a.txt",
            "/tmp/a.txt",
            "//server/share/a.txt",
            r"\\server\share\a.txt",
            "C:/a.txt",
            "C:a.txt",
            r"C:\a.txt",
            r"docs\a.txt",
            r"..\a.txt",
            "docs//a.txt",
            "docs/a.txt/",
            "docs/\x00a.txt",
        )

        for value in invalid_paths:
            with self.subTest(value=value):
                with self.assertRaises(WorkspacePathError) as raised:
                    normalize_workspace_relative(value)
                self.assertIn(
                    raised.exception.rule_family,
                    {"invalid_path", "path_escape"},
                )

    def test_rejects_non_string_values(self):
        for value in (None, 1, Path("docs/a.txt")):
            with self.subTest(value=value):
                with self.assertRaises(WorkspacePathError) as raised:
                    normalize_workspace_relative(value)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.rule_family, "invalid_path")

    def test_uses_stable_rule_families_for_escape_and_ambiguity(self):
        cases = {
            "/tmp/a.txt": "path_escape",
            r"\\server\share\a.txt": "path_escape",
            "C:/a.txt": "path_escape",
            r"C:\a.txt": "path_escape",
            r"docs\a.txt": "invalid_path",
            "./a.txt": "invalid_path",
            "../a.txt": "path_escape",
        }

        for value, family in cases.items():
            with self.subTest(value=value):
                with self.assertRaises(WorkspacePathError) as raised:
                    normalize_workspace_relative(value)
                self.assertEqual(raised.exception.rule_family, family)


class LinkLikeTests(unittest.TestCase):
    def test_detects_reparse_attribute_without_is_junction(self):
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

        class Python311PathLike:
            def is_symlink(self):
                return False

            def lstat(self):
                return types.SimpleNamespace(
                    st_mode=stat.S_IFREG,
                    st_file_attributes=reparse_flag,
                )

        with mock.patch.object(
            stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            reparse_flag,
            create=True,
        ):
            self.assertTrue(is_link_like(Python311PathLike()))  # type: ignore[arg-type]

    def test_uses_is_junction_when_available(self):
        path = mock.Mock()
        path.is_symlink.return_value = False
        path.is_junction.return_value = True
        path.lstat.return_value = types.SimpleNamespace(st_mode=stat.S_IFDIR)

        self.assertTrue(is_link_like(path))

    def test_regular_file_is_not_link_like(self):
        path = mock.Mock(spec=["is_symlink", "lstat"])
        path.is_symlink.return_value = False
        path.lstat.return_value = types.SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_file_attributes=0,
        )

        self.assertFalse(is_link_like(path))


class WorkspaceFileIOTests(unittest.TestCase):
    def test_append_workspace_text_creates_and_extends_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            append_workspace_text(root, "runs/latest/trace.jsonl", "first\n")
            append_workspace_text(root, "runs/latest/trace.jsonl", "second\n")

            self.assertEqual(
                read_workspace_text(root, "runs/latest/trace.jsonl"),
                "first\nsecond\n",
            )

    def test_append_workspace_text_rejects_link_without_changing_external_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "sentinel.txt"
            external.write_text("EXTERNAL_APPEND_SENTINEL", encoding="utf-8")
            self._symlink_or_skip(external, root / "trace.jsonl")

            with self.assertRaises(WorkspacePathError) as raised:
                append_workspace_text(root, "trace.jsonl", "attacker-controlled\n")

            self.assertIn(raised.exception.rule_family, {"linked_path", "reparse_point"})
            self.assertEqual(
                external.read_text(encoding="utf-8"),
                "EXTERNAL_APPEND_SENTINEL",
            )

    def test_update_mode_creates_without_truncating_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing.lock"
            existing.write_bytes(b"abc")

            with open_workspace_file(root, "existing.lock", "update", create=True) as handle:
                self.assertEqual(handle.read(), b"abc")
                handle.seek(0)
                handle.write(b"Z")
            with open_workspace_file(root, "created.lock", "update", create=True) as handle:
                handle.write(b"x")

            self.assertEqual(existing.read_bytes(), b"Zbc")
            self.assertEqual((root / "created.lock").read_bytes(), b"x")

    def _metadata(self, root, relative):
        self.assertTrue(hasattr(workspace_fs, "workspace_file_metadata"))
        return workspace_fs.workspace_file_metadata(root, relative)

    def _read_optional_text(self, root, relative, **kwargs):
        self.assertTrue(hasattr(workspace_fs, "read_optional_workspace_text"))
        return workspace_fs.read_optional_workspace_text(root, relative, **kwargs)

    def test_optional_text_read_returns_content_or_final_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trusted").mkdir()
            (root / "trusted" / "value.txt").write_text("hello", encoding="utf-8")

            self.assertEqual(
                self._read_optional_text(root, "trusted/value.txt"),
                "hello",
            )
            self.assertIsNone(
                self._read_optional_text(root, "trusted/missing.txt")
            )

    def test_optional_text_read_only_accepts_exact_final_missing_error(self):
        cases = (
            WorkspacePathError("linked", "linked_path", missing_path="value.txt"),
            WorkspacePathError("reparse", "reparse_point", missing_path="value.txt"),
            WorkspacePathError("ancestor missing", "path_race", missing_path="parent"),
            WorkspacePathError("opaque race", "path_race"),
        )
        for error in cases:
            with self.subTest(family=error.rule_family, missing_path=error.missing_path):
                with mock.patch.object(
                    workspace_fs,
                    "read_workspace_bytes",
                    side_effect=error,
                ):
                    with self.assertRaises(WorkspacePathError) as raised:
                        self._read_optional_text("unused", "value.txt")

                self.assertIs(raised.exception, error)

    def test_optional_text_read_missing_then_created_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "value.txt"
            error = WorkspacePathError(
                "missing at open",
                "path_race",
                missing_path="value.txt",
            )

            def create_after_missing(_root, _relative):
                target.write_text("created later", encoding="utf-8")
                raise error

            with mock.patch.object(
                workspace_fs,
                "read_workspace_bytes",
                side_effect=create_after_missing,
            ) as read:
                result = self._read_optional_text(root, "value.txt")

            self.assertIsNone(result)
            read.assert_called_once_with(root, "value.txt")
            self.assertEqual(target.read_text(encoding="utf-8"), "created later")

    def test_optional_text_read_does_not_scan_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "value.txt").write_text("content", encoding="utf-8")

            with mock.patch.object(
                workspace_fs,
                "scan_workspace_files",
                side_effect=AssertionError("optional read must not scan"),
            ) as scan:
                result = self._read_optional_text(root, "value.txt")

            self.assertEqual(result, "content")
            scan.assert_not_called()

    def test_optional_text_read_ignores_unrelated_link(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "value.txt").write_text("content", encoding="utf-8")
            outside_file = Path(outside) / "sentinel.txt"
            outside_file.write_text("external sentinel", encoding="utf-8")
            self._symlink_or_skip(outside_file, root / "unrelated.txt")

            self.assertEqual(self._read_optional_text(root, "value.txt"), "content")

    def test_writes_and_reads_nested_text_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            write_workspace_text(root, "nested/docs/a.txt", "hello")

            self.assertEqual(read_workspace_text(root, "nested/docs/a.txt"), "hello")
            self.assertEqual(read_workspace_bytes(root, "nested/docs/a.txt"), b"hello")

    def test_writes_binary_content_without_text_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            write_workspace_bytes(root, "assets/data.bin", b"\x00\xff\x10")

            self.assertEqual(read_workspace_bytes(root, "assets/data.bin"), b"\x00\xff\x10")

    def test_streams_binary_content_with_a_hard_read_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = io.BytesIO(b"streamed content")

            written = write_workspace_stream(
                root,
                "assets/data.bin",
                source,
                max_bytes=len(b"streamed content"),
                chunk_size=4,
            )

            self.assertEqual(written, len(b"streamed content"))
            self.assertEqual(read_workspace_bytes(root, "assets/data.bin"), b"streamed content")

    def test_stream_write_reads_only_one_byte_past_the_limit(self):
        class TrackingSource(io.BytesIO):
            def __init__(self, content):
                super().__init__(content)
                self.requested = []

            def read(self, size=-1):
                self.requested.append(size)
                return super().read(size)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = TrackingSource(b"abcdef")

            with self.assertRaises(WorkspacePathError) as raised:
                write_workspace_stream(root, "data.bin", source, max_bytes=4, chunk_size=3)

            self.assertEqual(raised.exception.rule_family, "size_limit")
            self.assertEqual(sum(source.requested), 5)

    def test_stream_write_retries_short_destination_writes(self):
        class ShortWriteHandle:
            def __init__(self):
                self.content = bytearray()

            def write(self, content):
                accepted = min(2, len(content))
                self.content.extend(content[:accepted])
                return accepted

        handle = ShortWriteHandle()
        opened = mock.MagicMock()
        opened.__enter__.return_value = handle
        opened.__exit__.return_value = None
        with mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened):
            written = write_workspace_stream(
                "unused",
                "data.bin",
                io.BytesIO(b"abcdef"),
                max_bytes=6,
            )

        self.assertEqual(written, 6)
        self.assertEqual(bytes(handle.content), b"abcdef")

    def test_ensure_workspace_directory_creates_a_nested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            workspace_fs.ensure_workspace_directory(root, "assets/images")

            self.assertTrue((root / "assets" / "images").is_dir())

    def test_ensure_workspace_directory_rejects_reparse_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ancestor = root / "ancestor"
            ancestor.mkdir()
            real_is_link_like = workspace_fs.is_link_like

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=lambda path: Path(path) == ancestor or real_is_link_like(path),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    workspace_fs.ensure_workspace_directory(root, "ancestor/nested")

            self.assertEqual(raised.exception.rule_family, "reparse_point")
            self.assertFalse((ancestor / "nested").exists())

    def test_ensure_workspace_directory_rejects_root_identity_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            displaced = base / "displaced"
            replacement = base / "replacement"
            root.mkdir()
            replacement.mkdir()
            sentinel = replacement / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            real_ensure = workspace_fs._ensure_workspace_directory

            def replace_before_create(path, relative, *args, **kwargs):
                root.rename(displaced)
                replacement.rename(root)
                return real_ensure(path, relative, *args, **kwargs)

            with mock.patch.object(
                workspace_fs,
                "_ensure_workspace_directory",
                side_effect=replace_before_create,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    workspace_fs.ensure_workspace_directory(root, "nested")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual((root / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
            self.assertFalse((root / "nested").exists())

    def test_ensure_workspace_directory_rejects_ancestor_identity_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            ancestor = root / "ancestor"
            displaced = base / "displaced-ancestor"
            replacement = base / "replacement"
            ancestor.mkdir(parents=True)
            replacement.mkdir()
            sentinel = replacement / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")

            if os.name == "nt":
                real_lstat = Path.lstat
                replaced = False

                def replace_after_lstat(path):
                    nonlocal replaced
                    result = real_lstat(path)
                    if Path(path) == ancestor and not replaced:
                        ancestor.rename(displaced)
                        replacement.rename(ancestor)
                        replaced = True
                    return result

                patcher = mock.patch.object(Path, "lstat", autospec=True, side_effect=replace_after_lstat)
            else:
                real_stat = os.stat
                replaced = False

                def replace_after_stat(path, *args, **kwargs):
                    nonlocal replaced
                    result = real_stat(path, *args, **kwargs)
                    if path == "ancestor" and kwargs.get("dir_fd") is not None and not replaced:
                        ancestor.rename(displaced)
                        replacement.rename(ancestor)
                        replaced = True
                    return result

                patcher = mock.patch.object(os, "stat", side_effect=replace_after_stat)

            with patcher:
                with self.assertRaises(WorkspacePathError) as raised:
                    workspace_fs.ensure_workspace_directory(root, "ancestor/nested")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual((ancestor / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
            self.assertFalse((ancestor / "nested").exists())

    @unittest.skipUnless(os.name == "nt", "Windows directory lock lifetime")
    def test_windows_ensure_holds_root_and_ancestor_locks_through_final_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            final = first / "final"
            active = []
            entered = []
            active_at_final_validation = []
            real_resolve = Path.resolve

            @contextmanager
            def tracking_lock(path, expected, expected_identity, **_kwargs):
                path = Path(path)
                entered.append((path, Path(expected), expected_identity, tuple(active)))
                active.append(path)
                try:
                    yield expected_identity
                finally:
                    active.remove(path)

            def observe_final_validation(path, strict=False):
                if Path(path) == final:
                    active_at_final_validation.append(tuple(active))
                return real_resolve(path, strict=strict)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_open_windows_directory_lock",
                    side_effect=tracking_lock,
                ),
                mock.patch.object(
                    Path,
                    "resolve",
                    autospec=True,
                    side_effect=observe_final_validation,
                ),
            ):
                workspace_fs.ensure_workspace_directory(root, "first/final")

            self.assertEqual([entry[0] for entry in entered], [root, first, final])
            self.assertEqual([entry[1] for entry in entered], [root, first, final])
            self.assertEqual(entered[0][2], workspace_fs._stat_identity(root.lstat()))
            self.assertEqual(
                [entry[3] for entry in entered],
                [(), (root,), (root, first)],
            )
            self.assertEqual(active_at_final_validation, [(root, first, final)])

    @unittest.skipUnless(os.name == "nt", "Windows directory lock replacement prevention")
    def test_windows_ensure_prevents_ancestor_replacement_before_next_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            ancestor = root / "ancestor"
            displaced = base / "displaced-ancestor"
            replacement = base / "replacement"
            ancestor.mkdir(parents=True)
            replacement.mkdir()
            sentinel = replacement / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            real_lstat = Path.lstat
            active = []

            @contextmanager
            def tracking_lock(path, _expected, expected_identity, **_kwargs):
                path = Path(path)
                active.append(path)
                try:
                    yield expected_identity
                finally:
                    active.remove(path)

            def attempt_replacement_before_next_level(path):
                if Path(path) == ancestor / "nested":
                    if ancestor in active:
                        raise WorkspacePathError(
                            "workspace ancestor replacement was blocked",
                            "path_race",
                        )
                    ancestor.rename(displaced)
                    replacement.rename(ancestor)
                return real_lstat(path)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_open_windows_directory_lock",
                    side_effect=tracking_lock,
                ),
                mock.patch.object(
                    Path,
                    "lstat",
                    autospec=True,
                    side_effect=attempt_replacement_before_next_level,
                ),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    workspace_fs.ensure_workspace_directory(root, "ancestor/nested")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
            self.assertFalse((replacement / "nested").exists())
            self.assertFalse((ancestor / "nested").exists())

    @unittest.skipUnless(os.name == "nt", "Windows implicit parent lock lifetime")
    def test_windows_stream_write_holds_parent_locks_through_final_fd_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            nested = first / "nested"
            active = []
            entered = []
            active_at_final_validation = []
            real_validate = workspace_fs._validate_windows_final_path

            @contextmanager
            def tracking_lock(path, expected, expected_identity, **_kwargs):
                path = Path(path)
                entered.append((path, Path(expected), tuple(active)))
                active.append(path)
                try:
                    yield expected_identity
                finally:
                    active.remove(path)

            def observe_final_validation(descriptor, trusted_root, parts):
                active_at_final_validation.append(tuple(active))
                return real_validate(descriptor, trusted_root, parts)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_open_windows_directory_lock",
                    side_effect=tracking_lock,
                ),
                mock.patch.object(
                    workspace_fs,
                    "_validate_windows_final_path",
                    side_effect=observe_final_validation,
                ),
            ):
                write_workspace_stream(
                    root,
                    "first/nested/data.bin",
                    io.BytesIO(b"content"),
                    max_bytes=7,
                )

            self.assertEqual([entry[0] for entry in entered], [root, first, nested])
            self.assertEqual([entry[1] for entry in entered], [root, first, nested])
            self.assertEqual([entry[2] for entry in entered], [(), (root,), (root, first)])
            self.assertEqual(active_at_final_validation, [(root, first, nested)])

    @unittest.skipUnless(os.name == "nt", "Windows implicit parent replacement prevention")
    def test_windows_stream_write_rejects_ancestor_replacement_before_implicit_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "workspace"
            ancestor = root / "ancestor"
            displaced = base / "displaced-ancestor"
            replacement = base / "replacement"
            ancestor.mkdir(parents=True)
            replacement.mkdir()
            sentinel = replacement / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            active = []
            real_lstat = Path.lstat
            attempted = False

            @contextmanager
            def tracking_lock(path, _expected, expected_identity, **_kwargs):
                path = Path(path)
                active.append(path)
                try:
                    yield expected_identity
                finally:
                    active.remove(path)

            def attempt_replacement(path):
                nonlocal attempted
                if Path(path) == ancestor / "nested" and not attempted:
                    attempted = True
                    if ancestor in active:
                        raise WorkspacePathError(
                            "workspace ancestor replacement was blocked",
                            "path_race",
                        )
                    ancestor.rename(displaced)
                    replacement.rename(ancestor)
                return real_lstat(path)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_open_windows_directory_lock",
                    side_effect=tracking_lock,
                ),
                mock.patch.object(
                    Path,
                    "lstat",
                    autospec=True,
                    side_effect=attempt_replacement,
                ),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    write_workspace_stream(
                        root,
                        "ancestor/nested/data.bin",
                        io.BytesIO(b"content"),
                        max_bytes=7,
                    )

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
            self.assertFalse((replacement / "nested").exists())
            self.assertFalse((ancestor / "nested").exists())
            self.assertFalse((ancestor / "data.bin").exists())

    def test_workspace_file_state_hashes_existing_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_bytes(b"content")

            existing = workspace_file_state(root, "a.txt")
            missing = workspace_file_state(root, "missing.txt")

            self.assertTrue(existing.exists)
            self.assertEqual(existing.sha256, hashlib.sha256(b"content").hexdigest())
            self.assertFalse(missing.exists)
            self.assertIsNone(missing.sha256)

    def test_file_metadata_uses_fstat_on_verified_handle_without_reading_content(self):
        handle = mock.Mock()
        handle.fileno.return_value = 41
        opened = mock.MagicMock()
        opened.__enter__.return_value = handle
        opened.__exit__.return_value = None

        with (
            mock.patch.object(workspace_fs, "open_workspace_file", return_value=opened) as safe_open,
            mock.patch.object(
                workspace_fs.os,
                "fstat",
                return_value=types.SimpleNamespace(st_size=987654321),
            ) as fstat,
        ):
            metadata = self._metadata("unused", "artifacts/result.zip")

        self.assertEqual(metadata.size_bytes, 987654321)
        safe_open.assert_called_once_with("unused", "artifacts/result.zip", "read")
        fstat.assert_called_once_with(41)
        handle.read.assert_not_called()

    def test_file_metadata_preserves_missing_link_and_ancestor_race_errors(self):
        errors = (
            WorkspacePathError(
                "missing",
                "path_race",
                missing_path="artifacts/result.zip",
            ),
            WorkspacePathError("linked", "linked_path"),
            WorkspacePathError("ancestor changed", "path_race", missing_path="artifacts"),
        )
        for error in errors:
            with self.subTest(family=error.rule_family, missing_path=error.missing_path):
                with mock.patch.object(
                    workspace_fs,
                    "open_workspace_file",
                    side_effect=error,
                ):
                    with self.assertRaises(WorkspacePathError) as raised:
                        self._metadata("unused", "artifacts/result.zip")

                self.assertIs(raised.exception, error)

    def test_open_workspace_file_closes_handle_after_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_bytes(b"content")

            with open_workspace_file(root, "a.txt", "read") as handle:
                opened = handle
                self.assertEqual(handle.read(), b"content")
                self.assertFalse(handle.closed)

            self.assertTrue(opened.closed)

    def test_rejects_directory_as_unsafe_file_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "folder").mkdir()

            with self.assertRaises(WorkspacePathError) as raised:
                read_workspace_bytes(root, "folder")

            self.assertEqual(raised.exception.rule_family, "unsafe_file_type")

    def test_open_permission_error_uses_stable_path_race_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("content", encoding="utf-8")

            with mock.patch.object(
                workspace_fs if os.name == "nt" else os,
                "_open_windows_fd" if os.name == "nt" else "open",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    read_workspace_bytes(root, "a.txt")

            self.assertEqual(raised.exception.rule_family, "path_race")

    def test_read_and_write_io_errors_use_stable_path_race_family(self):
        class FailingHandle:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                raise OSError("read failed")

            def write(self, _content):
                raise OSError("write failed")

        operations = (
            lambda: read_workspace_bytes("unused", "a.txt"),
            lambda: write_workspace_bytes("unused", "a.txt", b"content"),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with mock.patch.object(
                    workspace_fs,
                    "open_workspace_file",
                    return_value=FailingHandle(),
                ):
                    with self.assertRaises(WorkspacePathError) as raised:
                        operation()

                self.assertEqual(raised.exception.rule_family, "path_race")

    def test_missing_read_and_write_do_not_leak_file_not_found_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            existing_root = base / "existing"
            existing_root.mkdir()
            operations = (
                lambda: read_workspace_bytes(existing_root, "missing.txt"),
                lambda: write_workspace_bytes(base / "missing-root", "a.txt", b"content"),
            )

            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(WorkspacePathError) as raised:
                        operation()
                    self.assertEqual(raised.exception.rule_family, "path_race")

            self.assertFalse(workspace_file_state(existing_root, "missing.txt").exists)

    def test_missing_final_error_identifies_workspace_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trusted").mkdir()

            with self.assertRaises(WorkspacePathError) as raised:
                read_workspace_bytes(root, "trusted/missing.txt")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(raised.exception.missing_path, "trusted/missing.txt")

    def test_file_state_fails_closed_when_parent_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(WorkspacePathError) as raised:
                workspace_file_state(root, "missing-parent/value.txt")

            self.assertEqual(raised.exception.rule_family, "path_race")

    def test_rejects_mocked_reparse_parent_before_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            linked = root / "linked"
            linked.mkdir()
            real_is_link_like = workspace_fs.is_link_like

            def mocked_is_link_like(path):
                return Path(path) == linked or real_is_link_like(path)

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=mocked_is_link_like,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    read_workspace_bytes(root, "linked/missing.txt")

            self.assertEqual(raised.exception.rule_family, "reparse_point")

    def test_rejects_mocked_symlink_with_linked_path_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            linked = root / "linked.txt"
            linked.write_text("placeholder", encoding="utf-8")
            real_is_link_like = workspace_fs.is_link_like
            real_is_symlink = Path.is_symlink

            def mocked_is_symlink(path):
                return path == linked or real_is_symlink(path)

            with (
                mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=mocked_is_symlink,
                ),
                mock.patch.object(
                    workspace_fs,
                    "is_link_like",
                    side_effect=lambda path: Path(path) == linked or real_is_link_like(path),
                ),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    read_workspace_bytes(root, linked.name)

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_rejects_internal_and_external_file_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            inside_file = root / "inside.txt"
            outside_file = Path(outside) / "outside.txt"
            inside_file.write_text("inside", encoding="utf-8")
            outside_file.write_text("sentinel", encoding="utf-8")
            internal_link = root / "internal-link.txt"
            external_link = root / "external-link.txt"
            self._symlink_or_skip(inside_file, internal_link)
            self._symlink_or_skip(outside_file, external_link)

            for relative in (internal_link.name, external_link.name):
                with self.subTest(relative=relative):
                    with self.assertRaises(WorkspacePathError) as raised:
                        read_workspace_text(root, relative)
                    self.assertEqual(raised.exception.rule_family, "linked_path")

            with self.assertRaises(WorkspacePathError) as raised:
                write_workspace_text(root, external_link.name, "changed")
            self.assertEqual(raised.exception.rule_family, "linked_path")
            self.assertEqual(outside_file.read_text(encoding="utf-8"), "sentinel")

    @unittest.skipUnless(os.name == "nt", "Windows final-handle validation")
    def test_rejects_opened_file_outside_root_and_closes_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            expected = root / "ancestor" / "value.txt"
            expected.parent.mkdir()
            expected.write_text("inside", encoding="utf-8")
            sentinel = Path(outside) / "value.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            opened_descriptors = []

            def replace_during_open(_path, flags, mode=0o666):
                descriptor = os.open(sentinel, flags, mode)
                opened_descriptors.append(descriptor)
                return descriptor

            with mock.patch.object(
                workspace_fs,
                "_open_windows_fd",
                side_effect=replace_during_open,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    read_workspace_text(root, "ancestor/value.txt")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(len(opened_descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(opened_descriptors[0])

    @unittest.skipUnless(os.name == "nt", "Windows final-handle validation")
    def test_write_does_not_change_content_before_final_handle_validation(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            expected = root / "ancestor" / "value.txt"
            expected.parent.mkdir()
            expected.write_text("inside", encoding="utf-8")
            sentinel = Path(outside) / "value.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")

            def replace_during_open(_path, flags, mode=0o666):
                return os.open(sentinel, flags, mode)

            with mock.patch.object(
                workspace_fs,
                "_open_windows_fd",
                side_effect=replace_during_open,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    write_workspace_text(root, "ancestor/value.txt", "changed")

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    @unittest.skipUnless(os.name == "nt", "Windows capability check")
    def test_windows_missing_final_path_capability_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("inside", encoding="utf-8")

            with mock.patch.object(workspace_fs, "_windows_final_path", None):
                with self.assertRaises(WorkspacePathError) as raised:
                    read_workspace_text(root, "a.txt")

            self.assertEqual(raised.exception.rule_family, "path_race")

    @staticmethod
    def _symlink_or_skip(target: Path, link: Path, *, is_directory: bool = False):
        try:
            os.symlink(target, link, target_is_directory=is_directory)
        except (NotImplementedError, OSError) as exc:
            raise unittest.SkipTest(f"symlinks unavailable: {exc}") from exc


class WorkspaceScanAndCopyTests(unittest.TestCase):
    def test_bound_tree_rename_preserves_tree_and_parent_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = parent / "workspace"
            destination = parent / "workspace.backup-11"
            source.mkdir()
            (source / "index.html").write_text("v1", encoding="utf-8")

            binding = workspace_fs.bind_workspace_tree(source)
            moved = workspace_fs.rename_workspace_tree_noreplace(binding, destination)

            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "index.html").read_text(encoding="utf-8"),
                "v1",
            )
            self.assertEqual(moved.path, destination)
            self.assertEqual(moved.identity, binding.identity)
            self.assertEqual(moved.parent_identity, binding.parent_identity)

    def test_bound_tree_rename_does_not_overwrite_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = parent / "workspace"
            destination = parent / "workspace.backup-11"
            source.mkdir()
            destination.mkdir()
            (source / "index.html").write_text("v1", encoding="utf-8")
            sentinel = destination / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            binding = workspace_fs.bind_workspace_tree(source)

            with self.assertRaises(WorkspacePathError):
                workspace_fs.rename_workspace_tree_noreplace(binding, destination)

            self.assertEqual((source / "index.html").read_text(encoding="utf-8"), "v1")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_bound_tree_rename_quarantines_post_rename_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = parent / "workspace.next-11-token"
            destination = parent / "workspace"
            source.mkdir()
            sentinel = source / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            binding = workspace_fs.bind_workspace_tree(source)
            mismatched = workspace_fs.WorkspaceTreeBinding(
                path=destination,
                trusted_path=destination,
                identity=(binding.identity[0], binding.identity[1] + 1),
                parent_path=binding.parent_path,
                trusted_parent=binding.trusted_parent,
                parent_identity=binding.parent_identity,
            )

            real_bind = workspace_fs.bind_workspace_tree

            def bind_mismatched_destination(path, **kwargs):
                if Path(path) == destination:
                    return mismatched
                return real_bind(path, **kwargs)

            with mock.patch.object(
                workspace_fs,
                "bind_workspace_tree",
                side_effect=bind_mismatched_destination,
            ):
                with self.assertRaises(workspace_fs.WorkspaceTreeRenameError) as raised:
                    workspace_fs.rename_workspace_tree_noreplace(binding, destination)

            self.assertTrue(raised.exception.renamed)
            self.assertTrue(raised.exception.quarantined)
            self.assertFalse(destination.exists())
            quarantines = list(parent.glob(".workspace.specgate-quarantine-*"))
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(
                (quarantines[0] / "sentinel.txt").read_text(encoding="utf-8"),
                "external sentinel",
            )

    def test_bound_tree_rename_retains_unknown_tree_when_quarantine_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = parent / "workspace.next-11-token"
            destination = parent / "workspace"
            source.mkdir()
            sentinel = source / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            binding = workspace_fs.bind_workspace_tree(source)
            mismatched = workspace_fs.WorkspaceTreeBinding(
                path=destination,
                trusted_path=destination,
                identity=(binding.identity[0], binding.identity[1] + 1),
                parent_path=binding.parent_path,
                trusted_parent=binding.trusted_parent,
                parent_identity=binding.parent_identity,
            )
            real_rename = workspace_fs._platform_rename_noreplace
            real_bind = workspace_fs.bind_workspace_tree
            calls = 0

            def bind_mismatched_destination(path, **kwargs):
                if Path(path) == destination:
                    return mismatched
                return real_bind(path, **kwargs)

            def fail_quarantine(source_path, destination_path):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("quarantine denied")
                return real_rename(source_path, destination_path)

            with (
                mock.patch.object(
                    workspace_fs,
                    "bind_workspace_tree",
                    side_effect=bind_mismatched_destination,
                ),
                mock.patch.object(
                    workspace_fs,
                    "_platform_rename_noreplace",
                    side_effect=fail_quarantine,
                ),
            ):
                with self.assertRaises(workspace_fs.WorkspaceTreeRenameError) as raised:
                    workspace_fs.rename_workspace_tree_noreplace(binding, destination)

            self.assertTrue(raised.exception.renamed)
            self.assertFalse(raised.exception.quarantined)
            self.assertEqual(
                (destination / "sentinel.txt").read_text(encoding="utf-8"),
                "external sentinel",
            )
            self.assertEqual(list(parent.glob(".workspace.specgate-quarantine-*")), [])

    @unittest.skipUnless(os.name == "nt", "Windows root identity validation")
    def test_windows_stat_and_handle_identity_match_for_same_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = workspace_fs._stat_identity(root.lstat())

            with workspace_fs._open_windows_directory_lock(
                root,
                root.resolve(),
                expected,
            ) as actual:
                self.assertEqual(actual, expected)

    @unittest.skipUnless(os.name == "nt", "Windows concurrent handle inspection")
    def test_windows_directory_lock_handle_inspection_is_thread_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = (Path(tmp) / "first", Path(tmp) / "second")
            for root in roots:
                root.mkdir()

            real_byref = ctypes.byref

            def inspect(root):
                expected_identity = workspace_fs._stat_identity(root.lstat())
                with workspace_fs._open_windows_directory_lock(
                    root,
                    root.resolve(),
                    expected_identity,
                ) as actual:
                    self.assertEqual(actual, expected_identity)

            for _ in range(20):
                barrier = threading.Barrier(2)

                def synchronize_handle_information(value, *args):
                    field_names = {
                        field[0] for field in getattr(type(value), "_fields_", ())
                    }
                    if {"file_attributes", "file_index_high"} <= field_names:
                        barrier.wait(timeout=5)
                    return real_byref(value, *args)

                with mock.patch.object(
                    ctypes,
                    "byref",
                    side_effect=synchronize_handle_information,
                ):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = [executor.submit(inspect, root) for root in roots]
                        for future in futures:
                            future.result(timeout=10)

    @unittest.skipUnless(os.name == "nt", "Windows directory handle sharing policy")
    def test_windows_directory_lock_fails_closed_without_delete_sharing_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_handle = ctypes.c_void_p(-1).value

            with mock.patch.object(
                ctypes.windll.kernel32,
                "CreateFileW",
                return_value=invalid_handle,
            ) as create_file:
                with self.assertRaises(WorkspacePathError) as raised:
                    with workspace_fs._open_windows_directory_lock(
                        root,
                        root.resolve(),
                        workspace_fs._stat_identity(root.lstat()),
                    ):
                        pass

            self.assertEqual(raised.exception.rule_family, "path_race")
            create_file.assert_called_once()
            self.assertEqual(create_file.call_args.args[1], 0x00000080)
            share_flags = create_file.call_args.args[2]
            self.assertEqual(share_flags & 0x00000004, 0)

    @unittest.skipUnless(os.name == "nt", "Windows anchor sharing policy")
    def test_windows_volume_root_lock_uses_delete_sharing_once(self):
        root = Path(Path.cwd().anchor)
        invalid_handle = ctypes.c_void_p(-1).value

        with mock.patch.object(
            ctypes.windll.kernel32,
            "CreateFileW",
            return_value=invalid_handle,
        ) as create_file:
            with self.assertRaises(WorkspacePathError) as raised:
                with workspace_fs._open_windows_directory_lock(
                    root,
                    root,
                    workspace_fs._stat_identity(root.lstat()),
                ):
                    pass

        self.assertEqual(raised.exception.rule_family, "path_race")
        create_file.assert_called_once()
        self.assertEqual(create_file.call_args.args[1], 0x00000080)
        share_flags = create_file.call_args.args[2]
        self.assertEqual(share_flags, 0x00000001 | 0x00000002 | 0x00000004)

    @unittest.skipUnless(os.name == "nt", "Windows pseudo-anchor sharing policy")
    def test_windows_pseudo_anchors_do_not_get_delete_sharing(self):
        drive = Path.cwd().drive
        cases = (
            Path(f"{drive}relative"),
            Path(Path.cwd().anchor) / "not-a-volume-root",
        )
        invalid_handle = ctypes.c_void_p(-1).value

        for path in cases:
            with self.subTest(path=str(path)), mock.patch.object(
                ctypes.windll.kernel32,
                "CreateFileW",
                return_value=invalid_handle,
            ) as create_file:
                with self.assertRaises(WorkspacePathError) as raised:
                    with workspace_fs._open_windows_directory_lock(
                        path,
                        path,
                        (1, 1),
                    ):
                        pass

            self.assertEqual(raised.exception.rule_family, "path_race")
            create_file.assert_called_once()
            share_flags = create_file.call_args.args[2]
            self.assertEqual(share_flags & 0x00000004, 0)

    @unittest.skipUnless(os.name == "nt", "Windows sharing failure side effects")
    def test_windows_directory_lock_sharing_failure_creates_no_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            sentinel = Path(outside) / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            invalid_handle = ctypes.c_void_p(-1).value

            with mock.patch.object(
                ctypes.windll.kernel32,
                "CreateFileW",
                return_value=invalid_handle,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    write_workspace_stream(
                        root,
                        "nested/data.bin",
                        io.BytesIO(b"content"),
                        max_bytes=7,
                    )

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse((root / "nested").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_publishes_workspace_bytes_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            publish_workspace_bytes(root, "publication-manifest.json", b'{"run_id": 11}')

            self.assertEqual(
                (root / "publication-manifest.json").read_bytes(),
                b'{"run_id": 11}',
            )
            self.assertEqual(
                [path.name for path in root.iterdir()],
                ["publication-manifest.json"],
            )

    def test_workspace_bytes_rejects_root_replaced_at_rename_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "audit"
            replacement = base / "replacement-audit"
            displaced = base / "displaced-audit"
            root.mkdir()
            replacement.mkdir()
            real_rename = getattr(workspace_fs, "_rename_bound_workspace_noreplace", None)
            staging_name = None

            def replace_root_before_rename(binding, source_relative, target_relative):
                nonlocal staging_name
                staging_name = source_relative
                root.rename(displaced)
                replacement.rename(root)
                write_workspace_text(root, source_relative, "EXTERNAL_SENTINEL")
                if real_rename is None:
                    raise AssertionError("bound rename helper was not called")
                return real_rename(binding, source_relative, target_relative)

            with mock.patch.object(
                workspace_fs,
                "_rename_bound_workspace_noreplace",
                create=True,
                side_effect=replace_root_before_rename,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    publish_workspace_bytes(
                        root,
                        "publication-manifest.json",
                        b'{"run_id": 11}',
                    )

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertIsNotNone(staging_name)
            self.assertFalse((root / "publication-manifest.json").exists())
            self.assertEqual(
                read_workspace_text(root, staging_name),
                "EXTERNAL_SENTINEL",
            )

    def test_publishes_composed_workspace_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "run"
            (source / "nested").mkdir(parents=True)
            (source / "nested" / "data.txt").write_text("data", encoding="utf-8")

            publish_workspace_snapshot(
                destination,
                source_trees=((source, "workspace"),),
                directories=("audit", "artifacts"),
                files=(("owner.json", b'{"run_id": 11}'),),
            )

            self.assertEqual(
                (destination / "workspace" / "nested" / "data.txt").read_text(
                    encoding="utf-8"
                ),
                "data",
            )
            self.assertTrue((destination / "audit").is_dir())
            self.assertTrue((destination / "artifacts").is_dir())
            self.assertEqual((destination / "owner.json").read_bytes(), b'{"run_id": 11}')

    def test_snapshot_rejects_linked_destination_parent_without_writing_external_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            external = base / "external"
            external.mkdir()
            sentinel = external / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            runs = base / "runs"
            try:
                os.symlink(external, runs, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")

            with self.assertRaises(WorkspacePathError) as raised:
                publish_workspace_snapshot(
                    runs / "11",
                    files=(("owner.json", b'{"run_id": 11}'),),
                )

            self.assertIn(raised.exception.rule_family, {"linked_path", "reparse_point"})
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
            self.assertFalse((external / "11").exists())
            self.assertEqual(sorted(path.name for path in external.iterdir()), ["sentinel.txt"])

    def test_snapshot_rejects_mocked_reparse_destination_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runs = base / "runs"
            runs.mkdir()
            destination = runs / "11"
            real_is_link_like = workspace_fs.is_link_like

            def mark_runs_reparse(path):
                if Path(path) == runs:
                    return True
                return real_is_link_like(path)

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=mark_runs_reparse,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    publish_workspace_snapshot(
                        destination,
                        files=(("owner.json", b'{"run_id": 11}'),),
                    )

            self.assertEqual(raised.exception.rule_family, "reparse_point")
            self.assertFalse(destination.exists())
            self.assertEqual(list(runs.iterdir()), [])

    def test_snapshot_rejects_destination_parent_replaced_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runs = base / "runs"
            replacement_parent = base / "replacement-runs"
            displaced_parent = base / "displaced-runs"
            runs.mkdir()
            replacement_parent.mkdir()
            destination = runs / "11"
            real_write = getattr(workspace_fs, "_write_owned_workspace_bytes", None)
            replaced = False

            def replace_parent_before_write(ownership, relative, content):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    staging_name = ownership.path.name
                    runs.rename(displaced_parent)
                    replacement_parent.rename(runs)
                    replacement_staging = runs / staging_name
                    replacement_staging.mkdir()
                    (replacement_staging / "sentinel.txt").write_text(
                        "external sentinel",
                        encoding="utf-8",
                    )
                if real_write is None:
                    raise AssertionError("owned writer was not called")
                return real_write(ownership, relative, content)

            with mock.patch.object(
                workspace_fs,
                "_write_owned_workspace_bytes",
                create=True,
                side_effect=replace_parent_before_write,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    publish_workspace_snapshot(
                        destination,
                        files=(("owner.json", b'{"run_id": 11}'),),
                    )

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertTrue(replaced)
            self.assertFalse(destination.exists())
            replacement_staging = next(runs.glob(".11.specgate-copy-*"))
            self.assertEqual(
                sorted(path.name for path in replacement_staging.iterdir()),
                ["sentinel.txt"],
            )
            self.assertEqual(
                (replacement_staging / "sentinel.txt").read_text(encoding="utf-8"),
                "external sentinel",
            )

    def test_snapshot_rejects_source_root_replaced_after_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            replacement = base / "replacement-source"
            displaced = base / "displaced-source"
            destination = base / "run"
            source.mkdir()
            replacement.mkdir()
            (source / "index.html").write_text("trusted", encoding="utf-8")
            (replacement / "index.html").write_text(
                "EXTERNAL_CONTENT_SENTINEL",
                encoding="utf-8",
            )
            real_read = getattr(workspace_fs, "_read_bound_workspace_bytes", None)
            replaced = False

            def replace_source_before_read(binding, relative):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    source.rename(displaced)
                    replacement.rename(source)
                if real_read is None:
                    raise AssertionError("bound reader was not called")
                return real_read(binding, relative)

            with mock.patch.object(
                workspace_fs,
                "_read_bound_workspace_bytes",
                create=True,
                side_effect=replace_source_before_read,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    publish_workspace_snapshot(
                        destination,
                        source_trees=((source, "workspace"),),
                    )

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertTrue(replaced)
            self.assertFalse(destination.exists())
            self.assertEqual(
                (source / "index.html").read_text(encoding="utf-8"),
                "EXTERNAL_CONTENT_SENTINEL",
            )
            staged_content = "".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for staging in base.glob(".run.specgate-copy-*")
                for path in staging.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("EXTERNAL_CONTENT_SENTINEL", staged_content)

    def test_tolerant_scan_prunes_excluded_directory_without_enumerating_children(self):
        self.assertTrue(hasattr(workspace_fs, "scan_workspace_files"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "safe.txt").write_text("safe", encoding="utf-8")
            excluded = root / "eval-runs"
            excluded.mkdir()
            (excluded / "external-name.txt").write_text("sentinel", encoding="utf-8")
            real_scandir = os.scandir

            def reject_excluded_scan(path):
                if not isinstance(path, int) and Path(path) == excluded:
                    raise AssertionError("excluded directory was enumerated")
                return real_scandir(path)

            with mock.patch.object(os, "scandir", side_effect=reject_excluded_scan):
                result = workspace_fs.scan_workspace_files(
                    root,
                    excluded_dirs={"eval-runs"},
                )

            self.assertEqual(result.files, ["safe.txt"])
            self.assertNotIn("external-name.txt", str(result))

    @unittest.skipUnless(os.name == "nt", "Windows tolerant directory identity validation")
    def test_tolerant_scan_rejects_replaced_directory_without_external_names(self):
        self.assertTrue(hasattr(workspace_fs, "scan_workspace_files"))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "safe.txt").write_text("safe", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "inside.txt").write_text("inside", encoding="utf-8")
            external = Path(outside)
            (external / "EXTERNAL_NAME_SENTINEL.txt").write_text("sentinel", encoding="utf-8")
            root_stat = root.stat()
            outside_stat = external.stat()
            real_scandir = os.scandir

            def redirect_replaced_directory(path):
                if not isinstance(path, int) and Path(path) == nested:
                    return real_scandir(external)
                return real_scandir(path)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_windows_handle_identity",
                    side_effect=(
                        (root_stat.st_dev, root_stat.st_ino),
                        (root_stat.st_dev, root_stat.st_ino),
                        (outside_stat.st_dev, outside_stat.st_ino),
                    ),
                ),
                mock.patch.object(os, "scandir", side_effect=redirect_replaced_directory),
            ):
                result = workspace_fs.scan_workspace_files(root)

            self.assertEqual(result.files, ["safe.txt"])
            self.assertTrue(
                any(
                    rejection.path == "nested" and rejection.rule_family == "path_race"
                    for rejection in result.rejections
                )
            )
            self.assertNotIn("EXTERNAL_NAME_SENTINEL", str(result))

    @unittest.skipIf(os.name == "nt", "POSIX tolerant directory descriptor validation")
    def test_tolerant_scan_rejects_directory_swap_without_external_names(self):
        self.assertTrue(hasattr(workspace_fs, "scan_workspace_files"))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "safe.txt").write_text("safe", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "inside.txt").write_text("inside", encoding="utf-8")
            saved = root / "saved"
            external = Path(outside)
            (external / "EXTERNAL_NAME_SENTINEL.txt").write_text("sentinel", encoding="utf-8")
            real_open = os.open
            replaced = False

            def replace_then_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal replaced
                if path == "nested" and dir_fd is not None and not replaced:
                    nested.rename(saved)
                    os.symlink(external, nested, target_is_directory=True)
                    replaced = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(os, "open", side_effect=replace_then_open):
                result = workspace_fs.scan_workspace_files(root)

            self.assertEqual(result.files, ["safe.txt"])
            self.assertTrue(
                any(rejection.path == "nested" for rejection in result.rejections)
            )
            self.assertNotIn("EXTERNAL_NAME_SENTINEL", str(result))

    def test_iterates_normal_nested_files_in_stable_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "z.txt").write_text("z", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "b.txt").write_text("b", encoding="utf-8")
            (root / "docs" / "a.txt").write_text("a", encoding="utf-8")
            (root / "empty").mkdir()

            self.assertEqual(
                list(iter_workspace_files(root)),
                ["docs/a.txt", "docs/b.txt", "z.txt"],
            )

    def test_copies_normal_files_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            (source / "docs").mkdir(parents=True)
            (source / "empty").mkdir()
            (source / "docs" / "a.txt").write_text("hello", encoding="utf-8")
            (source / "data.bin").write_bytes(b"\x00\xff")

            copy_workspace_tree(source, destination)

            self.assertEqual((destination / "docs" / "a.txt").read_text(encoding="utf-8"), "hello")
            self.assertEqual((destination / "data.bin").read_bytes(), b"\x00\xff")
            self.assertTrue((destination / "empty").is_dir())

    def test_copy_failure_removes_destination_and_partial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (source / "b.txt").write_text("b", encoding="utf-8")
            real_write = workspace_fs.write_workspace_bytes
            writes = 0

            def fail_second_write(root, relative, content):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("copy interrupted")
                real_write(root, relative, content)

            with mock.patch.object(
                workspace_fs,
                "write_workspace_bytes",
                side_effect=fail_second_write,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(destination.exists())

    def test_copy_cleanup_does_not_delete_replacement_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement = base / "replacement"
            displaced = base / "displaced-copy"
            source.mkdir()
            replacement.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (replacement / "sentinel.txt").write_text("existing sentinel", encoding="utf-8")
            real_write = workspace_fs.write_workspace_bytes
            copy_root = None

            def replace_copy_root(root, relative, content):
                nonlocal copy_root
                real_write(root, relative, content)
                copy_root = Path(root)
                copy_root.rename(displaced)
                replacement.rename(copy_root)
                raise OSError("copy interrupted after replacement")

            with mock.patch.object(
                workspace_fs,
                "write_workspace_bytes",
                side_effect=replace_copy_root,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertIsNotNone(copy_root)
            self.assertEqual(
                (copy_root / "sentinel.txt").read_text(encoding="utf-8"),
                "existing sentinel",
            )

    def test_copy_publish_does_not_overwrite_destination_created_during_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            real_write = workspace_fs.write_workspace_bytes

            def create_destination_before_publish(root, relative, content):
                real_write(root, relative, content)
                if Path(root) != destination and not destination.exists():
                    destination.mkdir()
                    (destination / "sentinel.txt").write_text(
                        "existing sentinel",
                        encoding="utf-8",
                    )

            with mock.patch.object(
                workspace_fs,
                "write_workspace_bytes",
                side_effect=create_destination_before_publish,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertEqual(
                (destination / "sentinel.txt").read_text(encoding="utf-8"),
                "existing sentinel",
            )

    def test_copy_publish_rejects_replaced_staging_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement = base / "replacement"
            displaced = base / "displaced-copy"
            source.mkdir()
            replacement.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (replacement / "sentinel.txt").write_text("existing sentinel", encoding="utf-8")
            real_write = workspace_fs.write_workspace_bytes
            copy_root = None

            def replace_staging_before_publish(root, relative, content):
                nonlocal copy_root
                real_write(root, relative, content)
                copy_root = Path(root)
                copy_root.rename(displaced)
                replacement.rename(copy_root)

            with mock.patch.object(
                workspace_fs,
                "write_workspace_bytes",
                side_effect=replace_staging_before_publish,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertIsNotNone(copy_root)
            self.assertEqual(
                (copy_root / "sentinel.txt").read_text(encoding="utf-8"),
                "existing sentinel",
            )
            self.assertFalse(destination.exists())

    def test_copy_publish_rejects_replacement_after_prevalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement = base / "replacement"
            displaced = base / "displaced-copy"
            source.mkdir()
            replacement.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (replacement / "sentinel.txt").write_text("existing sentinel", encoding="utf-8")
            real_rename = getattr(workspace_fs, "_rename_staging_noreplace", None)

            def replace_after_validation(staging, target):
                os.rename(staging, displaced)
                os.rename(replacement, staging)
                if real_rename is None:
                    raise AssertionError("rename helper was not called")
                return real_rename(staging, target)

            with mock.patch.object(
                workspace_fs,
                "_rename_staging_noreplace",
                create=True,
                side_effect=replace_after_validation,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(destination.exists())
            sentinels = list(base.rglob("sentinel.txt"))
            self.assertEqual(len(sentinels), 1)
            self.assertEqual(sentinels[0].read_text(encoding="utf-8"), "existing sentinel")

    def test_copy_cleanup_never_rmtree_after_identity_precheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement = base / "replacement"
            displaced = base / "displaced-copy"
            source.mkdir()
            replacement.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (replacement / "sentinel.txt").write_text("existing sentinel", encoding="utf-8")
            real_rmtree = shutil.rmtree
            copy_root = None

            def fail_write(root, _relative, _content):
                nonlocal copy_root
                copy_root = Path(root)
                raise OSError("copy interrupted")

            def replace_before_rmtree(path, *args, **kwargs):
                path = Path(path)
                os.rename(path, displaced)
                os.rename(replacement, path)
                return real_rmtree(path, *args, **kwargs)

            with (
                mock.patch.object(
                    workspace_fs,
                    "write_workspace_bytes",
                    side_effect=fail_write,
                ),
                mock.patch.object(
                    shutil,
                    "rmtree",
                    side_effect=replace_before_rmtree,
                ) as rmtree,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertIsNotNone(copy_root)
            rmtree.assert_not_called()
            sentinels = list(base.rglob("sentinel.txt"))
            self.assertEqual(len(sentinels), 1)
            self.assertEqual(sentinels[0].read_text(encoding="utf-8"), "existing sentinel")

    def test_copy_rejects_destination_replaced_before_postpublish_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement = base / "replacement"
            displaced = base / "displaced-published"
            source.mkdir()
            replacement.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (replacement / "sentinel.txt").write_text("existing sentinel", encoding="utf-8")
            real_verify = getattr(workspace_fs, "_verify_published_tree", None)

            def replace_before_verify(target, expected_identity, marker_name, marker_token):
                os.rename(target, displaced)
                os.rename(replacement, target)
                if real_verify is None:
                    raise AssertionError("postpublish verifier was not called")
                return real_verify(target, expected_identity, marker_name, marker_token)

            with mock.patch.object(
                workspace_fs,
                "_verify_published_tree",
                create=True,
                side_effect=replace_before_verify,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(destination.exists())
            sentinels = list(base.rglob("sentinel.txt"))
            self.assertEqual(len(sentinels), 1)
            self.assertEqual(sentinels[0].read_text(encoding="utf-8"), "existing sentinel")

    def test_copy_never_unlinks_marker_replaced_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            replacement_marker = base / "replacement-marker"
            displaced_marker = base / "displaced-marker"
            source.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            replacement_marker.write_text("marker sentinel", encoding="utf-8")
            real_unlink = Path.unlink

            def replace_marker_before_unlink(path, missing_ok=False):
                path = Path(path)
                if ".owner-" in path.name:
                    os.rename(path, displaced_marker)
                    os.rename(replacement_marker, path)
                return real_unlink(path, missing_ok=missing_ok)

            with mock.patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=replace_marker_before_unlink,
            ) as unlink:
                copy_workspace_tree(source, destination)

            unlink.assert_not_called()
            self.assertEqual(
                replacement_marker.read_text(encoding="utf-8"),
                "marker sentinel",
            )
            self.assertEqual(
                (destination / "a.txt").read_text(encoding="utf-8"),
                "a",
            )

    def test_copy_destination_lstat_error_uses_stable_path_race_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            real_lstat = Path.lstat

            def deny_destination(path):
                if path == destination:
                    raise PermissionError("lstat denied")
                return real_lstat(path)

            with mock.patch.object(Path, "lstat", autospec=True, side_effect=deny_destination):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(destination.exists())

    def test_copy_staging_mkdir_error_uses_stable_path_race_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()

            with mock.patch.object(
                workspace_fs,
                "_create_private_staging",
                create=True,
                side_effect=PermissionError("mkdir denied"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "path_race")
            self.assertFalse(destination.exists())

    def test_iter_does_not_accept_entries_from_replaced_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (nested / "inside.txt").write_text("inside", encoding="utf-8")
            external = Path(outside)
            (external / "sentinel.txt").write_text("external sentinel", encoding="utf-8")
            real_scandir = os.scandir

            def redirect_nested_scan(path):
                if not isinstance(path, int) and Path(path) == nested:
                    return real_scandir(external)
                return real_scandir(path)

            with mock.patch.object(os, "scandir", side_effect=redirect_nested_scan):
                try:
                    files = list(iter_workspace_files(root))
                except WorkspacePathError as exc:
                    self.assertEqual(exc.rule_family, "path_race")
                else:
                    self.assertEqual(files, ["nested/inside.txt"])

    @unittest.skipUnless(os.name == "nt", "Windows directory identity validation")
    def test_iter_rejects_directory_identity_change_before_child_open(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (nested / "inside.txt").write_text("inside", encoding="utf-8")
            external = Path(outside)
            sentinel = external / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            root_stat = root.stat()
            outside_stat = external.stat()
            identities = (
                (root_stat.st_dev, root_stat.st_ino),
                (outside_stat.st_dev, outside_stat.st_ino),
            )
            real_scandir = os.scandir

            def redirect_replaced_directory(path):
                if not isinstance(path, int) and Path(path) == nested:
                    return real_scandir(external)
                return real_scandir(path)

            with (
                mock.patch.object(
                    workspace_fs,
                    "_windows_handle_identity",
                    create=True,
                    side_effect=identities,
                ),
                mock.patch.object(
                    workspace_fs,
                    "_open_windows_workspace_fd",
                    wraps=workspace_fs._open_windows_workspace_fd,
                ) as open_file,
                mock.patch.object(
                    os,
                    "scandir",
                    side_effect=redirect_replaced_directory,
                ),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "path_race")
            open_file.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    @unittest.skipUnless(os.name == "nt", "Windows volume identity validation")
    def test_iter_rejects_different_volume_with_same_file_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (nested / "inside.txt").write_text("inside", encoding="utf-8")
            root_volume = root.stat().st_dev

            with mock.patch.object(
                workspace_fs,
                "_windows_handle_volume_serial",
                create=True,
                side_effect=(root_volume, root_volume + 1),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "path_race")

    @unittest.skipUnless(os.name == "nt", "Windows handle close validation")
    def test_iter_maps_directory_close_handle_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_close_handle = getattr(workspace_fs, "_windows_close_handle", None)

            def close_then_report_failure(handle):
                if real_close_handle is not None:
                    real_close_handle(handle)
                return False

            with mock.patch.object(
                workspace_fs,
                "_windows_close_handle",
                create=True,
                side_effect=close_then_report_failure,
            ) as close_handle:
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "path_race")
            close_handle.assert_called_once()

    @unittest.skipIf(os.name == "nt", "POSIX root descriptor validation")
    def test_posix_scan_rejects_root_ancestor_replaced_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            base = Path(tmp)
            replaceable = base / "replaceable"
            saved = base / "saved"
            root = replaceable / "workspace"
            root.mkdir(parents=True)
            (root / "inside.txt").write_text("inside", encoding="utf-8")
            external_parent = Path(outside)
            external_root = external_parent / "workspace"
            external_root.mkdir()
            sentinel = external_root / "sentinel.txt"
            sentinel.write_text("external sentinel", encoding="utf-8")
            real_validate_root = workspace_fs._validate_root
            replaced = False

            def validate_then_replace(path):
                nonlocal replaced
                result = real_validate_root(path)
                if not replaced:
                    replaceable.rename(saved)
                    os.symlink(external_parent, replaceable, target_is_directory=True)
                    replaced = True
                return result

            with mock.patch.object(
                workspace_fs,
                "_validate_root",
                side_effect=validate_then_replace,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertIn(raised.exception.rule_family, {"linked_path", "path_race"})
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_iter_permission_error_uses_stable_path_race_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with mock.patch.object(os, "scandir", side_effect=PermissionError("denied")):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "path_race")

    def test_iter_rejects_mocked_reparse_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

            class FakeEntry:
                name = "entry.txt"

                def stat(self, *, follow_symlinks=True):
                    if follow_symlinks:
                        raise AssertionError("scan followed a reparse entry")
                    return types.SimpleNamespace(
                        st_mode=stat.S_IFREG,
                        st_file_attributes=reparse_flag,
                    )

            class FakeScandir:
                def __enter__(self):
                    return iter([FakeEntry()])

                def __exit__(self, *_args):
                    return None

            with (
                mock.patch.object(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    reparse_flag,
                    create=True,
                ),
                mock.patch.object(os, "scandir", return_value=FakeScandir()),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "reparse_point")

    def test_iter_rejects_internal_and_external_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            inside = root / "inside"
            inside.mkdir()
            (inside / "inside.txt").write_text("inside", encoding="utf-8")
            external = Path(outside)
            (external / "sentinel.txt").write_text("sentinel", encoding="utf-8")
            WorkspaceFileIOTests._symlink_or_skip(
                inside,
                root / "internal-dir-link",
                is_directory=True,
            )
            WorkspaceFileIOTests._symlink_or_skip(
                external,
                root / "external-dir-link",
                is_directory=True,
            )

            with self.assertRaises(WorkspacePathError) as raised:
                list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_iter_rejects_non_regular_entry_and_closes_scandir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            class FakeEntry:
                name = "special"

                def stat(self, *, follow_symlinks=True):
                    if follow_symlinks:
                        raise AssertionError("scan followed a link-like entry")
                    return types.SimpleNamespace(
                        st_mode=stat.S_IFIFO,
                        st_file_attributes=0,
                    )

            class FakeScandir:
                def __init__(self):
                    self.closed = False

                def __enter__(self):
                    return iter([FakeEntry()])

                def __exit__(self, *_args):
                    self.closed = True

            scanner = FakeScandir()
            with mock.patch.object(os, "scandir", return_value=scanner):
                with self.assertRaises(WorkspacePathError) as raised:
                    list(iter_workspace_files(root))

            self.assertEqual(raised.exception.rule_family, "unsafe_file_type")
            self.assertTrue(scanner.closed)

    def test_copy_rejects_reparse_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            linked = source / "linked"
            linked.mkdir()
            real_is_link_like = workspace_fs.is_link_like

            def mocked_is_link_like(path):
                return Path(path) == linked or real_is_link_like(path)

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=mocked_is_link_like,
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    copy_workspace_tree(source, destination)

            self.assertEqual(raised.exception.rule_family, "reparse_point")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
