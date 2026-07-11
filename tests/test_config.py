import tempfile
import unittest
from pathlib import Path

from specgate.config import load_policy, load_workspace_config


class ConfigTests(unittest.TestCase):
    def write_config(self, governance_lines):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "specgate.toml"
        path.write_text(
            "\n".join(
                [
                    "[policy]",
                    'allowed_actions = ["read_file", "replace_file", "finish"]',
                    'allowed_read_paths = ["README.md"]',
                    'allowed_write_paths = ["README.md"]',
                    "",
                    "[governance]",
                    *governance_lines,
                ]
            ),
            encoding="utf-8-sig",
        )
        self.addCleanup(tmp.cleanup)
        return path

    def test_load_workspace_config_reads_policy_and_governance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specgate.toml"
            path.write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["read_file", "write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "src/**"]',
                        'allowed_write_paths = ["src/**"]',
                        "",
                        "[governance]",
                        'profile = "review"',
                        'review_actions = ["write_file"]',
                        'review_paths = ["src/**"]',
                        'blocked_paths = [".env", "secrets/**"]',
                    ]
                ),
                encoding="utf-8-sig",
            )

            config = load_workspace_config(path)

            self.assertEqual(config.policy.root, path.parent)
            self.assertIn("write_file", config.policy.allowed_actions)
            self.assertIn("src/**", config.policy.allowed_write_paths)
            self.assertEqual(config.governance.profile, "review")
            self.assertEqual(config.governance.review_actions, {"write_file"})
            self.assertEqual(config.governance.review_paths, {"src/**"})
            self.assertEqual(config.governance.blocked_paths, {".env", "secrets/**"})

    def test_load_workspace_config_reads_context_retrieval_compression_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specgate.toml"
            path.write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["read_file", "write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "src/**"]',
                        'allowed_write_paths = ["src/**"]',
                        "",
                        "[context]",
                        'strategy = "rag-select"',
                        "budget_chars = 9000",
                        "",
                        "[retrieval]",
                        "top_k = 3",
                        "chunk_lines = 12",
                        "chunk_overlap_lines = 2",
                        "max_chunk_chars = 1000",
                        "",
                        "[compression]",
                        "enabled = true",
                        "max_tool_result_chars = 300",
                        "",
                        "[isolation]",
                        "enabled = true",
                        'roles = ["planner", "implementer", "reviewer"]',
                    ]
                ),
                encoding="utf-8-sig",
            )

            config = load_workspace_config(path)

            self.assertEqual(config.context.strategy, "rag-select")
            self.assertEqual(config.context.budget_chars, 9000)
            self.assertEqual(config.retrieval.top_k, 3)
            self.assertEqual(config.retrieval.chunk_lines, 12)
            self.assertEqual(config.retrieval.chunk_overlap_lines, 2)
            self.assertEqual(config.retrieval.max_chunk_chars, 1000)
            self.assertTrue(config.compression.enabled)
            self.assertEqual(config.compression.max_tool_result_chars, 300)
            self.assertTrue(config.isolation.enabled)
            self.assertEqual(config.isolation.roles, ["planner", "implementer", "reviewer"])

    def test_load_workspace_config_accepts_multi_agent_isolated_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                '[context]\nstrategy = "multi-agent-isolated"\n',
                encoding="utf-8",
            )

            config = load_workspace_config(root)

            self.assertEqual(config.context.strategy, "multi-agent-isolated")

    def test_load_workspace_config_rejects_non_positive_retrieval_top_k(self):
        path = self.write_config(
            [
                "",
                "[retrieval]",
                "top_k = 0",
            ]
        )

        with self.assertRaises(ValueError):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_chunk_overlap_at_least_chunk_lines(self):
        path = self.write_config(
            [
                "",
                "[retrieval]",
                "chunk_lines = 12",
                "chunk_overlap_lines = 12",
            ]
        )

        with self.assertRaises(ValueError):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_non_positive_context_budget_chars(self):
        path = self.write_config(
            [
                "",
                "[context]",
                "budget_chars = 0",
            ]
        )

        with self.assertRaises(ValueError):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_bare_string_review_actions(self):
        path = self.write_config(['review_actions = "replace_file"'])

        with self.assertRaises((ValueError, TypeError)):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_bare_string_review_paths(self):
        path = self.write_config(['review_paths = "README.md"'])

        with self.assertRaises((ValueError, TypeError)):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_bare_string_blocked_paths(self):
        path = self.write_config(['blocked_paths = ".env"'])

        with self.assertRaises((ValueError, TypeError)):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_non_string_review_actions(self):
        path = self.write_config(['review_actions = ["replace_file", 123]'])

        with self.assertRaises((ValueError, TypeError)):
            load_workspace_config(path)

    def test_load_workspace_config_rejects_unknown_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "specgate.toml"
            path.write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["finish"]',
                        'allowed_read_paths = []',
                        'allowed_write_paths = []',
                        "",
                        "[governance]",
                        'profile = "unknown"',
                    ]
                ),
                encoding="utf-8-sig",
            )

            with self.assertRaises(ValueError):
                load_workspace_config(path)

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
