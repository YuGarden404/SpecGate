from __future__ import annotations

import re
import struct
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "FINAL_EVIDENCE_MATRIX.md"
REFLECTION_GUIDE = ROOT / "docs" / "REFLECTION_FACT_CHECK.md"
COLD_START_AUDIT = (
    ROOT
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-07-16-final-compliance-cold-start.md"
)
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
    "src/specgate/llm_config.py",
    "src/specgate/llm_transport.py",
    "src/specgate/web_llm.py",
    "tests/test_runner.py",
    "tests/test_gate.py",
    "tests/test_approvals.py",
    "tests/test_web_runtime.py",
    "tests/test_runtime_config.py",
    "tests/test_llm_config.py",
    "tests/test_llm_transport.py",
    "tests/test_web_llm.py",
    ".gitlab-ci.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/pages.yml",
    "Dockerfile",
)


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def markdown_table_in_section(relative: str, heading: str) -> tuple[tuple[str, ...], ...]:
    text = read_text(relative)
    heading_matches = list(re.finditer(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE))
    if len(heading_matches) != 1:
        raise AssertionError(
            f"expected one {heading!r} section in {relative}, found {len(heading_matches)}"
        )

    section_tail = text[heading_matches[0].end() :]
    next_heading = re.search(r"^##\s+", section_tail, re.MULTILINE)
    section = section_tail[: next_heading.start()] if next_heading else section_tail

    table_blocks: list[list[str]] = []
    current_block: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            current_block.append(line)
        elif current_block:
            table_blocks.append(current_block)
            current_block = []
    if current_block:
        table_blocks.append(current_block)
    if len(table_blocks) != 1:
        raise AssertionError(
            f"expected one Markdown table in {relative} {heading!r}, "
            f"found {len(table_blocks)}"
        )

    return tuple(
        tuple(cell.strip() for cell in line[1:-1].split("|"))
        for line in table_blocks[0]
    )


def requirement_name(requirement: str) -> str:
    name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_dependency_names() -> set[str]:
    data = tomllib.loads(read_text("pyproject.toml"))
    return {
        requirement_name(requirement)
        for requirement in data["project"]["dependencies"]
    }


def direct_dependency_versions() -> dict[str, str]:
    data = tomllib.loads(read_text("pyproject.toml"))
    versions = {}
    for requirement in data["project"]["dependencies"]:
        raw_name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
        constraint = requirement[len(raw_name) :].split(";", maxsplit=1)[0].strip()
        if constraint.startswith("["):
            constraint = constraint.split("]", maxsplit=1)[1].strip()
        versions[requirement_name(requirement)] = constraint
    return versions


class FinalEvidenceTests(unittest.TestCase):
    def test_supplemental_cold_start_records_required_evidence(self):
        self.assertTrue(COLD_START_AUDIT.is_file())
        audit = COLD_START_AUDIT.read_text(encoding="utf-8")
        for heading in (
            "## 验证边界",
            "## Agent 与会话",
            "## 尝试任务",
            "## 暂停与问题",
            "## 实际产出与测试",
            "## 与预期的差异",
            "## SPEC / PLAN 修订",
            "## 时间记录",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, audit)
        for phrase in (
            "最终合规阶段的补充冷启动验证",
            "不替代 2026-07-08",
            "Gemini Web",
            "任务 2",
            "任务 3",
            "任务 2 的步骤 1 和步骤 3",
            "任务 3 的步骤 1 和步骤 4",
            "没有修改任何文件",
            "没有运行任何测试",
            "执行环境前提",
            "约 3 分钟",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, audit)
        for requested_file in (
            "tests/test_final_evidence.py",
            "docs/FINAL_EVIDENCE_MATRIX.md",
            "docs/FINAL_SUBMISSION_CHECKLIST.md",
            "docs/REFLECTION_FACT_CHECK.md",
            "PLAN.md",
            "AGENT_LOG.md",
            "README.md",
        ):
            with self.subTest(requested_file=requested_file):
                self.assertIn(f"`{requested_file}`", audit)

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
            (16, "116cc10", "fa3278a"),
            (17, "d550032", "e73e937"),
            (18, "d3607c4", "8d30ca5"),
            (19, "5279a7c", "b98563a"),
            (20, "e35eb46", "c39d101"),
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

    def test_pr18_through_pr20_release_rows_are_exact_and_unique(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        heading = "## 5. 最近阶段 Git / PR / CI"
        self.assertIn(heading, matrix)
        section = matrix.split(heading, 1)[1].split("\n## ", 1)[0]
        table_rows = [
            tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
            for line in section.splitlines()
            if line.startswith("|")
        ]
        self.assertGreaterEqual(len(table_rows), 2)
        self.assertEqual(
            table_rows[0][:4],
            ("阶段", "功能 commit", "Merge commit", "PR"),
        )

        link_pattern = re.compile(
            r"^\[#(?P<pr>\d+)\]\("
            r"(?P<url>https://github\.com/YuGarden404/SpecGate/pull/(?P=pr))"
            r"\)$"
        )
        sha_pattern = re.compile(r"^`(?P<sha>[0-9a-f]{7})`$")
        releases = []
        for cells in table_rows[2:]:
            self.assertGreaterEqual(len(cells), 4)
            match = link_pattern.fullmatch(cells[3])
            self.assertIsNotNone(match, msg=f"invalid PR cell: {cells[3]}")
            feature_commit = sha_pattern.fullmatch(cells[1])
            merge_commit = sha_pattern.fullmatch(cells[2])
            self.assertIsNotNone(feature_commit, msg=f"invalid feature SHA: {cells[1]}")
            self.assertIsNotNone(merge_commit, msg=f"invalid merge SHA: {cells[2]}")
            releases.append(
                (
                    cells[0],
                    feature_commit.group("sha"),
                    merge_commit.group("sha"),
                    int(match.group("pr")),
                    match.group("url"),
                )
            )

        expected_releases = (
            (
                "后端审计加固",
                "d3607c4",
                "8d30ca5",
                18,
                "https://github.com/YuGarden404/SpecGate/pull/18",
            ),
            (
                "Web 真实 LLM 接入",
                "5279a7c",
                "b98563a",
                19,
                "https://github.com/YuGarden404/SpecGate/pull/19",
            ),
            (
                "真实 LLM 生命周期修复",
                "e35eb46",
                "c39d101",
                20,
                "https://github.com/YuGarden404/SpecGate/pull/20",
            ),
        )
        for expected in expected_releases:
            with self.subTest(pr=expected[3]):
                self.assertEqual(releases.count(expected), 1)
                for column, value in enumerate(expected):
                    self.assertEqual(
                        sum(row[column] == value for row in releases),
                        1,
                        msg=f"release field is not unique: {value}",
                    )

    def test_final_snapshot_uses_pr20_baseline_without_stale_branch_claims(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        snapshot = matrix.split("## 3. 课程交付物", 1)[0]
        self.assertIn("main@c39d101", snapshot)
        self.assertIn("PR #20", snapshot)
        self.assertIn("审查起点完整回归", snapshot)
        self.assertIn("Ran 908 tests in 210.559s", snapshot)
        self.assertIn("OK (skipped=27)", snapshot)
        self.assertIn("最终测试数字将在本阶段结束时刷新", snapshot)
        self.assertIn("CI、Pages 和新截图仍待人工远端核对", snapshot)
        self.assertNotIn("当前未提交分支", snapshot)
        self.assertNotIn("main@e73e937", snapshot)
        self.assertNotIn("Ran 896 tests", snapshot)

    def test_current_release_status_is_consistent_across_factual_materials(self):
        current_sections = {
            "matrix": MATRIX.read_text(encoding="utf-8").split(
                "## 3. 课程交付物", 1
            )[0],
            "checklist": read_text("docs/FINAL_SUBMISSION_CHECKLIST.md"),
            "reflection facts": read_text("docs/REFLECTION_FACT_CHECK.md").split(
                "## 5. 最终证据", 1
            )[1],
            "plan": read_text("PLAN.md").split(
                "# 2026-07-16 最终交付合规修复", 1
            )[1],
            "agent log": read_text("AGENT_LOG.md").split(
                "## 2026-07-16 最终交付合规修复：任务 2", 1
            )[1],
        }
        for document, section in current_sections.items():
            with self.subTest(document=document):
                self.assertIn("审查起点", section)
                self.assertIn("main@c39d101", section)
                self.assertIn("PR #20", section)
                self.assertIn("Ran 908 tests in 210.559s", section)
                self.assertIn("OK (skipped=27)", section)

        pending_markers = {
            "matrix": "仍待人工远端核对",
            "checklist": "仍待人工远端核对",
            "reflection facts": "尚待人工远端核对",
            "plan": "未核对前不标记完成",
            "agent log": "继续标记为待人工核对",
        }
        for document, marker in pending_markers.items():
            with self.subTest(document=document, boundary="remote evidence"):
                self.assertIn(marker, current_sections[document])
                for line in current_sections[document].splitlines():
                    if "PR #20" not in line:
                        continue
                    if not any(term in line for term in ("CI", "Pages", "截图")):
                        continue
                    self.assertFalse(
                        any(
                            term in line
                            for term in (
                                "CI、Pages 和新截图已完成",
                                "CI、Pages 和新截图均通过",
                                "CI、Pages 和新截图为绿色",
                            )
                        ),
                        msg=f"{document} marks pending PR #20 evidence complete: {line}",
                    )

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

    def test_requirement_name_normalizes_supported_requirement_forms(self):
        cases = (
            (
                "Demo.Pkg[crypto]>=1; python_version >= '3.11'",
                "demo-pkg",
            ),
            ("Demo_Pkg @ https://example.invalid/demo_pkg-1.whl", "demo-pkg"),
            ("Demo__Pkg---Extra>=1", "demo-pkg-extra"),
        )
        for requirement, expected in cases:
            with self.subTest(requirement=requirement):
                self.assertEqual(requirement_name(requirement), expected)

    def test_readme_lists_every_direct_dependency_license(self):
        readme = read_text("README.md")
        heading = "## 第三方依赖与许可证"
        self.assertIn(heading, readme)
        section = readme.split(heading, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
        table_lines = [
            line.strip()
            for line in section.splitlines()
            if line.strip().startswith("|")
        ]
        self.assertGreaterEqual(len(table_lines), 2)

        def cells(line: str) -> tuple[str, ...]:
            return tuple(cell.strip() for cell in line.strip("|").split("|"))

        self.assertEqual(
            cells(table_lines[0]),
            ("依赖", "版本范围", "用途", "许可证", "官方项目"),
        )
        self.assertEqual(cells(table_lines[1]), ("---",) * 5)

        rows = []
        for line in table_lines[2:]:
            row = cells(line)
            with self.subTest(line=line, boundary="table shape"):
                self.assertEqual(len(row), 5)
                self.assertTrue(all(row), "dependency table cells must be non-empty")
            if len(row) == 5 and all(row):
                rows.append(row)

        parsed_rows = [
            (
                requirement_name(dependency.strip("`")),
                version.strip("`"),
                purpose,
                license_name,
                url,
            )
            for dependency, version, purpose, license_name, url in rows
        ]
        dependency_names = [row[0] for row in parsed_rows]
        self.assertEqual(
            len(dependency_names),
            len(set(dependency_names)),
            "dependency table contains duplicate names",
        )

        expected_names = direct_dependency_names()
        expected_versions = direct_dependency_versions()
        self.assertEqual(set(expected_versions), expected_names)
        self.assertEqual(set(dependency_names), expected_names)
        rows_by_dependency = {row[0]: row[1:] for row in parsed_rows}
        expected_metadata = {
            "cryptography": (
                "Apache-2.0 OR BSD-3-Clause",
                "https://github.com/pyca/cryptography",
            ),
            "fastapi": ("MIT", "https://github.com/fastapi/fastapi"),
            "httpx": ("BSD-3-Clause", "https://github.com/encode/httpx"),
            "keyring": ("MIT", "https://github.com/jaraco/keyring"),
            "python-multipart": (
                "Apache-2.0",
                "https://github.com/Kludex/python-multipart",
            ),
            "uvicorn": (
                "BSD-3-Clause",
                "https://github.com/Kludex/uvicorn",
            ),
        }
        self.assertEqual(set(expected_metadata), set(expected_versions))
        for dependency, expected_version in expected_versions.items():
            with self.subTest(dependency=dependency, boundary="metadata"):
                version, purpose, license_name, url = rows_by_dependency[dependency]
                self.assertEqual(version, expected_version)
                self.assertTrue(purpose)
                self.assertEqual(license_name, expected_metadata[dependency][0])
                self.assertEqual(url, expected_metadata[dependency][1])

    def test_spec_records_the_actual_open_design_decision(self):
        spec = read_text("SPEC.md")
        self.assertIn("Open Design", spec)
        self.assertIn("未采用", spec)
        self.assertIn("不追溯性声称", spec)

    def test_spec_describes_current_credentials_runtime_and_config(self):
        spec = read_text("SPEC.md")
        for phrase in (
            "操作系统 keyring",
            "AES-256-GCM",
            "固定 worker",
            "有界队列",
            "schema v5",
            "runtime_config_json",
            "llm_config_json",
            "不可变配置快照",
            "Chat Completions",
            "fail closed",
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
            "真实模型",
            "llm_config_json",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertNotIn("支持 `.env` fallback", combined)

    def test_submission_docs_do_not_claim_public_backend_or_registry(self):
        expected_delivery_statuses = {
            "公开静态评审入口": "已完成",
            "本地交互式 WebUI": "已完成",
            "公网交互式 Web 后端": "待完成",
            "Docker 本地与 CI 构建": "已完成",
            "公开容器 registry": "待完成",
        }
        tables = {
            "checklist": (
                markdown_table_in_section(
                    "docs/FINAL_SUBMISSION_CHECKLIST.md",
                    "## 2. 课程交付物对照",
                ),
                ("要求", "状态", "对应文件或证据"),
            ),
            "matrix": (
                markdown_table_in_section(
                    "docs/FINAL_EVIDENCE_MATRIX.md",
                    "## 3. 课程交付物",
                ),
                ("要求", "状态", "仓库证据", "复现方式"),
            ),
        }

        parsed_rows = {}
        for document, (table, expected_header) in tables.items():
            with self.subTest(document=document, boundary="header"):
                self.assertEqual(table[0], expected_header)
            with self.subTest(document=document, boundary="separator"):
                self.assertEqual(len(table[1]), len(expected_header))
                self.assertTrue(all(re.fullmatch(r":?-{3,}:?", cell) for cell in table[1]))

            rows = table[2:]
            for row_number, row in enumerate(rows, start=1):
                with self.subTest(
                    document=document,
                    boundary="column_count",
                    row=row_number,
                ):
                    self.assertEqual(len(row), len(expected_header))

            names = [row[0] for row in rows]
            for name, expected_status in expected_delivery_statuses.items():
                with self.subTest(document=document, requirement=name):
                    self.assertEqual(names.count(name), 1)
                    self.assertEqual(next(row[1] for row in rows if row[0] == name), expected_status)
            for stale_name in ("公开 WebUI URL", "Docker 分发"):
                with self.subTest(document=document, stale_name=stale_name):
                    self.assertNotIn(stale_name, names)
            parsed_rows[document] = {row[0]: row[1] for row in rows}

        expected_screenshot_statuses = {
            "历史 CI/Pages 截图（截至 PR #15/#17）": "已完成",
            "PR #20 后 CI/Pages 与新截图": "待核验",
        }
        for name, expected_status in expected_screenshot_statuses.items():
            with self.subTest(document="checklist", screenshot=name):
                self.assertEqual(parsed_rows["checklist"].get(name), expected_status)

    def test_real_llm_delivery_facts_are_current_and_do_not_require_network(self):
        readme = read_text("README.md")
        deployment = read_text("docs/DEPLOYMENT.md")
        matrix = read_text("docs/FINAL_EVIDENCE_MATRIX.md")
        combined = "\n".join((readme, deployment, matrix))

        for phrase in (
            "默认使用 MockLLM",
            "失败不会降级",
            "SPECGATE_LLM_ALLOWED_HOSTS",
            "SPECGATE_LLM_MAX_OUTPUT_TOKENS",
            "SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS",
            "Fake/Stub",
            "GitHub Pages",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        for stale in (
            "当前 WebUI 仍只运行 MockLLM",
            "保存 API key 不会启用或调用真实模型",
            "保存凭据不会启用或调用真实 LLM",
            "课程验收和 Web 运行仍只使用 `MockLLM`",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, combined)

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
