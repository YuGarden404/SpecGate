from __future__ import annotations

import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "FINAL_EVIDENCE_MATRIX.md"
REFLECTION_GUIDE = ROOT / "docs" / "REFLECTION_FACT_CHECK.md"
SCREENSHOTS = (
    ROOT / "docs" / "evidence" / "github-actions-web-runtime-and-credentials.png",
    ROOT / "docs" / "evidence" / "github-actions-runtime-config.png",
)
KEY_EVIDENCE_PATHS = (
    "src/specgate/runner.py",
    "src/specgate/actions.py",
    "src/specgate/tools.py",
    "src/specgate/policy.py",
    "src/specgate/gate.py",
    "src/specgate/approvals.py",
    "src/specgate/context.py",
    "src/specgate/credentials.py",
    "src/specgate/web_credentials.py",
    "src/specgate/web_runtime.py",
    "src/specgate/runtime_config.py",
    "tests/test_runner.py",
    "tests/test_gate.py",
    "tests/test_approvals.py",
    "tests/test_web_runtime.py",
    "tests/test_runtime_config.py",
    ".gitlab-ci.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/pages.yml",
    "Dockerfile",
)


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class FinalEvidenceTests(unittest.TestCase):
    def test_required_evidence_artifacts_exist_and_pngs_are_readable(self):
        self.assertTrue(MATRIX.is_file())
        self.assertTrue(REFLECTION_GUIDE.is_file())
        for screenshot in SCREENSHOTS:
            with self.subTest(screenshot=screenshot.name):
                raw = screenshot.read_bytes()
                self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreaterEqual(len(raw), 24)
                width, height = struct.unpack(">II", raw[16:24])
                self.assertGreaterEqual(width, 1000)
                self.assertGreaterEqual(height, 500)

    def test_release_chain_and_screenshot_links_are_recorded(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        releases = (
            (11, "e17b8e5", "f2b4e88"),
            (12, "fecc5e3", "80be31b"),
            (13, "20c0102", "73fbb34"),
            (14, "e5fc981", "49f66a2"),
            (15, "a523137", "f45e73a"),
        )
        for pr, feature_commit, merge_commit in releases:
            with self.subTest(pr=pr):
                self.assertIn(
                    f"https://github.com/YuGarden404/SpecGate/pull/{pr}",
                    matrix,
                )
                self.assertIn(feature_commit, matrix)
                self.assertIn(merge_commit, matrix)
        for screenshot in SCREENSHOTS:
            self.assertIn(f"evidence/{screenshot.name}", matrix)

    def test_readme_has_required_delivery_sections(self):
        readme = read_text("README.md")
        for heading in (
            "## 评审快速入口",
            "## 安装",
            "## 本地测试",
            "## Mock Demo",
            "## 目录结构",
            "## Docker / 服务器部署",
            "## 已知限制",
            "## 安全边界",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, readme)
        self.assertIn("docs/FINAL_EVIDENCE_MATRIX.md", readme)

    def test_spec_describes_current_credentials_runtime_and_config(self):
        spec = read_text("SPEC.md")
        for phrase in (
            "操作系统 keyring",
            "AES-256-GCM",
            "固定 worker",
            "有界队列",
            "schema v4",
            "runtime_config_json",
            "不可变配置快照",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, spec)
        for stale in (
            "`.env` 只作为本地开发 fallback",
            "实现 `.env` 本地开发 fallback",
            "WebUI 是静态报告站点",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, spec)

    def test_final_review_docs_describe_current_boundaries(self):
        combined = "\n".join(
            read_text(path)
            for path in (
                "docs/FINAL_SUBMISSION_CHECKLIST.md",
                "docs/PROJECT_WALKTHROUGH.md",
                "docs/AI4SE_Lab_9_12_Alignment.md",
            )
        )
        for phrase in (
            "AES-256-GCM",
            "WebRuntimeCoordinator",
            "runtime_config_json",
            "HITL",
            "MockLLM",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertNotIn("支持 `.env` fallback", combined)

    def test_matrix_references_existing_implementation_and_test_paths(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        for relative in KEY_EVIDENCE_PATHS:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(f"`{relative}`", matrix)

    def test_reflection_remains_student_owned(self):
        reflection = read_text("REFLECTION.md")
        guide = REFLECTION_GUIDE.read_text(encoding="utf-8")
        self.assertIn("本文件由学生本人完成", reflection)
        self.assertIn("不提供可直接替换的反思段落", guide)
        self.assertIn("由学生本人修改", guide)


if __name__ == "__main__":
    unittest.main()
