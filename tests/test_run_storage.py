import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import specgate.run_storage as run_storage
from specgate.run_storage import (
    RunStorageCleanupError,
    initialize_run_storage,
    promote_run_workspace,
    remove_run_storage,
)
from specgate.web_projects import RunPaths, project_paths, web_run_paths


class RunStorageTests(unittest.TestCase):
    ownership_marker = ".specgate-run-owner.json"

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

    def test_run_initialization_lock_is_exclusive_across_instances(self):
        project = self.make_project()
        first = run_storage.RunInitializationLock(project, 11)
        second = run_storage.RunInitializationLock(project, 11)
        self.assertEqual(first.path, project.runs / ".11.init.lock")

        first.acquire()
        try:
            self.assertFalse(second.try_acquire())
        finally:
            first.release()

        self.assertTrue(second.try_acquire())
        second.release()

    def test_run_initialization_lock_context_releases_after_exception(self):
        project = self.make_project()
        lock = run_storage.RunInitializationLock(project, 11)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with lock:
                raise RuntimeError("boom")

        contender = run_storage.RunInitializationLock(project, 11)
        self.assertTrue(contender.try_acquire())
        contender.release()

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
        marker = run.root / self.ownership_marker
        self.assertEqual(
            json.loads(marker.read_text(encoding="utf-8")),
            {"run_id": 11, "schema_version": 1},
        )
        self.assertFalse((run.workspace / self.ownership_marker).exists())
        self.assertFalse((run.artifacts / self.ownership_marker).exists())

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

    def test_initialize_run_storage_preserves_copy_error_when_temporary_cleanup_fails(self):
        project = self.make_project()

        def fail_after_partial_copy(source, destination):
            destination.mkdir()
            (destination / "partial.txt").write_text("partial", encoding="utf-8")
            raise OSError("copy failed")

        with (
            patch("specgate.run_storage.shutil.copytree", side_effect=fail_after_partial_copy),
            patch("specgate.run_storage.shutil.rmtree", side_effect=OSError("temporary cleanup failed")),
        ):
            try:
                initialize_run_storage(project, 11)
            except Exception as exc:
                error = exc
            else:
                self.fail("initialize_run_storage did not fail")

        self.assertEqual(str(error), "copy failed")
        self.assertTrue(
            any("temporary cleanup failed" in note for note in getattr(error, "__notes__", ()))
        )

    def test_initialize_run_storage_leaves_unowned_stale_temporary_directory(self):
        project = self.make_project()
        temporary_root = project.runs / ".11.tmp-unowned"
        temporary_root.mkdir()
        (temporary_root / "partial.txt").write_text("partial", encoding="utf-8")

        run = initialize_run_storage(project, 11)

        self.assertTrue(temporary_root.is_dir())
        self.assertTrue(run.root.is_dir())

    def test_cleanup_interrupted_run_storage_removes_owned_temp_and_formal_roots(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)
        temporary_root = project.runs / ".11.tmp-interrupted"
        temporary_root.mkdir()
        self.write_ownership_marker(temporary_root, 11)
        (temporary_root / "partial.txt").write_text("partial", encoding="utf-8")

        run_storage.cleanup_interrupted_run_storage(project, 11)

        self.assertFalse(temporary_root.exists())
        self.assertFalse(run.root.exists())

    def test_cleanup_interrupted_run_storage_preserves_missing_and_wrong_markers(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)
        self.write_ownership_marker(run.root, 12)
        unowned_temp = project.runs / ".11.tmp-unowned"
        unowned_temp.mkdir()
        sentinel = unowned_temp / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "unowned run storage retained"):
            run_storage.cleanup_interrupted_run_storage(project, 11)

        self.assertTrue(run.root.is_dir())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_cleanup_interrupted_run_storage_reports_owned_path_removal_failure(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)

        with patch("specgate.run_storage.shutil.rmtree", side_effect=OSError("cleanup failed")):
            with self.assertRaisesRegex(RunStorageCleanupError, "cleanup failed"):
                run_storage.cleanup_interrupted_run_storage(project, 11)

        self.assertTrue(run.root.is_dir())

    def test_remove_run_storage_removes_run_root(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)
        self.assertTrue(run.root.is_dir())

        remove_run_storage(project, 11)

        self.assertFalse(run.root.exists())

    def test_remove_run_storage_preserves_unowned_run_root(self):
        project = self.make_project()
        run = web_run_paths(project, 11)
        run.root.mkdir()
        sentinel = run.root / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "unowned run storage retained"):
            remove_run_storage(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_remove_run_storage_preserves_wrong_ownership_marker(self):
        project = self.make_project()
        run = web_run_paths(project, 11)
        run.root.mkdir()
        self.write_ownership_marker(run.root, 12)

        with self.assertRaisesRegex(RuntimeError, "unowned run storage retained"):
            remove_run_storage(project, 11)

        self.assertTrue(run.root.is_dir())

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

    def test_promote_run_workspace_keeps_committed_current_when_backup_cleanup_partially_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        (project.workspace / "old.txt").write_text("old", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        (run.workspace / "new.txt").write_text("new", encoding="utf-8")

        backup_workspace = project.workspace.with_name("workspace.backup-11")
        original_rmtree = shutil.rmtree
        backup_cleanup_attempts = 0

        def fail_first_backup_cleanup(path, *args, **kwargs):
            nonlocal backup_cleanup_attempts
            if Path(path) == backup_workspace:
                backup_cleanup_attempts += 1
                if backup_cleanup_attempts == 1:
                    (Path(path) / "old.txt").unlink()
                    raise OSError("backup cleanup failed")
            return original_rmtree(path, *args, **kwargs)

        with patch("specgate.run_storage.shutil.rmtree", side_effect=fail_first_backup_cleanup):
            with self.assertWarnsRegex(RuntimeWarning, "backup cleanup failed"):
                promote_run_workspace(project, 11)

        self.assertEqual(backup_cleanup_attempts, 1)
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual((project.workspace / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertTrue(backup_workspace.is_dir())
        self.assertFalse((backup_workspace / "old.txt").exists())
        self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v2")

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual((project.workspace / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_promote_run_workspace_keeps_backup_marker_when_committed_next_cleanup_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = project.workspace.with_name("workspace.next-11")
        backup_workspace = project.workspace.with_name("workspace.backup-11")
        project.workspace.rename(backup_workspace)
        shutil.copytree(run.workspace, project.workspace)
        shutil.copytree(run.workspace, next_workspace)

        original_rmtree = shutil.rmtree

        def partially_fail_next_cleanup(path, *args, **kwargs):
            if Path(path) == next_workspace:
                (Path(path) / "index.html").unlink()
                raise OSError("next cleanup failed")
            return original_rmtree(path, *args, **kwargs)

        with patch("specgate.run_storage.shutil.rmtree", side_effect=partially_fail_next_cleanup):
            with self.assertWarnsRegex(RuntimeWarning, "next cleanup failed"):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertTrue(next_workspace.is_dir())
        self.assertTrue(backup_workspace.is_dir())

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_promote_run_workspace_recovers_stale_next_before_retry(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = project.workspace.with_name("workspace.next-11")
        shutil.copytree(run.workspace, next_workspace)
        (next_workspace / "stale.txt").write_text("stale", encoding="utf-8")

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertFalse((project.workspace / "stale.txt").exists())
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_promote_run_workspace_recovers_backup_when_current_is_missing(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = project.workspace.with_name("workspace.next-11")
        backup_workspace = project.workspace.with_name("workspace.backup-11")
        shutil.copytree(run.workspace, next_workspace)
        project.workspace.rename(backup_workspace)

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_promote_run_workspace_reports_next_cleanup_failure_after_restoring_current(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = project.workspace.with_name("workspace.next-11")
        backup_workspace = project.workspace.with_name("workspace.backup-11")
        shutil.copytree(run.workspace, next_workspace)
        project.workspace.rename(backup_workspace)

        with patch(
            "specgate.run_storage.shutil.rmtree",
            side_effect=OSError("recovery cleanup failed"),
        ):
            try:
                promote_run_workspace(project, 11)
            except Exception as exc:
                error = exc
            else:
                self.fail("promote_run_workspace did not report cleanup failure")

        self.assertIsInstance(error, RunStorageCleanupError)
        self.assertIn("recovery cleanup failed", str(error))
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertTrue(next_workspace.is_dir())
        self.assertFalse(backup_workspace.exists())

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def workspace_swap_paths(self, project):
        return sorted(
            path
            for path in project.root.iterdir()
            if path.name.startswith("workspace.next-") or path.name.startswith("workspace.backup-")
        )

    def write_ownership_marker(self, root, run_id):
        (root / self.ownership_marker).write_text(
            json.dumps({"run_id": run_id, "schema_version": 1}, sort_keys=True),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
