from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re

from specgate import workspace_fs
from specgate.security import contains_secret_like_text


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


def _read_gate_file(path: Path) -> str | None:
    root = path.parent
    relative = path.name
    try:
        return workspace_fs.read_workspace_text(root, relative, encoding="utf-8-sig")
    except workspace_fs.WorkspacePathError as exc:
        if exc.missing_path == relative:
            return None
        raise


def _checklist_terms(checklist_text: str) -> list[str]:
    terms: list[str] = []
    for line in checklist_text.splitlines():
        line = line.strip()
        if line.startswith("- 必须包含 "):
            terms.append(line.removeprefix("- 必须包含 ").strip())
    return [term for term in terms if term]


def _requires_knowledge_graph(checklist_text: str) -> bool:
    lowered = checklist_text.lower()
    markers = ("class=node", "class=\"node\"", "知识节点", "data-related", "关系高亮")
    return any(marker in lowered for marker in markers)


def _required_node_count(checklist_text: str) -> int:
    match = re.search(r"至少\s*(\d+)\s*个.*(?:class=node|class=\"node\"|知识节点)", checklist_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 10


def _unsafe_input_result(kind: str, error: workspace_fs.WorkspacePathError) -> GateResult:
    if kind == "artifact":
        code = "unsafe_artifact"
        message = "index.html could not be read safely"
        repair_hint = "Replace index.html with a regular workspace file"
    else:
        code = "unsafe_checklist"
        message = "checklist could not be read safely"
        repair_hint = "Replace the checklist with a regular workspace file"
    issue = _issue(code, message, error.rule_family, repair_hint)
    return GateResult(False, [_check(code, False, message)], [issue], f"Gate failed: {repair_hint}")


def run_html_gate(html_path: Path, checklist_path: Path | None) -> GateResult:
    checks: list[GateCheck] = []
    issues: list[GateIssue] = []

    try:
        content = _read_gate_file(html_path)
    except workspace_fs.WorkspacePathError as exc:
        return _unsafe_input_result("artifact", exc)
    if content is None:
        issue = _issue("missing_artifact", "index.html 不存在", str(html_path), "写入 index.html")
        return GateResult(False, [_check("exists", False, "index.html missing")], [issue], "index.html 不存在")

    checklist_text = ""
    if checklist_path is not None:
        try:
            checklist_text = _read_gate_file(checklist_path) or ""
        except workspace_fs.WorkspacePathError as exc:
            return _unsafe_input_result("checklist", exc)
    parser = _HtmlFeatureParser()
    parser.feed(content)
    lower = content.lower()
    text = "\n".join(parser.text_parts + [content])

    requirements = [
        ("doctype", "<!doctype html" in lower, "需要 <!doctype html>", "添加 <!doctype html>"),
        ("html_tag", "html" in parser.tags, "需要 html 标签", "添加 html 根标签"),
        ("head_tag", "head" in parser.tags, "需要 head 标签", "添加 head"),
        ("title_tag", "title" in parser.tags, "需要 title 标签", "添加页面标题"),
        ("body_tag", "body" in parser.tags, "需要 body 标签", "添加 body"),
        ("viewport", parser.has_viewport, "需要 viewport meta", "添加移动端 viewport meta"),
        ("search", parser.has_search or "filter" in lower, "需要搜索或过滤 UI", "添加 search input 或 filter 控件"),
        ("offline", "https://" not in lower and "http://" not in lower, "不能依赖外部网络资源", "移除外部脚本和样式"),
        ("no_secret", not contains_secret_like_text(content), "不能包含疑似密钥", "移除密钥样文本"),
    ]

    if _requires_knowledge_graph(checklist_text):
        requirements.append(
            (
                "relations",
                "highlightrelations" in lower or "data-related" in lower,
                "需要关系高亮能力",
                "添加 data-related 和关系高亮脚本",
            )
        )

    for code, passed, message, hint in requirements:
        checks.append(_check(code, passed, message))
        if not passed:
            issues.append(_issue(code, message, code, hint))

    if _requires_knowledge_graph(checklist_text):
        min_nodes = _required_node_count(checklist_text)
        enough_nodes = parser.node_count >= min_nodes
        checks.append(_check("node_count", enough_nodes, f"至少 {min_nodes} 个知识节点"))
        if not enough_nodes:
            issues.append(
                _issue(
                    "too_few_nodes",
                    "知识节点不足",
                    str(parser.node_count),
                    f"添加至少 {min_nodes} 个 class=node 的知识节点",
                )
            )

    for term in _checklist_terms(checklist_text):
        passed = term in text
        checks.append(_check(f"checklist_contains_{term}", passed, f"必须包含 {term}"))
        if not passed:
            issues.append(_issue("missing_checklist_term", f"缺少 checklist 项：{term}", term, f"在页面内容中加入 {term}"))

    passed = not issues
    summary_issues = sorted(issues, key=lambda issue: 0 if issue.code == "too_few_nodes" else 1)
    summary = "Gate 通过" if passed else "Gate 失败：" + "；".join(issue.repair_hint for issue in summary_issues[:4])
    return GateResult(passed, checks, issues, summary)
