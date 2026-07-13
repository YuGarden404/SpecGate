import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specgate import workspace_fs
from specgate.gate import run_html_gate


VALID_HTML = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI for Coding Knowledge Navigator</title>
</head>
<body>
  <input type="search" aria-label="搜索">
  <main>
    <section class="node" data-related="spec"><h2>Spec</h2><p>定义 1</p></section>
    <section class="node" data-related="checklist"><h2>Checklist</h2><p>定义 2</p></section>
    <section class="node" data-related="gate"><h2>Gate</h2><p>定义 3</p></section>
    <section class="node" data-related="prompt"><h2>Prompt</h2><p>定义 4</p></section>
    <section class="node" data-related="context"><h2>Context</h2><p>定义 5</p></section>
    <section class="node" data-related="mcp"><h2>MCP</h2><p>定义 6</p></section>
    <section class="node" data-related="skill"><h2>Skill</h2><p>定义 7</p></section>
    <section class="node" data-related="hook"><h2>Hook</h2><p>定义 8</p></section>
    <section class="node" data-related="agent"><h2>Agent</h2><p>定义 9</p></section>
    <section class="node" data-related="trace"><h2>Trace</h2><p>定义 10</p></section>
  </main>
  <script>function highlightRelations(){ return true; } function filterNodes(){ return true; }</script>
</body>
</html>"""


class HtmlGateTests(unittest.TestCase):
    def test_valid_html_passes_core_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertTrue(result.passed)
            self.assertEqual([], result.issues)

    def test_missing_nodes_fails_with_repair_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 至少 10 个 class=node 知识节点\n", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "too_few_nodes" for issue in result.issues))
            self.assertIn("至少 10 个", result.summary)

    def test_generic_static_dashboard_does_not_require_knowledge_graph_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 学习计划看板</title>
</head>
<body>
  <header><h1>AI 学习计划</h1></header>
  <input type="search" aria-label="搜索">
  <main>
    <section class="module-card"><h2>Python</h2><p>详情：基础语法</p></section>
    <section class="module-card"><h2>LLM</h2><p>详情：提示词与上下文</p></section>
    <section class="module-card"><h2>Gate</h2><p>详情：验收反馈</p></section>
  </main>
  <aside>详情</aside>
  <script>function showDetail(){ return true; }</script>
</body>
</html>"""
            (root / "index.html").write_text(html, encoding="utf-8")
            (root / "CHECKLIST.md").write_text(
                "- 必须包含 AI 学习计划\n- 必须包含 搜索\n- 必须包含 详情\n- 必须包含 Python\n- 必须包含 LLM\n- 必须包含 Gate\n",
                encoding="utf-8",
            )

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertTrue(result.passed)
            self.assertFalse(any(issue.code == "too_few_nodes" for issue in result.issues))
            self.assertFalse(any(issue.code == "relations" for issue in result.issues))

    def test_secret_like_google_api_key_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = VALID_HTML.replace("</body>", "<p>AIzaSyDUMMYTOKEN1234567890</p></body>")
            (root / "index.html").write_text(html, encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "no_secret" for issue in result.issues))

    def test_file_links_fail_closed_without_exposing_external_content(self):
        sentinel = "EXTERNAL_GATE_SENTINEL"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            linked_html = root / "index.html"
            linked_html.write_text(VALID_HTML.replace("</body>", f"{sentinel}</body>"), encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            real_is_link_like = workspace_fs.is_link_like
            real_is_symlink = Path.is_symlink

            with (
                mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=lambda path: path == linked_html or real_is_symlink(path),
                ),
                mock.patch.object(
                    workspace_fs,
                    "is_link_like",
                    side_effect=lambda path: Path(path) == linked_html or real_is_link_like(path),
                ),
            ):
                result = run_html_gate(linked_html, root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_artifact" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            linked_checklist = root / "CHECKLIST.md"
            linked_checklist.write_text(f"- must include {sentinel}\n", encoding="utf-8")
            real_is_link_like = workspace_fs.is_link_like
            real_is_symlink = Path.is_symlink

            with (
                mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=lambda path: path == linked_checklist or real_is_symlink(path),
                ),
                mock.patch.object(
                    workspace_fs,
                    "is_link_like",
                    side_effect=lambda path: Path(path) == linked_checklist or real_is_link_like(path),
                ),
            ):
                result = run_html_gate(root / "index.html", linked_checklist)

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_checklist" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

    def test_directory_reparse_inputs_fail_closed(self):
        sentinel = "EXTERNAL_REPARSE_SENTINEL"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML.replace("</body>", f"{sentinel}</body>"), encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            real_is_link_like = workspace_fs.is_link_like

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=lambda path: Path(path) == root or real_is_link_like(path),
            ):
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_artifact" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checklist_root = root / "linked-checklist"
            checklist_root.mkdir()
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (checklist_root / "CHECKLIST.md").write_text(f"- must include {sentinel}\n", encoding="utf-8")
            real_is_link_like = workspace_fs.is_link_like

            with mock.patch.object(
                workspace_fs,
                "is_link_like",
                side_effect=lambda path: Path(path) == checklist_root or real_is_link_like(path),
            ):
                result = run_html_gate(root / "index.html", checklist_root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_checklist" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

    def test_ancestor_replacement_during_read_fails_closed(self):
        sentinel = "EXTERNAL_RACE_SENTINEL"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML.replace("</body>", f"{sentinel}</body>"), encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            real_read = workspace_fs.read_workspace_text

            def race_html(read_root, relative, **kwargs):
                if Path(read_root) == root and relative == "index.html":
                    raise workspace_fs.WorkspacePathError(f"ancestor replaced: {sentinel}", "path_race")
                return real_read(read_root, relative, **kwargs)

            with mock.patch.object(workspace_fs, "read_workspace_text", side_effect=race_html):
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_artifact" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (root / "CHECKLIST.md").write_text(f"- must include {sentinel}\n", encoding="utf-8")
            real_read = workspace_fs.read_workspace_text

            def race_checklist(read_root, relative, **kwargs):
                if Path(read_root) == root and relative == "CHECKLIST.md":
                    raise workspace_fs.WorkspacePathError(f"ancestor replaced: {sentinel}", "path_race")
                return real_read(read_root, relative, **kwargs)

            with mock.patch.object(workspace_fs, "read_workspace_text", side_effect=race_checklist):
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_checklist" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))


if __name__ == "__main__":
    unittest.main()
