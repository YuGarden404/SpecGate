import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specgate.snapshot import FileSnapshot
from specgate.workspace_fs import WorkspacePathError


class FileSnapshotTests(unittest.TestCase):
    def _symlink_or_skip(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def test_allows_existing_file_when_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")

            snapshot = FileSnapshot.capture(root, {"index.html"})
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.reason, "unchanged")

    def test_blocks_existing_file_when_content_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("external edit", encoding="utf-8")
            decision = snapshot.check_unchanged("index.html")

            self.assertFalse(decision.allowed)
            self.assertIn("file changed since run started", decision.reason)

    def test_allows_missing_file_when_still_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            snapshot = FileSnapshot.capture(root, {"index.html"})
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.reason, "unchanged")

    def test_blocks_missing_file_when_it_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("created outside", encoding="utf-8")
            decision = snapshot.check_unchanged("index.html")

            self.assertFalse(decision.allowed)
            self.assertIn("file changed since run started", decision.reason)

    def test_blocks_path_not_in_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            decision = snapshot.check_unchanged("other.html")

            self.assertFalse(decision.allowed)
            self.assertIn("not in snapshot", decision.reason)

    def test_update_after_write_refreshes_trusted_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("written by harness", encoding="utf-8")
            snapshot.update_after_write("index.html")
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)

    def test_capture_rejects_external_link_with_stable_rule_family(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "outside.txt"
            external.write_text("EXTERNAL_SNAPSHOT_SENTINEL", encoding="utf-8")
            self._symlink_or_skip(root / "index.html", external)

            with self.assertRaises(WorkspacePathError) as raised:
                FileSnapshot.capture(root, {"index.html"})

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_capture_propagates_safe_state_link_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "specgate.workspace_fs.workspace_file_state",
                side_effect=WorkspacePathError("linked target", "linked_path"),
            ):
                with self.assertRaises(WorkspacePathError) as raised:
                    FileSnapshot.capture(Path(tmp), {"index.html"})

            self.assertEqual(raised.exception.rule_family, "linked_path")

    def test_check_blocks_ancestor_replacement_without_following_external_tree(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (nested / "index.html").write_text("same bytes", encoding="utf-8")
            snapshot = FileSnapshot.capture(root, {"nested/index.html"})
            external = Path(outside)
            (external / "index.html").write_text("same bytes", encoding="utf-8")
            nested.rename(root / "original-nested")
            self._symlink_or_skip(root / "nested", external, directory=True)

            decision = snapshot.check_unchanged("nested/index.html")

            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule_family, "linked_path")

    def test_check_reports_safe_state_path_race_stably(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("safe", encoding="utf-8")
            snapshot = FileSnapshot.capture(root, {"index.html"})

            with mock.patch(
                "specgate.workspace_fs.workspace_file_state",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                decision = snapshot.check_unchanged("index.html")

            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule_family, "path_race")


if __name__ == "__main__":
    unittest.main()
