import tempfile
import unittest
from pathlib import Path

from specgate.config import load_policy


class ConfigTests(unittest.TestCase):
    def test_load_policy_accepts_utf8_bom_written_by_windows_powershell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specgate.toml"
            path.write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]',
                        'allowed_write_paths = ["index.html"]',
                    ]
                ),
                encoding="utf-8-sig",
            )

            policy = load_policy(path)

            self.assertIn("write_file", policy.allowed_actions)
            self.assertIn("index.html", policy.allowed_write_paths)


if __name__ == "__main__":
    unittest.main()
