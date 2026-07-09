import tempfile
import unittest
from pathlib import Path

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
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "too_few_nodes" for issue in result.issues))
            self.assertIn("至少 10 个", result.summary)

    def test_secret_like_google_api_key_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = VALID_HTML.replace("</body>", "<p>AIzaSyDUMMYTOKEN1234567890</p></body>")
            (root / "index.html").write_text(html, encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")

            result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

            self.assertFalse(result.passed)
            self.assertTrue(any(issue.code == "no_secret" for issue in result.issues))


if __name__ == "__main__":
    unittest.main()
