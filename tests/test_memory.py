import tempfile
import unittest
from pathlib import Path

from specgate.memory import append_memory, load_memory_summary


class MemoryTests(unittest.TestCase):
    def test_append_and_load_memory_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            append_memory(root, passed=True, steps=3, gate_summary="Gate passed after repair")
            summary = load_memory_summary(root)

            self.assertIn("Gate passed after repair", summary)
            self.assertIn("passed=True", summary)
            self.assertTrue((root / "memory.json").exists())


if __name__ == "__main__":
    unittest.main()
