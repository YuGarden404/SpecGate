import tempfile
import unittest
from pathlib import Path

from specgate.snapshot import FileSnapshot


class FileSnapshotTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
