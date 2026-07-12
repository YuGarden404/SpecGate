from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "src" / "specgate" / "web_static"


def read_static(filename: str) -> str:
    path = STATIC_DIR / filename
    if not path.is_file():
        raise AssertionError(f"{filename} should exist")
    return path.read_text(encoding="utf-8")


class WebStaticTests(unittest.TestCase):
    def test_static_assets_exist(self) -> None:
        for filename in ("index.html", "styles.css", "app.js"):
            with self.subTest(filename=filename):
                self.assertTrue((STATIC_DIR / filename).is_file())

    def test_index_contains_required_regions(self) -> None:
        html = read_static("index.html")
        for element_id in (
            "auth-view",
            "workspace-view",
            "project-list",
            "message-list",
            "detail-panel",
            "run-form",
            "project-dialog",
            "project-form",
            "settings-detail",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)

    def test_index_contains_report_detail_tab(self) -> None:
        html = read_static("index.html")
        self.assertIn('data-tab="report"', html)

    def test_index_contains_audit_detail_tab(self) -> None:
        html = read_static("index.html")
        self.assertIn('data-tab="audit"', html)

    def test_index_version_tags_static_assets(self) -> None:
        html = read_static("index.html")

        self.assertIn('/styles.css?v=', html)
        self.assertIn('/app.js?v=', html)

    def test_app_exports_required_workflow_functions(self) -> None:
        app_js = read_static("app.js")
        for function_name in (
            "startRun",
            "loadLatestProjectRun",
            "loadSettings",
            "approveApproval",
            "denyApproval",
            "resumeRun",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"async function {function_name}", app_js)

    def test_app_contains_report_render_workflow(self) -> None:
        app_js = read_static("app.js")
        self.assertIn('state.activeTab === "report"', app_js)
        self.assertIn("function renderReportDetail", app_js)
        self.assertIn("latest_run_id", app_js)

    def test_app_contains_audit_render_workflow(self) -> None:
        app_js = read_static("app.js")
        self.assertIn('state.activeTab === "audit"', app_js)
        self.assertIn("async function loadRunDebug", app_js)
        self.assertIn("function renderAuditDetail", app_js)
        self.assertIn("/debug", app_js)

    def test_app_contains_chinese_audit_visualization_helpers(self) -> None:
        app_js = read_static("app.js")
        for text in ("运行概览", "关键指标", "执行流程", "Evidence 状态", "原始 JSON"):
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        for function_name in (
            "renderAuditMetrics",
            "renderAuditTimeline",
            "translateRunStatus",
            "translateTrustLevel",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"function {function_name}", app_js)

    def test_app_contains_audit_strategy_display(self) -> None:
        app_js = read_static("app.js")
        for text in ("治理策略", "上下文策略", "运行模式"):
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        self.assertIn("function auditRunStrategy", app_js)

    def test_app_contains_status_run_workspace_helpers(self) -> None:
        app_js = read_static("app.js")
        for function_name in (
            "renderRunWorkspace",
            "renderRunWorkspaceMetrics",
            "renderRunWorkspaceFlow",
            "renderRunWorkspaceArtifacts",
            "renderRunWorkspaceApprovals",
            "formatBytes",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"function {function_name}", app_js)
        for text in ("运行工作台", "执行流程", "产物", "前往审批", "暂无产物"):
            with self.subTest(text=text):
                self.assertIn(text, app_js)

    def test_app_does_not_execute_artifact_html_in_same_origin_iframe(self) -> None:
        app_js = read_static("app.js").lower()
        self.assertNotIn("<iframe", app_js)
        self.assertNotIn("iframe", app_js)
        self.assertNotIn("artifacts/index", app_js.replace("fetch(", ""))

    def test_styles_include_codex_like_layout_hooks(self) -> None:
        css = read_static("styles.css")
        for selector in (".sidebar", ".conversation", ".detail-panel", ".composer"):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

    def test_styles_include_audit_visualization_hooks(self) -> None:
        css = read_static("styles.css")
        for selector in (".audit-metrics", ".audit-timeline", ".audit-event"):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)
        self.assertIn("flex-wrap: wrap", css)
        self.assertNotIn("grid-template-columns: repeat(6, 1fr)", css)

    def test_styles_include_run_workspace_hooks(self) -> None:
        css = read_static("styles.css")
        for selector in (
            ".run-workspace",
            ".run-workspace-grid",
            ".run-flow",
            ".run-flow-item",
            ".artifact-list",
            ".artifact-item",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

    def test_styles_preserve_hidden_attribute_for_view_switching(self) -> None:
        css = read_static("styles.css")

        self.assertIn("[hidden]", css)
        self.assertIn("display: none", css)


if __name__ == "__main__":
    unittest.main()
