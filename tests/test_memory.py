import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specgate.memory import append_memory, load_memory_summary
from specgate.workspace_fs import WorkspacePathError


class MemoryTests(unittest.TestCase):
    def test_memory_propagates_safe_read_boundary_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            error = WorkspacePathError("unsafe memory", "reparse_point")

            with mock.patch(
                "specgate.workspace_fs.read_optional_workspace_text",
                side_effect=error,
            ) as safe_read:
                with self.assertRaises(WorkspacePathError) as raised:
                    load_memory_summary(root)

            self.assertIs(raised.exception, error)
            safe_read.assert_called_once_with(root, "memory.json", encoding="utf-8")

    def test_memory_rejects_link_without_overwriting_external_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "memory.json"
            external.write_text('{"runs": []}', encoding="utf-8")
            link = root / "memory.json"
            try:
                link.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(WorkspacePathError):
                append_memory(root, True, 1, "done")

            self.assertEqual(external.read_text(encoding="utf-8"), '{"runs": []}')

    def test_append_and_load_memory_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            append_memory(root, passed=True, steps=3, gate_summary="Gate passed after repair")
            summary = load_memory_summary(root)

            self.assertIn("Gate passed after repair", summary)
            self.assertIn("passed=True", summary)
            self.assertTrue((root / "memory.json").exists())

    def test_memory_redacts_secret_like_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            append_memory(root, passed=False, steps=1, gate_summary="bad sk-secret123456")
            summary = load_memory_summary(root)

            self.assertNotIn("sk-secret123456", summary)
            self.assertIn("[REDACTED]", summary)


if __name__ == "__main__":
    unittest.main()
