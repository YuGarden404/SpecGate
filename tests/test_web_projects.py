import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
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
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        return db_path, data_root, user

    def zip_bytes(self, files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()

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
            self.assertEqual((directory / "SPEC.md").read_text(encoding="utf-8"), "# Spec\nBuild it")
            self.assertEqual((directory / "CHECKLIST.md").read_text(encoding="utf-8"), "- [ ] Ship")
            self.assertEqual((directory / "index.html").read_text(encoding="utf-8"), "<h1>Hello</h1>")

    def test_create_project_from_zip_copies_original_to_workspace(self):
        db_path, data_root, user = self.make_context()
        zip_content = self.zip_bytes(
            {
                "TASK_SPEC.md": "Spec",
                "CHECKLIST": "Checklist",
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
            self.assertEqual((directory / "TASK_SPEC.md").read_text(encoding="utf-8"), "Spec")
            self.assertEqual((directory / "CHECKLIST").read_text(encoding="utf-8"), "Checklist")
            self.assertEqual((directory / "site" / "index.html").read_text(encoding="utf-8"), "<h1>Zip</h1>")

    def test_create_project_from_zip_rejects_path_escape(self):
        db_path, data_root, user = self.make_context()

        for unsafe_name in ("../escape.txt", "nested/../../escape.txt", r"..\escape.txt", "/absolute.txt"):
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
