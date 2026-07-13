from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import specgate.workspace_fs as workspace_fs
from specgate.workspace_fs import (
    WorkspacePathError,
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
    write_workspace_text,
)


class WorkspacePathErrorTests(unittest.TestCase):
    def test_exposes_message_and_rule_family(self):
        error = WorkspacePathError("unsafe path", "linked_path")

        self.assertEqual(str(error), "unsafe path")
        self.assertEqual(error.rule_family, "linked_path")


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
