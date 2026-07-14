import unittest

from specgate.checklist_rules import (
    ChecklistRule,
    evaluate_rule,
    parse_checklist,
    parse_html_features,
)


class ChecklistParserTests(unittest.TestCase):
    def test_parses_selector_and_each_directives(self):
        checklist = """
- [ ] 至少三条新闻
  <!-- specgate: selector "article.news-card" min=3 -->
- [ ] 每条新闻结构完整
  <!-- specgate: each "article.news-card" has "h2" ".summary" "time" -->
"""

        result = parse_checklist(checklist)

        self.assertEqual([rule.kind for rule in result.rules], ["selector", "each"])
        self.assertEqual(result.rules[0].minimum, 3)
        self.assertEqual(result.rules[1].required_selectors, ("h2", ".summary", "time"))
        self.assertEqual(result.issues, ())

    def test_parses_text_and_forbid_directives(self):
        checklist = """
- [ ] 包含版权文字
  <!-- specgate: text "版权所有" -->
- [ ] 不依赖外部资源
  <!-- specgate: forbid external-resources -->
- [ ] 不包含脚本
  <!-- specgate: forbid scripts -->
"""

        result = parse_checklist(checklist)

        self.assertEqual([rule.kind for rule in result.rules], ["text", "forbid", "forbid"])
        self.assertEqual(result.rules[0].text, "版权所有")
        self.assertEqual(result.rules[1].forbidden_feature, "external-resources")
        self.assertEqual(result.rules[2].forbidden_feature, "scripts")

    def test_unrecognized_checkbox_is_unsupported(self):
        result = parse_checklist("- [ ] 页面要看起来高级")

        self.assertEqual(result.rules, ())
        self.assertEqual(result.issues[0].code, "unsupported_check")

    def test_invalid_selector_is_reported(self):
        checklist = """
- [ ] 复杂选择器
  <!-- specgate: selector "main > article" min=1 -->
"""

        result = parse_checklist(checklist)

        self.assertEqual(result.rules, ())
        self.assertEqual(result.issues[0].code, "invalid_checklist_rule")

    def test_legacy_must_include_rule_remains_supported(self):
        result = parse_checklist("- 必须包含 SpecGate")

        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.rules[0].kind, "text")
        self.assertEqual(result.rules[0].text, "SpecGate")

    def test_plain_documentation_is_not_treated_as_a_check(self):
        result = parse_checklist("# 页面说明\n\n请按设计完成页面。")

        self.assertEqual(result.rules, ())
        self.assertEqual(result.issues, ())


class ChecklistEvaluationTests(unittest.TestCase):
    def test_evaluates_selector_count(self):
        document = parse_html_features(
            '<main><article class="news-card"></article><article class="news-card"></article></main>'
        )
        rule = ChecklistRule(
            kind="selector",
            label="两条新闻",
            selector="article.news-card",
            minimum=2,
        )

        self.assertTrue(evaluate_rule(rule, document).passed)

    def test_evaluates_each_rule_against_descendants(self):
        document = parse_html_features(
            '<article class="news-card"><h2>A</h2><p class="summary">B</p><time>C</time></article>'
        )
        rule = ChecklistRule(
            kind="each",
            label="新闻结构",
            selector="article.news-card",
            required_selectors=("h2", ".summary", "time"),
        )

        self.assertTrue(evaluate_rule(rule, document).passed)

    def test_each_rule_reports_missing_descendant(self):
        document = parse_html_features(
            '<article class="news-card"><h2>A</h2><time>C</time></article>'
        )
        rule = ChecklistRule(
            kind="each",
            label="新闻结构",
            selector="article.news-card",
            required_selectors=("h2", ".summary", "time"),
        )

        result = evaluate_rule(rule, document)

        self.assertFalse(result.passed)
        self.assertIn(".summary", result.evidence)

    def test_evaluates_text_and_forbid_rules(self):
        document = parse_html_features(
            '<html><body><footer>版权所有</footer><script>noop()</script></body></html>'
        )

        self.assertTrue(
            evaluate_rule(
                ChecklistRule(kind="text", label="版权", text="版权所有"),
                document,
            ).passed
        )
        self.assertFalse(
            evaluate_rule(
                ChecklistRule(kind="forbid", label="无脚本", forbidden_feature="scripts"),
                document,
            ).passed
        )


if __name__ == "__main__":
    unittest.main()
