import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from specgate.run_storage import initialize_run_storage, promote_run_workspace, remove_run_storage
from specgate.web_projects import RunPaths, project_paths, web_run_paths


class RunStorageTests(unittest.TestCase):
    def make_project(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = project_paths(Path(tmp.name) / "data", 2, 7)
        project.workspace.mkdir(parents=True)
        project.runs.mkdir()
        return project

    def test_web_run_paths_are_scoped_by_run_id(self):
        project = project_paths(Path("data"), 2, 7)

        run = web_run_paths(project, 11)

        root = project.runs / "11"
        self.assertEqual(
            run,
            RunPaths(
                root=root,
                workspace=root / "workspace",
                audit=root / "audit",
                approval_queue=root / "approvals" / "pending_approvals.json",
                artifacts=root / "artifacts",
                index_artifact=root / "artifacts" / "index.html",
                zip_artifact=root / "artifacts" / "result.zip",
            ),
        )

    def test_run_paths_are_immutable(self):
        run = web_run_paths(project_paths(Path("data"), 2, 7), 11)

        with self.assertRaises(FrozenInstanceError):
            run.workspace = Path("elsewhere")

    def test_initialize_run_storage_copies_project_workspace(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        (project.workspace / "nested").mkdir()
        (project.workspace / "nested" / "data.txt").write_text("data", encoding="utf-8")

        run = initialize_run_storage(project, 11)

        self.assertEqual(run, web_run_paths(project, 11))
        self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((run.workspace / "nested" / "data.txt").read_text(encoding="utf-8"), "data")
        self.assertTrue(run.audit.is_dir())
        self.assertTrue(run.approval_queue.parent.is_dir())
        self.assertTrue(run.artifacts.is_dir())

    def test_initialize_run_storage_rejects_existing_target(self):
        project = self.make_project()
        run = web_run_paths(project, 11)
        run.root.mkdir()
        sentinel = run.root / "keep.txt"
        sentinel.write_text("existing", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            initialize_run_storage(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing")
        self.assertEqual(list(project.runs.iterdir()), [run.root])

    def test_initialize_run_storage_cleans_temporary_directory_on_copy_failure(self):
        project = self.make_project()

        def fail_after_partial_copy(source, destination):
            destination.mkdir()
            (destination / "partial.txt").write_text("partial", encoding="utf-8")
            raise OSError("copy failed")

        with patch("specgate.run_storage.shutil.copytree", side_effect=fail_after_partial_copy):
            with self.assertRaisesRegex(OSError, "copy failed"):
                initialize_run_storage(project, 11)

        self.assertEqual(list(project.runs.iterdir()), [])

    def test_remove_run_storage_removes_run_root(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)
        self.assertTrue(run.root.is_dir())

        remove_run_storage(project, 11)

        self.assertFalse(run.root.exists())

    def test_promote_run_workspace_replaces_project_workspace(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        (project.workspace / "old.txt").write_text("old", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        (run.workspace / "new.txt").write_text("new", encoding="utf-8")
        (run.workspace / "old.txt").unlink()

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual((project.workspace / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertFalse((project.workspace / "old.txt").exists())
        self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_promote_run_workspace_restores_project_workspace_when_publish_rename_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        (project.workspace / "old.txt").write_text("old", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        (run.workspace / "new.txt").write_text("new", encoding="utf-8")

        original_rename = Path.rename
        rename_calls = []

        def fail_second_rename(source, target):
            rename_calls.append((source, target))
            if len(rename_calls) == 2:
                raise OSError("publish rename failed")
            return original_rename(source, target)

        with patch.object(Path, "rename", autospec=True, side_effect=fail_second_rename):
            with self.assertRaisesRegex(OSError, "publish rename failed"):
                promote_run_workspace(project, 11)

        self.assertEqual(len(rename_calls), 3)
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((project.workspace / "old.txt").read_text(encoding="utf-8"), "old")
        self.assertFalse((project.workspace / "new.txt").exists())
        self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def workspace_swap_paths(self, project):
        return sorted(
            path
            for path in project.root.iterdir()
            if path.name.startswith("workspace.next-") or path.name.startswith("workspace.backup-")
        )


if __name__ == "__main__":
    unittest.main()
