from __future__ import annotations

import re
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
    def assert_js_callable(
        self,
        app_js: str,
        name: str,
        *,
        async_expected: bool = False,
    ) -> None:
        escaped_name = re.escape(name)
        if async_expected:
            callable_patterns = [
                rf"async\s+function\s+{escaped_name}\s*\(",
                rf"(?:const|let|var)\s+{escaped_name}\s*=\s*async\b",
            ]
        else:
            callable_patterns = [
                rf"function\s+{escaped_name}\s*\(",
                rf"(?:const|let|var)\s+{escaped_name}\s*=",
            ]
        self.assertRegex(app_js, "|".join(callable_patterns))

    def test_static_assets_exist(self) -> None:
        for filename in ("index.html", "styles.css", "app.js"):
            with self.subTest(filename=filename):
                self.assertTrue((STATIC_DIR / filename).is_file())

    def test_index_contains_required_regions(self) -> None:
        html = read_static("index.html")
        for element_id in (
            "auth-view",
            "workspace-view",
            "app-menu-bar",
            "sidebar-toggle-button",
            "back-button",
            "forward-button",
            "project-sidebar",
            "project-list",
            "workspace-main",
            "workspace-titlebar",
            "message-list",
            "run-form",
            "project-dialog",
            "project-form",
            "search-dialog",
            "about-dialog",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)

    def test_index_contains_codex_like_menu_bar(self) -> None:
        html = read_static("index.html")
        for text in (
            "文件",
            "编辑",
            "帮助",
            "新窗口",
            "Ctrl+Shift+N",
            "新项目",
            "Ctrl+N",
            "关闭",
            "Ctrl+W",
            "设置",
            "Ctrl+,",
            "登出",
            "退出",
            "Ctrl+Q",
            "搜索",
            "Ctrl+G",
            "关于 SpecGate",
        ):
            with self.subTest(text=text):
                self.assertIn(text, html)
        self.assertNotRegex(html, r"<button\b[^>]*>\s*视图\s*</button>")

    def test_project_dialog_uses_file_import_fields(self) -> None:
        html = read_static("index.html")
        for text in (
            "project-name",
            "spec.md",
            "checklist.md",
            "index.html",
        ):
            with self.subTest(text=text):
                self.assertIn(text, html)
        for element_id in (
            "project-spec-file",
            "project-checklist-file",
            "project-index-file",
        ):
            with self.subTest(element_id=element_id):
                input_pattern = (
                    rf"<input\b(?=[^>]*\bid\s*=\s*['\"]{re.escape(element_id)}['\"])"
                    r"(?=[^>]*\btype\s*=\s*['\"]file['\"])[^>]*>"
                )
                self.assertRegex(
                    html,
                    input_pattern,
                )
        for element_id in ("project-spec", "project-checklist", "project-index"):
            with self.subTest(legacy_id=element_id):
                self.assertNotRegex(
                    html,
                    rf"<textarea\b[^>]*\bid\s*=\s*['\"]{re.escape(element_id)}['\"]",
                )
        for field_name in ("spec_text", "checklist_text", "index_html"):
            with self.subTest(legacy_name=field_name):
                self.assertNotRegex(
                    html,
                    rf"<textarea\b[^>]*\bname\s*=\s*['\"]{re.escape(field_name)}['\"]",
                )

    def test_index_contains_report_detail_view_menu_item(self) -> None:
        html = read_static("index.html")
        self.assertIn('data-detail-view="detail-report"', html)

    def test_index_contains_audit_detail_view_menu_item(self) -> None:
        html = read_static("index.html")
        self.assertIn('data-detail-view="detail-audit"', html)

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

    def test_app_contains_codex_shell_workflows(self) -> None:
        app_js = read_static("app.js")
        for text in ("viewBackStack", "viewForwardStack"):
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        for function_name in (
            "pushView",
            "goBack",
            "goForward",
            "closeCurrentProject",
            "toggleSidebar",
            "showSidebarPeek",
            "hideSidebarPeek",
            "openSearchDialog",
            "renderSearchResults",
            "openNewWindow",
            "exitWindow",
            "clearAuthForm",
            "renderWorkspaceView",
            "openProjectMenu",
        ):
            with self.subTest(function_name=function_name):
                self.assert_js_callable(app_js, function_name)
        with self.subTest(function_name="readProjectFile"):
            self.assert_js_callable(app_js, "readProjectFile", async_expected=True)

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
        for selector in (
            ".app-menu-bar",
            ".menu-group",
            ".menu-popover",
            ".workspace-view",
            ".app-shell",
            ".project-sidebar",
            ".sidebar-edge-hotzone",
            ".workspace-main",
            ".workspace-titlebar",
            ".messages-frame",
            ".composer-frame",
            ".search-results",
            "body.sidebar-collapsed",
            "body.sidebar-peeking",
        ):
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
