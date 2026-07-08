from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


@dataclass(frozen=True)
class GateIssue:
    code: str
    severity: str
    message: str
    evidence: str
    repair_hint: str


@dataclass(frozen=True)
class GateCheck:
    code: str
    passed: bool
    message: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: list[GateCheck]
    issues: list[GateIssue]
    summary: str


class _HtmlFeatureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.node_count = 0
        self.has_viewport = False
        self.has_search = False
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag_name = tag.lower()
        self.tags.append(tag_name)
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag_name == "meta" and attrs_dict.get("name", "").lower() == "viewport":
            self.has_viewport = True
        classes = attrs_dict.get("class", "")
        if "node" in classes.split():
            self.node_count += 1
        if tag_name == "input" and attrs_dict.get("type", "").lower() == "search":
            self.has_search = True

    def handle_data(self, data: str):
        if data.strip():
            self.text_parts.append(data.strip())


def _issue(code: str, message: str, evidence: str, repair_hint: str) -> GateIssue:
    return GateIssue(code, "error", message, evidence, repair_hint)


def _check(code: str, passed: bool, message: str) -> GateCheck:
    return GateCheck(code, passed, message)


def _checklist_terms(checklist_path: Path) -> list[str]:
    if not checklist_path.exists():
        return []
    terms: list[str] = []
    for line in checklist_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- 必须包含 "):
            terms.append(line.removeprefix("- 必须包含 ").strip())
    return [term for term in terms if term]


def run_html_gate(html_path: Path, checklist_path: Path) -> GateResult:
    checks: list[GateCheck] = []
    issues: list[GateIssue] = []

    if not html_path.exists():
        issue = _issue("missing_artifact", "index.html 不存在", str(html_path), "写入 index.html")
        return GateResult(False, [_check("exists", False, "index.html missing")], [issue], "index.html 不存在")

    content = html_path.read_text(encoding="utf-8")
    parser = _HtmlFeatureParser()
    parser.feed(content)
    lower = content.lower()
    text = "\n".join(parser.text_parts)

    requirements = [
        ("doctype", "<!doctype html" in lower, "需要 <!doctype html>", "添加 <!doctype html>"),
        ("html_tag", "html" in parser.tags, "需要 html 标签", "添加 html 根标签"),
        ("head_tag", "head" in parser.tags, "需要 head 标签", "添加 head"),
        ("title_tag", "title" in parser.tags, "需要 title 标签", "添加页面标题"),
        ("body_tag", "body" in parser.tags, "需要 body 标签", "添加 body"),
        ("viewport", parser.has_viewport, "需要 viewport meta", "添加移动端 viewport meta"),
        ("search", parser.has_search or "filter" in lower, "需要搜索或过滤 UI", "添加 search input 或 filter 控件"),
        ("relations", "highlightrelations" in lower or "data-related" in lower, "需要关系高亮能力", "添加 data-related 和关系高亮脚本"),
        ("offline", "https://" not in lower and "http://" not in lower, "不能依赖外部网络资源", "移除外部脚本和样式"),
        ("no_secret", "sk-" not in content and "api_key" not in lower, "不能包含疑似密钥", "移除密钥样文本"),
    ]

    for code, passed, message, hint in requirements:
        checks.append(_check(code, passed, message))
        if not passed:
            issues.append(_issue(code, message, code, hint))

    enough_nodes = parser.node_count >= 10
    checks.append(_check("node_count", enough_nodes, "至少 10 个知识节点"))
    if not enough_nodes:
        issues.append(_issue("too_few_nodes", "知识节点不足", str(parser.node_count), "添加至少 10 个 class=node 的知识节点"))

    for term in _checklist_terms(checklist_path):
        passed = term in text
        checks.append(_check(f"checklist_contains_{term}", passed, f"必须包含 {term}"))
        if not passed:
            issues.append(_issue("missing_checklist_term", f"缺少 checklist 项：{term}", term, f"在页面内容中加入 {term}"))

    passed = not issues
    summary_issues = sorted(issues, key=lambda issue: 0 if issue.code == "too_few_nodes" else 1)
    summary = "Gate 通过" if passed else "Gate 失败：" + "；".join(issue.repair_hint for issue in summary_issues[:4])
    return GateResult(passed, checks, issues, summary)
