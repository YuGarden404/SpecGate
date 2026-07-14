from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
import shlex


_CHECKBOX_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s+(.+?)\s*$")
_LEGACY_TEXT_RE = re.compile(r"^\s*-\s*必须包含\s+(.+?)\s*$")
_DIRECTIVE_RE = re.compile(r"^\s*<!--\s*specgate:\s*(.*?)\s*-->\s*$")
_TAG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_TAG_CLASS_RE = re.compile(
    r"^(?P<tag>[A-Za-z][A-Za-z0-9-]*)\.(?P<class>[A-Za-z_][A-Za-z0-9_-]*)$"
)
_ATTR_RE = re.compile(
    r'^\[(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)(?:="(?P<value>[^"]*)")?\]$'
)
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True)
class ChecklistRuleIssue:
    code: str
    message: str
    label: str


@dataclass(frozen=True)
class ChecklistRule:
    kind: str
    label: str
    selector: str | None = None
    minimum: int = 1
    required_selectors: tuple[str, ...] = ()
    text: str | None = None
    forbidden_feature: str | None = None


@dataclass(frozen=True)
class ChecklistParseResult:
    rules: tuple[ChecklistRule, ...]
    issues: tuple[ChecklistRuleIssue, ...]


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list["HtmlNode"] = field(default_factory=list)


@dataclass(frozen=True)
class HtmlDocument:
    roots: tuple[HtmlNode, ...]
    nodes: tuple[HtmlNode, ...]
    text: str
    raw: str


@dataclass(frozen=True)
class ChecklistRuleResult:
    passed: bool
    message: str
    evidence: str


@dataclass(frozen=True)
class _SimpleSelector:
    tag: str | None = None
    class_name: str | None = None
    element_id: str | None = None
    attr_name: str | None = None
    attr_value: str | None = None


class _FeatureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[HtmlNode] = []
        self.nodes: list[HtmlNode] = []
        self.stack: list[HtmlNode] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        node = HtmlNode(
            tag=tag.lower(),
            attrs={str(name).lower(): value or "" for name, value in attrs},
        )
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.roots.append(node)
        self.nodes.append(node)
        if node.tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == lowered:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def parse_checklist(markdown: str) -> ChecklistParseResult:
    rules: list[ChecklistRule] = []
    issues: list[ChecklistRuleIssue] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        legacy = _LEGACY_TEXT_RE.match(line)
        if legacy:
            text = legacy.group(1).strip()
            if text:
                rules.append(ChecklistRule(kind="text", label=line.strip(), text=text))
            index += 1
            continue

        checkbox = _CHECKBOX_RE.match(line)
        if not checkbox:
            index += 1
            continue

        label = checkbox.group(1).strip()
        directive: str | None = None
        next_index = index + 1
        if next_index < len(lines):
            match = _DIRECTIVE_RE.match(lines[next_index])
            if match:
                directive = match.group(1).strip()
                index = next_index

        if directive is None:
            compatible = _parse_compatible_label(label)
            if compatible is None:
                issues.append(
                    ChecklistRuleIssue(
                        "unsupported_check",
                        "checklist item has no deterministic SpecGate rule",
                        label,
                    )
                )
            else:
                rules.append(compatible)
        else:
            try:
                rules.append(_parse_directive(label, directive))
            except ValueError as exc:
                issues.append(ChecklistRuleIssue("invalid_checklist_rule", str(exc), label))
        index += 1

    return ChecklistParseResult(tuple(rules), tuple(issues))


def parse_html_features(content: str) -> HtmlDocument:
    parser = _FeatureParser()
    parser.feed(content)
    parser.close()
    return HtmlDocument(
        tuple(parser.roots),
        tuple(parser.nodes),
        "\n".join(parser.text_parts),
        content,
    )


def evaluate_rule(rule: ChecklistRule, document: HtmlDocument) -> ChecklistRuleResult:
    if rule.kind == "selector" and rule.selector is not None:
        count = len(_matching_nodes(document.nodes, rule.selector))
        passed = count >= rule.minimum
        return ChecklistRuleResult(
            passed,
            f"selector {rule.selector} requires at least {rule.minimum}",
            f"matched={count}",
        )

    if rule.kind == "each" and rule.selector is not None:
        targets = _matching_nodes(document.nodes, rule.selector)
        missing: list[str] = []
        if not targets:
            missing.append(rule.selector)
        for target_index, target in enumerate(targets, start=1):
            descendants = tuple(_descendants(target))
            for selector in rule.required_selectors:
                if not _matching_nodes(descendants, selector):
                    missing.append(f"item {target_index}: {selector}")
        return ChecklistRuleResult(
            not missing,
            f"each {rule.selector} must contain required descendants",
            "all descendants present" if not missing else "; ".join(missing),
        )

    if rule.kind == "text" and rule.text is not None:
        passed = rule.text in document.text
        return ChecklistRuleResult(
            passed,
            f"document must contain text: {rule.text}",
            "text found" if passed else f"missing text: {rule.text}",
        )

    if rule.kind == "forbid":
        if rule.forbidden_feature == "scripts":
            found = any(node.tag == "script" for node in document.nodes)
        elif rule.forbidden_feature == "external-resources":
            found = _has_external_resource(document)
        else:
            return ChecklistRuleResult(False, "unsupported forbidden feature", "invalid rule")
        return ChecklistRuleResult(
            not found,
            f"document must not contain {rule.forbidden_feature}",
            "forbidden feature found" if found else "forbidden feature absent",
        )

    return ChecklistRuleResult(False, "unsupported checklist rule", rule.kind)


def _parse_directive(label: str, directive: str) -> ChecklistRule:
    try:
        tokens = shlex.split(directive, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid directive quoting: {exc}") from exc
    if not tokens:
        raise ValueError("empty SpecGate directive")

    command = tokens[0]
    if command == "selector":
        if len(tokens) not in {2, 3}:
            raise ValueError("selector directive requires a selector and optional min=N")
        _parse_selector(tokens[1])
        minimum = 1
        if len(tokens) == 3:
            if not tokens[2].startswith("min="):
                raise ValueError("selector directive only accepts min=N")
            try:
                minimum = int(tokens[2].removeprefix("min="))
            except ValueError as exc:
                raise ValueError("selector minimum must be an integer") from exc
            if minimum < 1:
                raise ValueError("selector minimum must be positive")
        return ChecklistRule(kind="selector", label=label, selector=tokens[1], minimum=minimum)

    if command == "each":
        if len(tokens) < 4 or tokens[2] != "has":
            raise ValueError("each directive requires: each SELECTOR has CHILD...")
        _parse_selector(tokens[1])
        for selector in tokens[3:]:
            _parse_selector(selector)
        return ChecklistRule(
            kind="each",
            label=label,
            selector=tokens[1],
            required_selectors=tuple(tokens[3:]),
        )

    if command == "text":
        if len(tokens) != 2 or not tokens[1]:
            raise ValueError("text directive requires one non-empty literal")
        return ChecklistRule(kind="text", label=label, text=tokens[1])

    if command == "forbid":
        if len(tokens) != 2 or tokens[1] not in {"external-resources", "scripts"}:
            raise ValueError("forbid directive supports external-resources or scripts")
        return ChecklistRule(kind="forbid", label=label, forbidden_feature=tokens[1])

    raise ValueError(f"unsupported SpecGate directive: {command}")


def _parse_compatible_label(label: str) -> ChecklistRule | None:
    must_include = re.match(r"^必须包含\s+(.+)$", label)
    if must_include:
        return ChecklistRule(kind="text", label=label, text=must_include.group(1).strip())
    lowered = label.lower().replace(" ", "")
    if "外部" in label and any(marker in label for marker in ("不", "无", "禁止")):
        return ChecklistRule(kind="forbid", label=label, forbidden_feature="external-resources")
    if ("脚本" in label or "js" in lowered) and any(marker in label for marker in ("不", "无", "禁止")):
        return ChecklistRule(kind="forbid", label=label, forbidden_feature="scripts")
    return None


def _parse_selector(value: str) -> _SimpleSelector:
    if _TAG_RE.fullmatch(value):
        return _SimpleSelector(tag=value.lower())
    if value.startswith(".") and _NAME_RE.fullmatch(value[1:]):
        return _SimpleSelector(class_name=value[1:])
    if value.startswith("#") and _NAME_RE.fullmatch(value[1:]):
        return _SimpleSelector(element_id=value[1:])
    tag_class = _TAG_CLASS_RE.fullmatch(value)
    if tag_class:
        return _SimpleSelector(
            tag=tag_class.group("tag").lower(),
            class_name=tag_class.group("class"),
        )
    attribute = _ATTR_RE.fullmatch(value)
    if attribute:
        return _SimpleSelector(
            attr_name=attribute.group("name").lower(),
            attr_value=attribute.group("value"),
        )
    raise ValueError(f"unsupported simple selector: {value}")


def _matching_nodes(nodes: tuple[HtmlNode, ...], selector_value: str) -> list[HtmlNode]:
    selector = _parse_selector(selector_value)
    return [node for node in nodes if _node_matches(node, selector)]


def _node_matches(node: HtmlNode, selector: _SimpleSelector) -> bool:
    if selector.tag is not None and node.tag != selector.tag:
        return False
    if selector.class_name is not None:
        if selector.class_name not in node.attrs.get("class", "").split():
            return False
    if selector.element_id is not None and node.attrs.get("id") != selector.element_id:
        return False
    if selector.attr_name is not None:
        if selector.attr_name not in node.attrs:
            return False
        if selector.attr_value is not None and node.attrs[selector.attr_name] != selector.attr_value:
            return False
    return True


def _descendants(node: HtmlNode):
    for child in node.children:
        yield child
        yield from _descendants(child)


def _has_external_resource(document: HtmlDocument) -> bool:
    for node in document.nodes:
        for name in ("href", "src", "action"):
            value = node.attrs.get(name, "").strip().lower()
            if value.startswith(("http://", "https://", "//")):
                return True
    lowered = document.raw.lower()
    return bool(re.search(r"url\(\s*['\"]?(?:https?:)?//", lowered))
