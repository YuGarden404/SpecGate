import hashlib
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
    def test_page_without_search_passes_when_checklist_does_not_require_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>News</title>
</head>
<body><main><h1>News</h1></main></body>
</html>"""
            (root / "index.html").write_text(html, encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertTrue(result.passed)
            self.assertNotIn("search", {issue.code for issue in result.issues})

    def test_unsupported_checkbox_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- [ ] 页面要看起来高级\n", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertIn("unsupported_check", {issue.code for issue in result.issues})

    def test_gate_records_input_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "index.html"
            checklist_path = root / "CHECKLIST.md"
            html_path.write_text(VALID_HTML, encoding="utf-8")
            checklist_path.write_text("", encoding="utf-8")

            result = run_html_gate(html_path, checklist_path)

            self.assertEqual(
                result.artifact_sha256,
                hashlib.sha256(
                    workspace_fs.read_workspace_text(
                        root,
                        "index.html",
                        encoding="utf-8-sig",
                    ).encode("utf-8")
                ).hexdigest(),
            )
            self.assertEqual(
                result.checklist_sha256,
                hashlib.sha256(b"").hexdigest(),
            )

    def test_gate_hashes_exact_input_bytes_including_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "index.html"
            checklist_path = root / "CHECKLIST.md"
            html_bytes = b"\xef\xbb\xbf" + VALID_HTML.encode("utf-8")
            checklist_bytes = b"\xef\xbb\xbf"
            html_path.write_bytes(html_bytes)
            checklist_path.write_bytes(checklist_bytes)

            result = run_html_gate(html_path, checklist_path)

            self.assertEqual(
                result.artifact_sha256,
                hashlib.sha256(html_bytes).hexdigest(),
            )
            self.assertEqual(
                result.checklist_sha256,
                hashlib.sha256(checklist_bytes).hexdigest(),
            )

    def test_structured_selector_rule_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (root / "CHECKLIST.md").write_text(
                '- [ ] 至少 2 个 article\n  <!-- specgate: selector "article" min=2 -->\n',
                encoding="utf-8",
            )

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertIn("checklist_selector", {issue.code for issue in result.issues})

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
            real_read = workspace_fs.read_workspace_bytes

            def race_html(read_root, relative, **kwargs):
                if Path(read_root) == root and relative == "index.html":
                    raise workspace_fs.WorkspacePathError(f"ancestor replaced: {sentinel}", "path_race")
                return real_read(read_root, relative)

            with mock.patch.object(workspace_fs, "read_workspace_bytes", side_effect=race_html):
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_artifact" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (root / "CHECKLIST.md").write_text(f"- must include {sentinel}\n", encoding="utf-8")
            real_read = workspace_fs.read_workspace_bytes

            def race_checklist(read_root, relative, **kwargs):
                if Path(read_root) == root and relative == "CHECKLIST.md":
                    raise workspace_fs.WorkspacePathError(f"ancestor replaced: {sentinel}", "path_race")
                return real_read(read_root, relative)

            with mock.patch.object(workspace_fs, "read_workspace_bytes", side_effect=race_checklist):
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "unsafe_checklist" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))

    def test_index_ancestor_cannot_be_replaced_between_state_and_read(self):
        sentinel = "EXTERNAL_INDEX_SENTINEL"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            artifact_root = base / "artifact"
            displaced_root = base / "artifact-original"
            external_root = base / "external-artifact"
            artifact_root.mkdir()
            external_root.mkdir()
            (artifact_root / "index.html").write_text(
                "<html><head><title>x</title></head><body></body></html>",
                encoding="utf-8",
            )
            (external_root / "index.html").write_text(
                VALID_HTML.replace("</body>", f"{sentinel}</body>"),
                encoding="utf-8",
            )
            (base / "CHECKLIST.md").write_text("", encoding="utf-8")
            real_state = workspace_fs.workspace_file_state

            def replace_after_state(root, relative):
                state = real_state(root, relative)
                if Path(root) == artifact_root and relative == "index.html":
                    artifact_root.rename(displaced_root)
                    external_root.rename(artifact_root)
                return state

            with mock.patch.object(
                workspace_fs,
                "workspace_file_state",
                side_effect=replace_after_state,
            ) as state_mock:
                result = run_html_gate(artifact_root / "index.html", base / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "doctype" for issue in result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))
            self.assertNotIn(sentinel, repr(result))
            state_mock.assert_not_called()

    def test_checklist_ancestor_cannot_be_replaced_between_state_and_read(self):
        sentinel = "EXTERNAL_CHECKLIST_SENTINEL"
        internal_term = "INTERNAL_ONLY_TERM"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checklist_root = base / "checklist"
            displaced_root = base / "checklist-original"
            external_root = base / "external-checklist"
            checklist_root.mkdir()
            external_root.mkdir()
            (base / "index.html").write_text(VALID_HTML, encoding="utf-8")
            (checklist_root / "CHECKLIST.md").write_text(
                f"- 必须包含 {internal_term}\n",
                encoding="utf-8",
            )
            (external_root / "CHECKLIST.md").write_text(
                f"- 必须包含 {sentinel}\n",
                encoding="utf-8",
            )
            real_state = workspace_fs.workspace_file_state

            def replace_after_state(root, relative):
                state = real_state(root, relative)
                if Path(root) == checklist_root and relative == "CHECKLIST.md":
                    checklist_root.rename(displaced_root)
                    external_root.rename(checklist_root)
                return state

            with mock.patch.object(
                workspace_fs,
                "workspace_file_state",
                side_effect=replace_after_state,
            ) as state_mock:
                result = run_html_gate(base / "index.html", checklist_root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertIn(internal_term, repr(result.issues))
            self.assertNotIn(sentinel, result.summary)
            self.assertNotIn(sentinel, repr(result.issues))
            self.assertNotIn(sentinel, repr(result))
            state_mock.assert_not_called()

    def test_missing_inputs_use_safe_open_missing_path_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")

            with mock.patch.object(
                workspace_fs,
                "workspace_file_state",
                side_effect=AssertionError("Gate must not check state before reading"),
            ) as state_mock:
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "missing_artifact" for issue in result.issues))
            state_mock.assert_not_called()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(VALID_HTML, encoding="utf-8")

            with mock.patch.object(
                workspace_fs,
                "workspace_file_state",
                side_effect=AssertionError("Gate must not check state before reading"),
            ) as state_mock:
                result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertTrue(result.passed)
            state_mock.assert_not_called()

    def test_non_race_missing_metadata_for_index_fails_closed(self):
        sentinel = "EXTERNAL_INDEX_ERROR_SENTINEL"
        for family in ("linked_path", "reparse_point"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "CHECKLIST.md").write_text("", encoding="utf-8")
                error = workspace_fs.WorkspacePathError(
                    f"unsafe index: {sentinel}",
                    family,
                    missing_path="index.html",
                )

                with mock.patch.object(workspace_fs, "read_workspace_bytes", side_effect=error):
                    result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

                self.assertFalse(result.passed)
                self.assertTrue(any(issue.code == "unsafe_artifact" for issue in result.issues))
                self.assertTrue(any(issue.evidence == family for issue in result.issues))
                self.assertNotIn(sentinel, repr(result))

    def test_non_race_missing_metadata_for_checklist_fails_closed(self):
        sentinel = "EXTERNAL_CHECKLIST_ERROR_SENTINEL"
        for family in ("linked_path", "reparse_point"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
                real_read = workspace_fs.read_workspace_bytes

                def reject_checklist(read_root, relative, **kwargs):
                    if relative == "CHECKLIST.md":
                        raise workspace_fs.WorkspacePathError(
                            f"unsafe checklist: {sentinel}",
                            family,
                            missing_path="CHECKLIST.md",
                        )
                    return real_read(read_root, relative)

                with mock.patch.object(
                    workspace_fs,
                    "read_workspace_bytes",
                    side_effect=reject_checklist,
                ):
                    result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

                self.assertFalse(result.passed)
                self.assertTrue(any(issue.code == "unsafe_checklist" for issue in result.issues))
                self.assertTrue(any(issue.evidence == family for issue in result.issues))
                self.assertNotIn(sentinel, repr(result))

if __name__ == "__main__":
    unittest.main()
