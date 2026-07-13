import io
import sqlite3
import stat
import tempfile
import threading
import unittest
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest import mock

import specgate.web_projects as web_projects
import specgate.workspace_fs as workspace_fs
from specgate.workspace_fs import WorkspacePathError
from specgate.web_auth import create_user
from specgate.web_db import connect_db, init_db
from specgate.web_projects import (
    create_manual_project,
    create_project_from_zip,
    package_result_zip,
    project_paths,
)


class WebProjectsTests(unittest.TestCase):
    def make_context(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        db_path = base / "web.sqlite3"
        data_root = base / "data"
        data_root.mkdir()
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        return db_path, data_root, user

    def zip_bytes(self, files):
        return self.zip_entries(files.items())

    def zip_entries(self, entries, *, compression=zipfile.ZIP_STORED):
        buffer = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w", compression=compression) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in entries:
                archive.writestr(name, content)
        return buffer.getvalue()

    def zip_bytes_with_raw_name(self, stored_name, raw_name, content):
        zip_content = self.zip_bytes(
            {
                stored_name: content,
                "CHECKLIST.md": "Checklist",
            }
        )
        return zip_content.replace(stored_name.encode("utf-8"), raw_name.encode("utf-8"))

    def assert_no_projects_or_upload_residue(self, db_path, data_root, user_id):
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from projects").fetchone()[0], 0)
        projects_root = data_root / "users" / str(user_id) / "projects"
        if projects_root.exists():
            self.assertTrue(all(path.name.startswith(".") for path in projects_root.iterdir()))

    def test_create_manual_project_writes_input_snapshot_and_workspace(self):
        db_path, data_root, user = self.make_context()

        project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Manual Site",
            spec_text="# Spec\nBuild it",
            checklist_text="- [ ] Ship",
            index_html="<h1>Hello</h1>",
        )

        self.assertIsInstance(project, sqlite3.Row)
        self.assertEqual(project["name"], "Manual Site")
        self.assertEqual(project["create_mode"], "manual")

        paths = project_paths(data_root, user["id"], project["id"])
        self.assertEqual(project["root_path"], str(paths.root))
        for directory in (paths.original, paths.workspace, paths.artifacts, paths.runs):
            self.assertTrue(directory.is_dir())

        for directory in (paths.original, paths.workspace):
            self.assertEqual((directory / "TASK_SPEC.md").read_text(encoding="utf-8"), "# Spec\nBuild it")
            self.assertEqual((directory / "CHECKLIST.md").read_text(encoding="utf-8"), "- [ ] Ship")
            self.assertEqual((directory / "index.html").read_text(encoding="utf-8"), "<h1>Hello</h1>")

    def test_create_project_from_zip_copies_original_to_workspace(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes(
            {
                "docs/SPEC": "Spec",
                "docs/CHECKLIST.md": "Checklist",
                "site/index.html": "<h1>Zip</h1>",
            }
        )

        project = create_project_from_zip(
            db_path,
            data_root,
            user["id"],
            "Zip Site",
            zip_content,
        )

        self.assertEqual(project["name"], "Zip Site")
        self.assertEqual(project["create_mode"], "zip")
        paths = project_paths(data_root, user["id"], project["id"])
        self.assertEqual(project["root_path"], str(paths.root))
        for directory in (paths.original, paths.workspace):
            self.assertEqual((directory / "docs" / "SPEC").read_text(encoding="utf-8"), "Spec")
            self.assertEqual((directory / "docs" / "CHECKLIST.md").read_text(encoding="utf-8"), "Checklist")
            self.assertEqual((directory / "site" / "index.html").read_text(encoding="utf-8"), "<h1>Zip</h1>")
        self.assertFalse((paths.original / "TASK_SPEC.md").exists())
        self.assertFalse((paths.original / "CHECKLIST.md").exists())
        self.assertEqual((paths.workspace / "TASK_SPEC.md").read_text(encoding="utf-8"), "Spec")
        self.assertEqual((paths.workspace / "CHECKLIST.md").read_text(encoding="utf-8"), "Checklist")

    def test_create_project_from_zip_uses_safe_directory_api_for_explicit_directories(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_entries(
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("empty/nested/", b"")]
        )
        real_ensure = workspace_fs.ensure_workspace_directory

        with mock.patch.object(
            web_projects,
            "ensure_workspace_directory",
            create=True,
            wraps=real_ensure,
        ) as safe_directory:
            project = create_project_from_zip(
                db_path,
                data_root,
                user["id"],
                "Directories",
                zip_content,
            )

        paths = project_paths(data_root, user["id"], project["id"])
        self.assertTrue((paths.original / "empty" / "nested").is_dir())
        self.assertTrue((paths.workspace / "empty" / "nested").is_dir())
        self.assertEqual(safe_directory.call_count, 5)
        self.assertEqual(
            [call.args[1] for call in safe_directory.call_args_list],
            ["users/1/projects", "original", "artifacts", "runs", "empty/nested"],
        )

    def test_create_project_from_zip_extracts_once_then_uses_safe_workspace_copy(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes(
            {"SPEC.md": "Spec", "CHECKLIST.md": "Checklist", "site/index.html": "index"}
        )
        real_bind = web_projects.bind_workspace_tree
        real_extract = web_projects._extract_archive
        real_copy = workspace_fs.copy_workspace_tree

        with (
            mock.patch.object(web_projects, "bind_workspace_tree", wraps=real_bind) as bind_tree,
            mock.patch.object(web_projects, "_extract_archive", wraps=real_extract) as extract,
            mock.patch.object(
                web_projects,
                "copy_workspace_tree",
                create=True,
                wraps=real_copy,
            ) as copy_tree,
        ):
            project = create_project_from_zip(
                db_path,
                data_root,
                user["id"],
                "Single extraction",
                zip_content,
            )

        paths = project_paths(data_root, user["id"], project["id"])
        self.assertEqual(bind_tree.call_count, 1)
        self.assertEqual(extract.call_count, 1)
        copy_tree.assert_called_once()
        copied_source, copied_destination = copy_tree.call_args.args
        self.assertEqual(copied_source.name, "original")
        self.assertEqual(copied_destination.name, "workspace")
        self.assertEqual(copied_source.parent, copied_destination.parent)
        self.assertEqual((paths.workspace / "site" / "index.html").read_text(encoding="utf-8"), "index")

    def test_zip_file_preparation_does_not_hold_project_database_write_transaction(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})
        entered_extract = threading.Event()
        release_extract = threading.Event()
        real_extract = web_projects._extract_archive

        def slow_extract(*args, **kwargs):
            entered_extract.set()
            if not release_extract.wait(timeout=5):
                raise AssertionError("test did not release archive extraction")
            return real_extract(*args, **kwargs)

        with mock.patch.object(web_projects, "_extract_archive", side_effect=slow_extract):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    create_project_from_zip,
                    db_path,
                    data_root,
                    user["id"],
                    "Slow upload",
                    zip_content,
                )
                self.assertTrue(entered_extract.wait(timeout=2))
                try:
                    concurrent = sqlite3.connect(db_path, timeout=0.1)
                    try:
                        concurrent.execute(
                            """
                            insert into projects (
                              user_id, name, create_mode, root_path, created_at, updated_at
                            ) values (?, ?, ?, ?, ?, ?)
                            """,
                            (user["id"], "Concurrent", "manual", "", "now", "now"),
                        )
                        concurrent.commit()
                    finally:
                        concurrent.close()
                finally:
                    release_extract.set()
                project = future.result(timeout=5)

        self.assertEqual(project["id"], 2)
        self.assertEqual(project["root_path"], str(project_paths(data_root, user["id"], 2).root))

    def test_zip_staging_parent_is_created_safely_relative_to_data_root(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})
        real_ensure = workspace_fs.ensure_workspace_directory

        with mock.patch.object(
            web_projects,
            "ensure_workspace_directory",
            wraps=real_ensure,
        ) as ensure_directory:
            create_project_from_zip(
                db_path,
                data_root,
                user["id"],
                "Safe parent",
                zip_content,
            )

        self.assertIn(
            mock.call(data_root, f"users/{user['id']}/projects"),
            ensure_directory.call_args_list,
        )

    def test_staging_replacement_during_extraction_stops_before_next_write(self):
        db_path, data_root, user = self.make_context()
        base = data_root.parent
        replacement = base / "replacement"
        (replacement / "original").mkdir(parents=True)
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})
        real_write = web_projects.write_workspace_stream
        staging_root = None
        writes = 0

        def replace_after_first_write(root, relative, source, **kwargs):
            nonlocal staging_root, writes
            written = real_write(root, relative, source, **kwargs)
            writes += 1
            if writes == 1:
                staging_root = Path(root).parent
                displaced = staging_root.parent / ".displaced-staging"
                binding = workspace_fs.bind_workspace_tree(staging_root)
                workspace_fs.rename_workspace_tree_noreplace(binding, displaced)
                replacement.rename(staging_root)
            return written

        with mock.patch.object(
            web_projects,
            "write_workspace_stream",
            side_effect=replace_after_first_write,
        ):
            with self.assertRaises(WorkspacePathError):
                create_project_from_zip(db_path, data_root, user["id"], "Replaced", zip_content)

        self.assertIsNotNone(staging_root)
        self.assertEqual((staging_root / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
        self.assertFalse((staging_root / "original" / "CHECKLIST.md").exists())
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())

    def test_staging_replacement_before_publish_is_not_rebound(self):
        db_path, data_root, user = self.make_context()
        base = data_root.parent
        replacement = base / "replacement"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})
        real_normalize = web_projects._normalize_workspace_inputs
        staging_root = None

        def replace_after_normalize(original, workspace, spec_path, checklist_path):
            nonlocal staging_root
            real_normalize(original, workspace, spec_path, checklist_path)
            staging_root = Path(original).parent
            safe_displaced = staging_root.parent / ".displaced-staging"
            binding = workspace_fs.bind_workspace_tree(staging_root)
            workspace_fs.rename_workspace_tree_noreplace(binding, safe_displaced)
            replacement.rename(staging_root)

        with mock.patch.object(
            web_projects,
            "_normalize_workspace_inputs",
            side_effect=replace_after_normalize,
        ):
            with self.assertRaises(WorkspacePathError):
                create_project_from_zip(db_path, data_root, user["id"], "Replaced", zip_content)

        self.assertIsNotNone(staging_root)
        self.assertEqual((staging_root / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from projects").fetchone()[0], 0)

    def test_create_project_from_zip_rejects_path_escape(self):
        db_path, data_root, user = self.make_context()

        for unsafe_name in (
            "../escape.txt",
            "nested/../../escape.txt",
            r"..\evil.txt",
            "/absolute.txt",
            "C:escape.txt",
            "//server/share.txt",
            "nested//ambiguous.txt",
            "nested/./ambiguous.txt",
            "trailing-dot./file.txt",
            "trailing-space /file.txt",
            "CON/file.txt",
            ".",
        ):
            with self.subTest(unsafe_name=unsafe_name):
                zip_content = self.zip_bytes(
                    {
                        "SPEC.md": "Spec",
                        "CHECKLIST.md": "Checklist",
                        unsafe_name: "unsafe",
                    }
                )

                with self.assertRaises(ValueError):
                    create_project_from_zip(db_path, data_root, user["id"], "Unsafe", zip_content)

    def test_create_project_from_zip_rejects_backslash_paths(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes_with_raw_name("docs/SPEC.md", r"docs\SPEC.md", "Spec")
        self.assertIn(rb"docs\SPEC.md", zip_content)

        with self.assertRaises(ValueError):
            create_project_from_zip(db_path, data_root, user["id"], "Backslash", zip_content)

    def test_create_project_from_zip_rejects_nul_in_raw_member_name(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes_with_raw_name("docsxSPEC.md", "docs\x00SPEC.md", "Spec")

        with self.assertRaises(ValueError):
            create_project_from_zip(db_path, data_root, user["id"], "Nul", zip_content)

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_windows_invalid_characters_before_writing(self):
        db_path, data_root, user = self.make_context()
        for unsafe_name in ('bad<name.txt', 'bad>name.txt', 'bad"name.txt', 'bad|name.txt', 'bad?name.txt', 'bad*name.txt'):
            with self.subTest(unsafe_name=unsafe_name), mock.patch.object(
                web_projects,
                "write_workspace_stream",
            ) as safe_write:
                with self.assertRaises(ValueError):
                    create_project_from_zip(
                        db_path,
                        data_root,
                        user["id"],
                        "Invalid name",
                        self.zip_bytes(
                            {"SPEC.md": "Spec", "CHECKLIST.md": "Checklist", unsafe_name: "unsafe"}
                        ),
                    )

            safe_write.assert_not_called()

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_unix_links_and_special_files(self):
        db_path, data_root, user = self.make_context()
        for file_type in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR):
            with self.subTest(file_type=file_type):
                special = zipfile.ZipInfo("special")
                special.create_system = 3
                special.external_attr = (file_type | 0o600) << 16
                zip_content = self.zip_entries(
                    [
                        ("SPEC.md", "Spec"),
                        ("CHECKLIST.md", "Checklist"),
                        (special, "payload"),
                    ]
                )

                with self.assertRaises(ValueError):
                    create_project_from_zip(db_path, data_root, user["id"], "Special", zip_content)

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_special_mode_even_with_non_unix_creator(self):
        db_path, data_root, user = self.make_context()
        special = zipfile.ZipInfo("special")
        special.create_system = 0
        special.external_attr = (stat.S_IFLNK | 0o600) << 16

        with self.assertRaises(ValueError):
            create_project_from_zip(
                db_path,
                data_root,
                user["id"],
                "Disguised",
                self.zip_entries(
                    [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), (special, "target")]
                ),
            )

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_directory_entries_with_content_before_writing(self):
        db_path, data_root, user = self.make_context()
        directory = zipfile.ZipInfo("payload/")
        directory.external_attr = (stat.S_IFDIR | 0o700) << 16
        zip_content = self.zip_entries(
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), (directory, "hidden")]
        )

        with mock.patch.object(web_projects, "write_workspace_stream") as safe_write:
            with self.assertRaises(ValueError):
                create_project_from_zip(db_path, data_root, user["id"], "Directory data", zip_content)

        safe_write.assert_not_called()
        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_duplicate_case_and_prefix_conflicts(self):
        db_path, data_root, user = self.make_context()
        cases = (
            [("SPEC.md", "one"), ("SPEC.md", "two"), ("CHECKLIST.md", "Checklist")],
            [("SPEC.md", "Spec"), ("spec.MD", "other"), ("CHECKLIST.md", "Checklist")],
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("Assets/a.txt", "a"), ("assets/b.txt", "b")],
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("assets", "file"), ("assets/a.txt", "nested")],
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("assets", "file"), ("assets/sub/", b"")],
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("docs/", b""), ("docs", "file")],
        )

        for entries in cases:
            with self.subTest(entries=[str(entry[0]) for entry in entries]):
                with self.assertRaises(ValueError):
                    create_project_from_zip(
                        db_path,
                        data_root,
                        user["id"],
                        "Conflict",
                        self.zip_entries(entries),
                    )

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_file_directory_prefix_conflict_is_rejected_before_any_write(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_entries(
            [
                ("SPEC.md", "Spec"),
                ("CHECKLIST.md", "Checklist"),
                ("assets", "file"),
                ("assets/sub/", b""),
            ]
        )

        with mock.patch.object(web_projects, "write_workspace_stream") as safe_write:
            with self.assertRaises(ValueError):
                create_project_from_zip(db_path, data_root, user["id"], "Conflict", zip_content)

        safe_write.assert_not_called()
        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_enforces_archive_limits(self):
        db_path, data_root, user = self.make_context()
        cases = (
            ("MAX_ZIP_FILES", 2, [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("index.html", "x")]),
            ("MAX_ZIP_DIRECTORIES", 1, [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("a/b/c.txt", "x")]),
            ("MAX_ZIP_FILE_BYTES", 3, [("SPEC.md", "Spec"), ("CHECKLIST.md", "ok")]),
            ("MAX_ZIP_TOTAL_BYTES", 8, [("SPEC.md", "Spec"), ("CHECKLIST.md", "Check")]),
        )

        for constant, limit, entries in cases:
            with self.subTest(constant=constant):
                with mock.patch.object(web_projects, constant, limit, create=True):
                    with self.assertRaises(web_projects.ArchiveLimitError):
                        create_project_from_zip(
                            db_path,
                            data_root,
                            user["id"],
                            "Limited",
                            self.zip_entries(entries),
                        )

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_excessive_compression_ratio(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_entries(
            [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist"), ("data.txt", "x" * 1000)],
            compression=zipfile.ZIP_DEFLATED,
        )

        with mock.patch.object(web_projects, "MAX_ZIP_COMPRESSION_RATIO", 2, create=True):
            with self.assertRaises(web_projects.ArchiveLimitError):
                create_project_from_zip(db_path, data_root, user["id"], "Compressed", zip_content)

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rejects_encrypted_and_unsupported_entries(self):
        db_path, data_root, user = self.make_context()
        base = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})
        for archive_bytes in (
            self.patch_zip_member(base, "SPEC.md", flag_bits=1),
            self.patch_zip_member(base, "SPEC.md", flag_bits=0x40),
            self.patch_zip_member(base, "SPEC.md", flag_bits=0x2000),
            self.patch_zip_member(base, "SPEC.md", compression=99),
        ):
            with self.subTest():
                with self.assertRaises(ValueError):
                    create_project_from_zip(db_path, data_root, user["id"], "Unsupported", archive_bytes)

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_checks_crc_before_writing(self):
        db_path, data_root, user = self.make_context()
        corrupt_archives = (
            self.corrupt_stored_member(
                self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"}),
                "SPEC.md",
            ),
            self.corrupt_stored_member(
                self.zip_entries(
                    [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist")],
                    compression=zipfile.ZIP_DEFLATED,
                ),
                "SPEC.md",
            ),
            self.corrupt_stored_member(
                self.zip_entries(
                    [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist")],
                    compression=zipfile.ZIP_BZIP2,
                ),
                "SPEC.md",
            ),
            self.corrupt_stored_member(
                self.zip_entries(
                    [("SPEC.md", "Spec"), ("CHECKLIST.md", "Checklist")],
                    compression=zipfile.ZIP_LZMA,
                ),
                "SPEC.md",
            ),
        )

        for corrupt in corrupt_archives:
            with self.subTest(), mock.patch.object(
                web_projects,
                "write_workspace_stream",
                create=True,
            ) as safe_write:
                with self.assertRaises(ValueError):
                    create_project_from_zip(db_path, data_root, user["id"], "Corrupt", corrupt)

            safe_write.assert_not_called()
        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_rolls_back_failed_extraction_and_staging(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})

        with mock.patch.object(
            web_projects,
            "write_workspace_stream",
            create=True,
            side_effect=WorkspacePathError("write failed", "path_race"),
        ):
            with self.assertRaises(WorkspacePathError):
                create_project_from_zip(db_path, data_root, user["id"], "Failed", zip_content)

        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_failed_extraction_quarantines_owned_staging(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})

        with mock.patch.object(
            web_projects,
            "write_workspace_stream",
            side_effect=WorkspacePathError("write failed", "path_race"),
        ):
            with self.assertRaises(WorkspacePathError):
                create_project_from_zip(db_path, data_root, user["id"], "Failed", zip_content)

        projects_root = data_root / "users" / str(user["id"]) / "projects"
        quarantines = list(projects_root.glob(".*.specgate-upload-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())
        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_cleanup_does_not_delete_staging_replacement(self):
        db_path, data_root, user = self.make_context()
        base = data_root.parent
        replacement = base / "replacement"
        displaced = base / "displaced-staging"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})

        def replace_staging(root, _relative, _source, **_kwargs):
            staging_root = Path(root).parent
            staging_root.rename(displaced)
            replacement.rename(staging_root)
            raise WorkspacePathError("write failed", "path_race")

        with mock.patch.object(web_projects, "write_workspace_stream", side_effect=replace_staging):
            with self.assertRaises(WorkspacePathError) as raised:
                create_project_from_zip(db_path, data_root, user["id"], "Replaced", zip_content)

        self.assertEqual(raised.exception.rule_family, "path_race")
        self.assertTrue(
            any("upload cleanup failed" in note for note in getattr(raised.exception, "__notes__", ()))
        )
        sentinels = list(base.rglob("sentinel.txt"))
        self.assertEqual(len(sentinels), 1)
        self.assertEqual(sentinels[0].read_text(encoding="utf-8"), "external sentinel")
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from projects").fetchone()[0], 0)

    def test_cleanup_quarantine_failure_is_attached_to_original_error(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})

        with (
            mock.patch.object(
                web_projects,
                "write_workspace_stream",
                side_effect=WorkspacePathError("write failed", "path_race"),
            ),
            mock.patch.object(
                web_projects,
                "rename_workspace_tree_noreplace",
                side_effect=WorkspacePathError("upload quarantine failed", "path_race"),
            ),
        ):
            with self.assertRaises(WorkspacePathError) as raised:
                create_project_from_zip(db_path, data_root, user["id"], "Cleanup failure", zip_content)

        self.assertEqual(str(raised.exception), "write failed")
        self.assertTrue(
            any("upload cleanup failed" in note for note in getattr(raised.exception, "__notes__", ()))
        )
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from projects").fetchone()[0], 0)

    def test_finalize_failure_quarantines_published_project_root(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"})

        with mock.patch.object(web_projects, "_finalize_project", side_effect=RuntimeError("finalize failed")):
            with self.assertRaisesRegex(RuntimeError, "finalize failed"):
                create_project_from_zip(db_path, data_root, user["id"], "Finalize failure", zip_content)

        projects_root = data_root / "users" / str(user["id"]) / "projects"
        quarantines = list(projects_root.glob(".1.specgate-upload-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual((quarantines[0] / "original" / "SPEC.md").read_text(encoding="utf-8"), "Spec")
        self.assertFalse(project_paths(data_root, user["id"], 1).root.exists())
        self.assert_no_projects_or_upload_residue(db_path, data_root, user["id"])

    def test_create_project_from_zip_never_overwrites_existing_project_path(self):
        db_path, data_root, user = self.make_context()
        occupied = project_paths(data_root, user["id"], 1).root
        occupied.mkdir(parents=True)
        sentinel = occupied / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaises((ValueError, WorkspacePathError)):
            create_project_from_zip(
                db_path,
                data_root,
                user["id"],
                "Occupied",
                self.zip_bytes({"SPEC.md": "Spec", "CHECKLIST.md": "Checklist"}),
            )

        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from projects").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(occupied.iterdir()), [sentinel])

    @staticmethod
    def patch_zip_member(content, member_name, *, flag_bits=None, compression=None):
        patched = bytearray(content)
        encoded_name = member_name.encode("utf-8")
        for signature, header_size, name_length_offset, flag_offset, compression_offset in (
            (b"PK\x03\x04", 30, 26, 6, 8),
            (b"PK\x01\x02", 46, 28, 8, 10),
        ):
            cursor = 0
            while True:
                cursor = patched.find(signature, cursor)
                if cursor < 0:
                    break
                name_length = int.from_bytes(
                    patched[cursor + name_length_offset : cursor + name_length_offset + 2],
                    "little",
                )
                name_start = cursor + header_size
                if bytes(patched[name_start : name_start + name_length]) == encoded_name:
                    if flag_bits is not None:
                        patched[cursor + flag_offset : cursor + flag_offset + 2] = flag_bits.to_bytes(2, "little")
                    if compression is not None:
                        patched[cursor + compression_offset : cursor + compression_offset + 2] = compression.to_bytes(2, "little")
                cursor = name_start + name_length
        return bytes(patched)

    @staticmethod
    def corrupt_stored_member(content, member_name):
        corrupted = bytearray(content)
        cursor = corrupted.find(b"PK\x03\x04")
        while cursor >= 0:
            name_length = int.from_bytes(corrupted[cursor + 26 : cursor + 28], "little")
            extra_length = int.from_bytes(corrupted[cursor + 28 : cursor + 30], "little")
            name_start = cursor + 30
            if bytes(corrupted[name_start : name_start + name_length]) == member_name.encode("utf-8"):
                compressed_size = int.from_bytes(corrupted[cursor + 18 : cursor + 22], "little")
                data_start = name_start + name_length + extra_length
                corrupted[data_start + compressed_size // 2] ^= 0x01
                return bytes(corrupted)
            cursor = corrupted.find(b"PK\x03\x04", name_start + name_length)
        raise AssertionError("member not found")

    def test_create_project_from_zip_requires_spec_and_checklist(self):
        db_path, data_root, user = self.make_context()

        cases = [
            {"CHECKLIST.md": "Checklist"},
            {"SPEC.md": "Spec"},
            {"README.md": "Neither"},
        ]
        for files in cases:
            with self.subTest(files=sorted(files)):
                with self.assertRaises(ValueError):
                    create_project_from_zip(
                        db_path,
                        data_root,
                        user["id"],
                        "Incomplete",
                        self.zip_bytes(files),
                    )

    def test_package_result_zip_contains_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "latest-index.html").write_text("<h1>Result</h1>", encoding="utf-8")

            zip_path = package_result_zip(artifact_dir)

            self.assertEqual(zip_path, artifact_dir / "result.zip")
            with zipfile.ZipFile(zip_path) as archive:
                self.assertEqual(archive.namelist(), ["index.html"])
                self.assertEqual(archive.read("index.html").decode("utf-8"), "<h1>Result</h1>")


if __name__ == "__main__":
    unittest.main()
