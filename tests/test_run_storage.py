import json
import os
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import specgate.run_storage as run_storage
import specgate.workspace_fs as workspace_fs
from specgate.run_storage import (
    RunStorageCleanupError,
    initialize_run_storage,
    promote_run_workspace,
    remove_run_storage,
)
from specgate.web_projects import RunPaths, project_paths, web_run_paths
from specgate.workspace_fs import WorkspacePathError


class RunStorageTests(unittest.TestCase):
    ownership_marker = ".specgate-run-owner.json"
    promotion_token = "b" * 64

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

    def test_run_publication_lock_is_exclusive_across_instances(self):
        project = self.make_project()
        first = run_storage.RunPublicationLock(project, 11)
        second = run_storage.RunPublicationLock(project, 11)
        self.assertEqual(first.path, project.runs / ".11.publish.lock")

        first.acquire()
        try:
            self.assertFalse(second.try_acquire())
            with self.assertRaisesRegex(run_storage.RunPublicationLockError, "publication lock"):
                second.acquire()
        finally:
            first.release()

        self.assertTrue(second.try_acquire())
        second.release()

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

    def test_initialize_rejects_mocked_reparse_workspace_root(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("trusted", encoding="utf-8")
        external = project.root.parent / "external"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        real_is_link_like = workspace_fs.is_link_like

        def mark_workspace_reparse(path):
            if Path(path) == project.workspace:
                return True
            return real_is_link_like(path)

        with patch(
            "specgate.workspace_fs.is_link_like",
            side_effect=mark_workspace_reparse,
        ):
            with self.assertRaises(WorkspacePathError) as raised:
                initialize_run_storage(project, 11)

        self.assertEqual(raised.exception.rule_family, "reparse_point")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
        self.assertFalse(web_run_paths(project, 11).root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows publication failure")
    def test_initialize_run_storage_fails_closed_when_windows_rename_is_denied(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        denied = PermissionError(13, "rename denied")
        denied.winerror = 5

        with patch(
            "specgate.workspace_fs._rename_staging_noreplace",
            side_effect=denied,
        ):
            with self.assertRaises(WorkspacePathError) as raised:
                initialize_run_storage(project, 11)

        self.assertEqual(raised.exception.rule_family, "path_race")
        self.assertFalse(web_run_paths(project, 11).root.exists())
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual(len(list(project.runs.glob(".11.specgate-copy-*"))), 1)

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

        with patch(
            "specgate.run_storage.publish_workspace_snapshot",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                initialize_run_storage(project, 11)

        self.assertEqual(list(project.runs.iterdir()), [])

    def test_initialize_run_storage_retains_uncertain_staging_without_recursive_cleanup(self):
        project = self.make_project()
        denied = PermissionError(13, "rename denied")
        denied.winerror = 5
        with (
            patch("specgate.workspace_fs._rename_staging_noreplace", side_effect=denied),
            patch("specgate.run_storage.shutil.rmtree") as rmtree,
        ):
            with self.assertRaises(WorkspacePathError):
                initialize_run_storage(project, 11)

        rmtree.assert_not_called()
        self.assertFalse(web_run_paths(project, 11).root.exists())
        self.assertEqual(len(list(project.runs.glob(".11.specgate-copy-*"))), 1)

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
        next_workspace, backup_workspace = self.promotion_paths(project)
        next_marker = self.read_promotion_marker(next_workspace)
        backup_marker = self.read_promotion_marker(backup_workspace)
        self.assertEqual(next_marker["run_id"], 11)
        self.assertEqual(next_marker["phase"], "next")
        self.assertEqual(backup_marker["phase"], "backup")
        self.assertEqual(next_marker["transaction_token"], backup_marker["transaction_token"])
        self.assertEqual(
            tuple(next_marker["directory_identity"]),
            workspace_fs._stat_identity(project.workspace.lstat()),
        )
        self.assertEqual(next_marker["parent_identity"], backup_marker["parent_identity"])

    def test_promote_uses_transaction_token_in_next_directory_name(self):
        project = self.make_project()
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        token = "a" * 64
        observed = {}

        def capture_copy(_source, destination):
            observed["destination"] = Path(destination)
            raise KeyboardInterrupt("stop after path selection")

        with (
            patch("specgate.run_storage.secrets.token_hex", return_value=token),
            patch("specgate.run_storage.copy_workspace_tree", side_effect=capture_copy),
        ):
            with self.assertRaisesRegex(KeyboardInterrupt, "path selection"):
                promote_run_workspace(project, 11)

        self.assertEqual(
            observed["destination"],
            project.workspace.with_name(f"workspace.next-11-{token}"),
        )

    def test_promote_rejects_unowned_preexisting_next_and_preserves_sentinel(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace, _ = run_storage._promotion_paths(
            project.workspace,
            11,
            self.promotion_token,
        )
        next_workspace.mkdir()
        sentinel = next_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")

        with patch("specgate.run_storage.secrets.token_hex", return_value=self.promotion_token):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
        self.assertEqual(
            (project.workspace / "index.html").read_text(encoding="utf-8"),
            "v1",
        )

    def test_promote_rejects_unowned_preexisting_backup_and_preserves_sentinel(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        _, backup_workspace = run_storage._promotion_paths(
            project.workspace,
            11,
            self.promotion_token,
        )
        backup_workspace.mkdir()
        sentinel = backup_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")

        with patch("specgate.run_storage.secrets.token_hex", return_value=self.promotion_token):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
        self.assertEqual(
            (project.workspace / "index.html").read_text(encoding="utf-8"),
            "v1",
        )

    def test_promote_rejects_wrong_run_marker_and_preserves_next_sentinel(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace, _ = run_storage._promotion_paths(
            project.workspace,
            11,
            self.promotion_token,
        )
        next_workspace.mkdir()
        sentinel = next_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        binding = workspace_fs.bind_workspace_tree(next_workspace)
        marker = {
            "schema_version": 1,
            "run_id": 12,
            "phase": "next",
            "transaction_token": "wrong-run-token",
            "directory_identity": list(binding.identity),
            "parent_identity": list(binding.parent_identity),
        }
        marker_path = run_storage._promotion_marker_path(next_workspace)
        marker_path.write_text(json.dumps(marker), encoding="utf-8")

        with patch("specgate.run_storage.secrets.token_hex", return_value=self.promotion_token):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_promote_rejects_current_replaced_before_bound_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        replacement = project.root.parent / "replacement-current"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = project.root.parent / "displaced-current"
        real_rename = run_storage.rename_workspace_tree_noreplace

        def replace_current(binding, destination):
            binding.path.rename(displaced)
            replacement.rename(binding.path)
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_current,
        ):
            with self.assertRaises(WorkspacePathError):
                promote_run_workspace(project, 11)

        self.assertEqual(
            (project.workspace / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertEqual((displaced / "index.html").read_text(encoding="utf-8"), "v1")

    def test_promote_rejects_next_replaced_before_bound_rename_and_rolls_back(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = None
        replacement = project.root.parent / "replacement-next-before-rename"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = project.root.parent / "displaced-next-before-rename"
        real_rename = run_storage.rename_workspace_tree_noreplace
        calls = 0

        def replace_next(binding, destination):
            nonlocal calls, next_workspace
            calls += 1
            if calls == 2:
                next_workspace = binding.path
                binding.path.rename(displaced)
                replacement.rename(binding.path)
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_next,
        ):
            with self.assertRaises(WorkspacePathError):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual(
            (next_workspace / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertEqual((displaced / "index.html").read_text(encoding="utf-8"), "v2")

    def test_promote_rejects_parent_replaced_before_bound_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        replacement_root = project.root.with_name("replacement-project-root")
        replacement_workspace = replacement_root / "workspace"
        replacement_workspace.mkdir(parents=True)
        sentinel = replacement_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced_root = project.root.with_name("displaced-project-root")
        real_rename = run_storage.rename_workspace_tree_noreplace

        def replace_parent(binding, destination):
            project.root.rename(displaced_root)
            replacement_root.rename(project.root)
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_parent,
        ):
            with self.assertRaises(WorkspacePathError):
                promote_run_workspace(project, 11)

        self.assertEqual(
            (project.workspace / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertEqual(
            (displaced_root / "workspace" / "index.html").read_text(encoding="utf-8"),
            "v1",
        )

    def test_promote_reloads_markers_before_first_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = None
        displaced_marker = project.root.parent / "displaced-next-marker.json"
        real_commit = run_storage._commit_workspace_promotion

        def replace_marker_before_commit(current, next_binding, backup, run_id, token):
            nonlocal next_workspace
            next_workspace = next_binding.path
            marker_path = run_storage._promotion_marker_path(next_workspace)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker_path.rename(displaced_marker)
            marker["transaction_token"] = "wrong-token"
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            return real_commit(current, next_binding, backup, run_id, token)

        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=replace_marker_before_commit,
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((next_workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(
            self.read_promotion_marker(next_workspace)["transaction_token"],
            "wrong-token",
        )
        self.assertTrue(displaced_marker.is_file())

    def test_promote_revalidates_next_marker_after_publish_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        real_rename = run_storage.rename_workspace_tree_noreplace
        calls = 0

        def replace_marker_after_publish(binding, destination):
            nonlocal calls
            calls += 1
            moved = real_rename(binding, destination)
            if calls == 2:
                marker_path = run_storage._promotion_marker_path(binding.path)
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker["transaction_token"] = "f" * 64
                marker_path.unlink()
                marker_path.write_text(json.dumps(marker), encoding="utf-8")
            return moved

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_marker_after_publish,
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        quarantines = list(project.root.glob(".workspace.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual((quarantines[0] / "index.html").read_text(encoding="utf-8"), "v2")

    def test_promote_quarantines_current_replaced_after_publish_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        replacement = project.root / "replacement-after-publish"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = project.root / "displaced-published-workspace"
        real_rename = run_storage.rename_workspace_tree_noreplace
        calls = 0

        def replace_current_after_publish(binding, destination):
            nonlocal calls
            calls += 1
            moved = real_rename(binding, destination)
            if calls == 2:
                moved.path.rename(displaced)
                replacement.rename(moved.path)
            return moved

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_current_after_publish,
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        quarantines = list(project.root.glob(".workspace.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(
            (quarantines[0] / "sentinel.txt").read_text(encoding="utf-8"),
            "external sentinel",
        )
        self.assertEqual((displaced / "index.html").read_text(encoding="utf-8"), "v2")

    def test_promote_run_workspace_restores_project_workspace_when_publish_rename_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        (project.workspace / "old.txt").write_text("old", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        (run.workspace / "new.txt").write_text("new", encoding="utf-8")

        original_rename = run_storage.rename_workspace_tree_noreplace
        rename_calls = []

        def fail_second_rename(binding, target):
            rename_calls.append((binding.path, Path(target)))
            if len(rename_calls) == 2:
                raise OSError("publish rename failed")
            return original_rename(binding, target)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=fail_second_rename,
        ):
            with self.assertRaisesRegex(OSError, "publish rename failed"):
                promote_run_workspace(project, 11)

        self.assertEqual(len(rename_calls), 4)
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((project.workspace / "old.txt").read_text(encoding="utf-8"), "old")
        self.assertFalse((project.workspace / "new.txt").exists())
        self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])
        quarantines = list(project.root.glob(".workspace.next-11-*.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual((quarantines[0] / "new.txt").read_text(encoding="utf-8"), "new")

    def test_promote_run_workspace_keeps_committed_current_when_backup_cleanup_partially_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        backup_workspace = None
        replacement = project.root.parent / "replacement-backup"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = project.root.parent / "displaced-backup"
        real_rename = run_storage.rename_workspace_tree_noreplace
        calls = 0

        def replace_backup_before_quarantine(binding, destination):
            nonlocal calls, backup_workspace
            calls += 1
            if calls == 3:
                backup_workspace = binding.path
                binding.path.rename(displaced)
                replacement.rename(binding.path)
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_backup_before_quarantine,
        ):
            with self.assertWarnsRegex(RuntimeWarning, "backup.*quarantine failed"):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual((backup_workspace / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
        self.assertEqual((displaced / "index.html").read_text(encoding="utf-8"), "v1")
        with self.assertRaises(run_storage.RunStorageOwnershipError):
            promote_run_workspace(project, 11)

    def test_promote_run_workspace_keeps_backup_marker_when_committed_next_cleanup_fails(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace = None
        replacement = project.root.parent / "replacement-next"
        replacement.mkdir()
        sentinel = replacement / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        displaced = project.root.parent / "displaced-next"
        real_rename = run_storage.rename_workspace_tree_noreplace
        calls = 0

        def fail_publish_then_replace_next(binding, destination):
            nonlocal calls, next_workspace
            calls += 1
            if calls == 2:
                raise OSError("publish rename failed")
            if calls == 4:
                next_workspace = binding.path
                binding.path.rename(displaced)
                replacement.rename(binding.path)
            return real_rename(binding, destination)

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=fail_publish_then_replace_next,
        ):
            try:
                promote_run_workspace(project, 11)
            except OSError as exc:
                error = exc
            else:
                self.fail("promotion did not fail")

        self.assertTrue(
            any("next quarantine failed" in note for note in getattr(error, "__notes__", ()))
        )
        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((next_workspace / "sentinel.txt").read_text(encoding="utf-8"), "external sentinel")
        self.assertEqual((displaced / "index.html").read_text(encoding="utf-8"), "v2")

    def test_promote_run_workspace_recovers_stale_next_before_retry(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        real_copy = run_storage.copy_workspace_tree
        with patch("specgate.run_storage.copy_workspace_tree", wraps=real_copy) as copy_tree:
            with patch(
                "specgate.run_storage._commit_workspace_promotion",
                side_effect=KeyboardInterrupt("interrupted before commit"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    promote_run_workspace(project, 11)

            promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(copy_tree.call_count, 1)
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_recovery_rejects_sidecar_tokens_conflicting_with_transaction(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=KeyboardInterrupt("interrupted before commit"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                promote_run_workspace(project, 11)

        next_workspace, backup_workspace = self.promotion_paths(project)
        for path in (next_workspace, backup_workspace):
            marker_path = run_storage._promotion_marker_path(path)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["transaction_token"] = "f" * 64
            marker_path.unlink()
            marker_path.write_text(json.dumps(marker), encoding="utf-8")

        with self.assertRaises(run_storage.RunStorageOwnershipError):
            promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((next_workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertFalse(backup_workspace.exists())

    def test_recovery_preserves_next_when_ownership_marker_is_missing(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=KeyboardInterrupt("interrupted before commit"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                promote_run_workspace(project, 11)

        next_workspace, _ = self.promotion_paths(project)
        run_storage._promotion_marker_path(next_workspace).unlink()

        with self.assertRaises(run_storage.RunStorageOwnershipError):
            promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual((next_workspace / "index.html").read_text(encoding="utf-8"), "v2")

    def test_recovery_preserves_evidence_when_canonical_target_is_occupied(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        backup_workspace = None

        def interrupt_after_backup(current_binding, _next_binding, backup, _run_id, _token):
            nonlocal backup_workspace
            backup_workspace = Path(backup)
            run_storage.rename_workspace_tree_noreplace(current_binding, backup)
            raise KeyboardInterrupt("interrupted after backup")

        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=interrupt_after_backup,
        ):
            with self.assertRaises(KeyboardInterrupt):
                promote_run_workspace(project, 11)

        project.workspace.mkdir()
        sentinel = project.workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        with self.assertRaises(run_storage.RunStorageOwnershipError):
            promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")
        self.assertEqual((backup_workspace / "index.html").read_text(encoding="utf-8"), "v1")

    def test_promote_run_workspace_recovers_backup_when_current_is_missing(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        backup_workspace = None

        def interrupt_after_backup(current_binding, _next_binding, backup, _run_id, _token):
            nonlocal backup_workspace
            backup_workspace = Path(backup)
            run_storage.rename_workspace_tree_noreplace(current_binding, backup)
            raise KeyboardInterrupt("interrupted after backup")

        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=interrupt_after_backup,
        ):
            with self.assertRaises(KeyboardInterrupt):
                promote_run_workspace(project, 11)

        self.assertFalse(project.workspace.exists())
        self.assertTrue(backup_workspace.is_dir())

        promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual(self.workspace_swap_paths(project), [])

    def test_current_missing_recovery_revalidates_marker_after_publish_rename(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        backup_workspace = None

        def interrupt_after_backup(current_binding, _next_binding, backup, _run_id, _token):
            nonlocal backup_workspace
            backup_workspace = Path(backup)
            run_storage.rename_workspace_tree_noreplace(current_binding, backup)
            raise KeyboardInterrupt("interrupted after backup")

        with patch(
            "specgate.run_storage._commit_workspace_promotion",
            side_effect=interrupt_after_backup,
        ):
            with self.assertRaises(KeyboardInterrupt):
                promote_run_workspace(project, 11)

        next_workspace, _ = self.promotion_paths(project)
        marker_path = run_storage._promotion_marker_path(next_workspace)
        real_rename = run_storage.rename_workspace_tree_noreplace

        def replace_marker_after_recovery_rename(binding, destination):
            moved = real_rename(binding, destination)
            if Path(destination) == project.workspace:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker["transaction_token"] = "f" * 64
                marker_path.unlink()
                marker_path.write_text(json.dumps(marker), encoding="utf-8")
            return moved

        with patch(
            "specgate.run_storage.rename_workspace_tree_noreplace",
            side_effect=replace_marker_after_recovery_rename,
        ):
            with self.assertRaises(run_storage.RunStoragePostRenameError):
                promote_run_workspace(project, 11)

        self.assertFalse(project.workspace.exists())
        self.assertEqual((backup_workspace / "index.html").read_text(encoding="utf-8"), "v1")
        quarantines = list(project.root.glob(".workspace.specgate-quarantine-*"))
        self.assertEqual(len(quarantines), 1)
        self.assertEqual((quarantines[0] / "index.html").read_text(encoding="utf-8"), "v2")

    def test_current_missing_recovery_rejects_each_marker_binding_mismatch(self):
        mutations = {
            "missing": None,
            "run_id": lambda marker: marker.__setitem__("run_id", 12),
            "phase": lambda marker: marker.__setitem__("phase", "backup"),
            "directory_identity": lambda marker: marker.__setitem__(
                "directory_identity", [-1, -1]
            ),
            "parent_identity": lambda marker: marker.__setitem__("parent_identity", [-1, -1]),
        }
        for description, mutate in mutations.items():
            with self.subTest(description=description):
                project = self.make_project()
                (project.workspace / "index.html").write_text("v1", encoding="utf-8")
                run = initialize_run_storage(project, 11)
                (run.workspace / "index.html").write_text("v2", encoding="utf-8")
                backup_workspace = None

                def interrupt_after_backup(
                    current_binding,
                    _next_binding,
                    backup,
                    _run_id,
                    _token,
                ):
                    nonlocal backup_workspace
                    backup_workspace = Path(backup)
                    run_storage.rename_workspace_tree_noreplace(current_binding, backup)
                    raise KeyboardInterrupt("interrupted after backup")

                with patch(
                    "specgate.run_storage._commit_workspace_promotion",
                    side_effect=interrupt_after_backup,
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        promote_run_workspace(project, 11)

                next_workspace, _ = self.promotion_paths(project)
                marker_path = run_storage._promotion_marker_path(next_workspace)
                real_rename = run_storage.rename_workspace_tree_noreplace

                def alter_marker_after_rename(binding, destination):
                    moved = real_rename(binding, destination)
                    if Path(destination) == project.workspace:
                        if mutate is None:
                            marker_path.unlink()
                        else:
                            marker = json.loads(marker_path.read_text(encoding="utf-8"))
                            mutate(marker)
                            marker_path.unlink()
                            marker_path.write_text(json.dumps(marker), encoding="utf-8")
                    return moved

                with patch(
                    "specgate.run_storage.rename_workspace_tree_noreplace",
                    side_effect=alter_marker_after_rename,
                ):
                    with self.assertRaises(run_storage.RunStoragePostRenameError):
                        promote_run_workspace(project, 11)

                self.assertFalse(project.workspace.exists())
                self.assertEqual(
                    (backup_workspace / "index.html").read_text(encoding="utf-8"),
                    "v1",
                )
                quarantines = list(project.root.glob(".workspace.specgate-quarantine-*"))
                self.assertEqual(len(quarantines), 1)
                self.assertEqual(
                    (quarantines[0] / "index.html").read_text(encoding="utf-8"),
                    "v2",
                )

    def test_promote_run_workspace_reports_next_cleanup_failure_after_restoring_current(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        next_workspace, _ = run_storage._promotion_paths(
            project.workspace,
            11,
            self.promotion_token,
        )
        real_is_link_like = workspace_fs.is_link_like

        def mark_next_reparse(path):
            if Path(path) == next_workspace:
                return True
            return real_is_link_like(path)

        next_workspace.mkdir()
        sentinel = next_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        with (
            patch("specgate.run_storage.secrets.token_hex", return_value=self.promotion_token),
            patch.object(workspace_fs, "is_link_like", side_effect=mark_next_reparse),
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_promote_rejects_mocked_reparse_backup_and_preserves_sentinel(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        _, backup_workspace = run_storage._promotion_paths(
            project.workspace,
            11,
            self.promotion_token,
        )
        backup_workspace.mkdir()
        sentinel = backup_workspace / "sentinel.txt"
        sentinel.write_text("external sentinel", encoding="utf-8")
        real_is_link_like = workspace_fs.is_link_like

        def mark_backup_reparse(path):
            if Path(path) == backup_workspace:
                return True
            return real_is_link_like(path)

        with (
            patch("specgate.run_storage.secrets.token_hex", return_value=self.promotion_token),
            patch.object(workspace_fs, "is_link_like", side_effect=mark_backup_reparse),
        ):
            with self.assertRaises(run_storage.RunStorageOwnershipError):
                promote_run_workspace(project, 11)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "external sentinel")

    def test_backup_cleanup_reloads_marker_and_rejects_replaced_token(self):
        project = self.make_project()
        (project.workspace / "index.html").write_text("v1", encoding="utf-8")
        run = initialize_run_storage(project, 11)
        (run.workspace / "index.html").write_text("v2", encoding="utf-8")
        backup_workspace = None
        displaced_marker = project.root.parent / "displaced-backup-marker.json"
        real_cleanup = run_storage._quarantine_committed_phase

        def replace_marker_before_cleanup(state, token):
            nonlocal backup_workspace
            backup_workspace = state.path
            state.marker_path.rename(displaced_marker)
            replacement = dict(state.marker)
            replacement["transaction_token"] = "wrong-token"
            state.marker_path.write_text(json.dumps(replacement), encoding="utf-8")
            return real_cleanup(state, token)

        with patch(
            "specgate.run_storage._quarantine_committed_phase",
            side_effect=replace_marker_before_cleanup,
        ):
            with self.assertWarnsRegex(RuntimeWarning, "backup.*quarantine failed"):
                promote_run_workspace(project, 11)

        self.assertEqual((project.workspace / "index.html").read_text(encoding="utf-8"), "v2")
        self.assertEqual((backup_workspace / "index.html").read_text(encoding="utf-8"), "v1")
        self.assertEqual(
            self.read_promotion_marker(backup_workspace)["transaction_token"],
            "wrong-token",
        )
        self.assertTrue(displaced_marker.is_file())

    def workspace_swap_paths(self, project):
        return sorted(
            path
            for path in project.root.iterdir()
            if path.name.startswith("workspace.next-") or path.name.startswith("workspace.backup-")
        )

    def promotion_paths(self, project, run_id=11):
        transaction_path = run_storage._promotion_transaction_path(project.workspace, run_id)
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        return run_storage._promotion_paths(
            project.workspace,
            run_id,
            transaction["transaction_token"],
        )

    def write_ownership_marker(self, root, run_id):
        (root / self.ownership_marker).write_text(
            json.dumps({"run_id": run_id, "schema_version": 1}, sort_keys=True),
            encoding="utf-8",
        )

    def read_promotion_marker(self, path):
        marker = path.with_name(f".{path.name}.specgate-owner.json")
        return json.loads(marker.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
