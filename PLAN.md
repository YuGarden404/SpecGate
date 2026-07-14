# SpecGate MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零实现 SpecGate 的 MVP：一个 Python CLI Coding Agent Harness，能用 `MockLLM` 读取 `TASK_SPEC.md` + `CHECKLIST.md`，生成/修复静态 `index.html`，运行确定性 Gate，并输出静态 Web 报告。

**Architecture:** 核心采用小模块拆分：CLI 读取配置并启动 `AgentRunner`；runner 组装 context、调用 LLM、解析 JSON action、经过 guardrail、分发工具、运行 Gate、写 trace、生成报告。MVP 不开放 shell，不做浏览器自动化，所有核心机制必须能在 mock LLM 下用单元测试确定性验证。

**Tech Stack:** Python 3.11+ 标准库、`unittest`、`tomllib`、静态 HTML/CSS、Docker、GitLab CI `unit-test` job。

---

## 0. 执行前置条件

当前 `D:\code\NJU\SpecGate` 已有文档文件，但 `.git` 目录是空目录，`git status` 会失败。正式实现前需要人工修复 Git 初始化，以满足课程“完整 commit / PR 历史”要求。

建议人工处理方式：

```powershell
cd D:\code\NJU\SpecGate
Remove-Item -LiteralPath .git -Recurse -Force
git init
git add SPEC.md SPEC_PROCESS.md AGENT_LOG.md README.md PLAN.md .gitignore
git commit -m "docs: add initial specgate specification"
```

如果不允许删除 `.git`，则需要手动检查该目录权限和内容，让 `git status` 在项目根目录可用后再继续实现。

---

## 1. 文件结构规划

实现完成后，项目主要文件结构如下：

```text
SpecGate/
  SPEC.md
  PLAN.md
  SPEC_PROCESS.md
  AGENT_LOG.md
  README.md
  REFLECTION.md
  pyproject.toml
  specgate.toml
  Dockerfile
  .gitlab-ci.yml
  src/
    specgate/
      __init__.py
      actions.py
      config.py
      context.py
      credentials.py
      gate.py
      llm.py
      policy.py
      report.py
      runner.py
      tools.py
      trace.py
      cli.py
  tests/
    test_actions.py
    test_policy.py
    test_tools.py
    test_gate.py
    test_context.py
    test_runner.py
    test_report.py
    test_cli.py
    test_credentials.py
  examples/
    knowledge_nav/
      TASK_SPEC.md
      CHECKLIST.md
      specgate.toml
      index.html
  docs/
    superpowers/
      plans/
        2026-07-07-specgate-mvp.md
```

职责边界：

- `actions.py`：定义 Action 数据结构和严格 JSON 解析。
- `config.py`：读取 `specgate.toml`，生成运行配置。
- `policy.py`：定义工作区边界、allowlist、guardrail。
- `tools.py`：实现白名单文件工具和 dispatcher。
- `gate.py`：实现静态 HTML Gate 和 checklist 检查。
- `context.py`：构建 LLM context pack。
- `llm.py`：定义 LLM 接口和 `MockLLM`。
- `trace.py`：写入 `trace.jsonl` 并做 redaction。
- `runner.py`：实现 agent 主循环。
- `report.py`：生成静态 Web 报告。
- `credentials.py`：实现凭据状态接口和安全边界。
- `cli.py`：命令行入口。

---

## Task 1: 项目骨架与测试入口

**Files:**
- Create: `pyproject.toml`
- Create: `src/specgate/__init__.py`
- Create: `tests/test_imports.py`
- Modify: `README.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_imports.py`：

```python
import unittest


class ImportTests(unittest.TestCase):
    def test_specgate_package_imports(self):
        import specgate

        self.assertEqual(specgate.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m unittest tests.test_imports -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate'
```

- [ ] **Step 3: 写最小实现**

创建 `pyproject.toml`：

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "specgate"
version = "0.1.0"
description = "A small coding agent harness for static HTML generation and gate feedback."
requires-python = ">=3.11"
dependencies = []

[project.scripts]
specgate = "specgate.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

创建 `src/specgate/__init__.py`：

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_imports -v
```

Expected:

```text
test_specgate_package_imports ... ok
```

- [ ] **Step 5: 更新文档和日志**

在 `README.md` 增加测试命令：

```markdown
## 本地测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```
```

在 `AGENT_LOG.md` 追加 task 记录：

```markdown
## <实际时间>

- Task：Task 1 项目骨架与测试入口。
- 验证：`python -m unittest tests.test_imports -v` 通过。
- 人工干预：无。
```

- [ ] **Step 6: 提交**

```powershell
git add pyproject.toml src/specgate/__init__.py tests/test_imports.py README.md AGENT_LOG.md
git commit -m "chore: add python package skeleton"
```

---

## Task 2: Action 数据结构与严格 JSON 解析

**Files:**
- Create: `src/specgate/actions.py`
- Create: `tests/test_actions.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_actions.py`：

```python
import unittest

from specgate.actions import Action, ActionParseError, parse_action


class ActionParserTests(unittest.TestCase):
    def test_parse_valid_action(self):
        raw = '{"schema_version":"1","action":"write_file","args":{"path":"index.html","content":"<html></html>"},"reason":"create page"}'

        action = parse_action(raw)

        self.assertEqual(
            action,
            Action(
                schema_version="1",
                action="write_file",
                args={"path": "index.html", "content": "<html></html>"},
                reason="create page",
            ),
        )

    def test_rejects_markdown_wrapped_json(self):
        raw = '```json\n{"schema_version":"1","action":"finish","args":{}}\n```'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("strict JSON object", str(ctx.exception))

    def test_rejects_missing_required_field(self):
        raw = '{"schema_version":"1","args":{}}'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("missing field: action", str(ctx.exception))

    def test_rejects_non_object_args(self):
        raw = '{"schema_version":"1","action":"finish","args":[]}'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("args must be an object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_actions -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.actions'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/actions.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


class ActionParseError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    schema_version: str
    action: str
    args: dict[str, Any]
    reason: str = ""


def parse_action(raw: str) -> Action:
    text = raw.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ActionParseError("model output must be one strict JSON object")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"invalid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ActionParseError("action payload must be an object")

    for field in ("schema_version", "action", "args"):
        if field not in payload:
            raise ActionParseError(f"missing field: {field}")

    if not isinstance(payload["schema_version"], str):
        raise ActionParseError("schema_version must be a string")
    if not isinstance(payload["action"], str):
        raise ActionParseError("action must be a string")
    if not isinstance(payload["args"], dict):
        raise ActionParseError("args must be an object")

    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        raise ActionParseError("reason must be a string")

    return Action(
        schema_version=payload["schema_version"],
        action=payload["action"],
        args=payload["args"],
        reason=reason,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_actions -v
```

Expected:

```text
Ran 4 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/actions.py tests/test_actions.py
git commit -m "feat: add strict action parser"
```

---

## Task 3: Workspace Policy 与 Guardrail

**Files:**
- Create: `src/specgate/policy.py`
- Create: `tests/test_policy.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_policy.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.policy import GuardrailDecision, WorkspacePolicy, check_action


class PolicyTests(unittest.TestCase):
    def test_allows_registered_write_inside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file"},
                allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                allowed_write_paths={"index.html"},
            )
            action = Action("1", "write_file", {"path": "index.html", "content": "ok"})

            decision = check_action(action, policy)

            self.assertEqual(decision, GuardrailDecision(True, "allowed"))

    def test_blocks_unknown_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "run_command", {"command": "dir"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("unknown action", decision.reason)

    def test_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "write_file", {"path": "../outside.txt", "content": "bad"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("path escapes workspace", decision.reason)

    def test_blocks_write_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            action = Action("1", "write_file", {"path": "secret.txt", "content": "bad"})

            decision = check_action(action, policy)

            self.assertFalse(decision.allowed)
            self.assertIn("write path not allowed", decision.reason)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_policy -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.policy'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/policy.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from specgate.actions import Action


@dataclass(frozen=True)
class WorkspacePolicy:
    root: Path
    allowed_actions: set[str]
    allowed_read_paths: set[str]
    allowed_write_paths: set[str]


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str


def _normalize_relative(path_value: str) -> str | None:
    if not isinstance(path_value, str) or not path_value:
        return None
    pure = PurePosixPath(path_value.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return str(pure)


def check_action(action: Action, policy: WorkspacePolicy) -> GuardrailDecision:
    if action.action not in policy.allowed_actions:
        return GuardrailDecision(False, f"unknown action: {action.action}")

    path_value = action.args.get("path")
    if path_value is None:
        return GuardrailDecision(True, "allowed")

    normalized = _normalize_relative(path_value)
    if normalized is None:
        return GuardrailDecision(False, "path escapes workspace")

    if action.action in {"write_file", "replace_file"}:
        if normalized not in policy.allowed_write_paths:
            return GuardrailDecision(False, f"write path not allowed: {normalized}")

    if action.action == "read_file":
        if normalized not in policy.allowed_read_paths:
            return GuardrailDecision(False, f"read path not allowed: {normalized}")

    return GuardrailDecision(True, "allowed")
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_policy -v
```

Expected:

```text
Ran 4 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/policy.py tests/test_policy.py
git commit -m "feat: add workspace guardrails"
```

---

## Task 4: 文件工具与 Dispatcher

**Files:**
- Create: `src/specgate/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_tools.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.policy import WorkspacePolicy
from specgate.tools import ToolDispatcher


class ToolDispatcherTests(unittest.TestCase):
    def test_write_then_read_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file", "read_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            dispatcher = ToolDispatcher(policy)

            write_result = dispatcher.dispatch(
                Action("1", "write_file", {"path": "index.html", "content": "<!doctype html>"})
            )
            read_result = dispatcher.dispatch(Action("1", "read_file", {"path": "index.html"}))

            self.assertTrue(write_result.ok)
            self.assertEqual(read_result.data["content"], "<!doctype html>")

    def test_blocked_action_returns_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = WorkspacePolicy(Path(tmp), {"write_file"}, {"index.html"}, {"index.html"})
            dispatcher = ToolDispatcher(policy)

            result = dispatcher.dispatch(Action("1", "run_command", {"command": "dir"}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("unknown action", result.message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.tools'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/tools.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    action: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False


class ToolDispatcher:
    def __init__(self, policy: WorkspacePolicy):
        self.policy = policy

    def dispatch(self, action: Action) -> ToolResult:
        decision = check_action(action, self.policy)
        if not decision.allowed:
            return ToolResult(False, action.action, decision.reason, blocked=True)

        if action.action == "write_file":
            return self._write_file(action)
        if action.action == "replace_file":
            return self._write_file(action)
        if action.action == "read_file":
            return self._read_file(action)
        if action.action == "list_files":
            return self._list_files(action)
        if action.action == "finish":
            return ToolResult(True, "finish", "finish requested", {"summary": action.args.get("summary", "")})

        return ToolResult(False, action.action, f"unimplemented action: {action.action}", blocked=True)

    def _resolve(self, relative: str) -> Path:
        return self.policy.root / relative

    def _write_file(self, action: Action) -> ToolResult:
        path = self._resolve(action.args["path"])
        content = action.args.get("content", "")
        if not isinstance(content, str):
            return ToolResult(False, action.action, "content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(True, action.action, f"wrote {action.args['path']}", {"path": action.args["path"]})

    def _read_file(self, action: Action) -> ToolResult:
        path = self._resolve(action.args["path"])
        if not path.exists():
            return ToolResult(False, action.action, f"file not found: {action.args['path']}")
        return ToolResult(
            True,
            action.action,
            f"read {action.args['path']}",
            {"path": action.args["path"], "content": path.read_text(encoding="utf-8")},
        )

    def _list_files(self, action: Action) -> ToolResult:
        files = sorted(str(path.relative_to(self.policy.root)).replace("\\", "/") for path in self.policy.root.rglob("*") if path.is_file())
        return ToolResult(True, action.action, "listed files", {"files": files})
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/tools.py tests/test_tools.py
git commit -m "feat: add safe file tool dispatcher"
```

---

## Task 5: 静态 HTML Gate 与 Checklist 检查

**Files:**
- Create: `src/specgate/gate.py`
- Create: `tests/test_gate.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_gate.py`：

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_gate -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.gate'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/gate.py`：

```python
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
        self.tags.append(tag.lower())
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "meta" and attrs_dict.get("name", "").lower() == "viewport":
            self.has_viewport = True
        classes = attrs_dict.get("class", "")
        if "node" in classes.split():
            self.node_count += 1
        if tag.lower() == "input" and attrs_dict.get("type", "").lower() == "search":
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
    summary = "Gate 通过" if passed else "Gate 失败：" + "；".join(issue.repair_hint for issue in issues[:4])
    return GateResult(passed, checks, issues, summary)
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_gate -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/gate.py tests/test_gate.py
git commit -m "feat: add deterministic html gate"
```

---

## Task 6: Trace Store 与 Context Builder

**Files:**
- Create: `src/specgate/trace.py`
- Create: `src/specgate/context.py`
- Create: `tests/test_context.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_context.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.context import build_context_pack
from specgate.gate import GateCheck, GateIssue, GateResult
from specgate.trace import TraceStore


class ContextTests(unittest.TestCase):
    def test_trace_redacts_secret_like_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceStore(Path(tmp) / "trace.jsonl")

            trace.append("llm_response", {"text": "key sk-abc123456789"})

            raw = (Path(tmp) / "trace.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("sk-abc123456789", raw)
            self.assertIn("[REDACTED]", raw)

    def test_context_pack_contains_task_docs_and_gate_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n做知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec", encoding="utf-8")
            (root / "index.html").write_text("<html><body>draft</body></html>", encoding="utf-8")
            gate = GateResult(
                False,
                [GateCheck("node_count", False, "至少 10 个知识节点")],
                [GateIssue("too_few_nodes", "error", "知识节点不足", "0", "添加至少 10 个节点")],
                "Gate 失败：添加至少 10 个节点",
            )

            pack = build_context_pack(root, gate)

            self.assertIn("TASK_SPEC.md", pack)
            self.assertIn("CHECKLIST.md", pack)
            self.assertIn("Gate 失败", pack)
            self.assertIn("index.html 摘要", pack)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.context'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/trace.py`：

```python
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_-]{8,}"),
]


def redact(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class TraceStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": redact(payload),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
```

创建 `src/specgate/context.py`：

```python
from __future__ import annotations

from pathlib import Path

from specgate.gate import GateResult


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _artifact_summary(path: Path) -> str:
    if not path.exists():
        return "index.html 摘要：文件不存在"
    content = path.read_text(encoding="utf-8")
    return f"index.html 摘要：{len(content)} 字符，node 出现 {content.count('class=\"node\"') + content.count(\"class='node'\")} 次"


def build_context_pack(root: Path, latest_gate: GateResult | None) -> str:
    task_spec = _read_optional(root / "TASK_SPEC.md")
    checklist = _read_optional(root / "CHECKLIST.md")
    gate_summary = latest_gate.summary if latest_gate else "尚未运行 Gate"

    return "\n\n".join(
        [
            "你是 SpecGate harness 中的 coding agent。只输出严格 JSON action。",
            "## TASK_SPEC.md\n" + task_spec,
            "## CHECKLIST.md\n" + checklist,
            "## " + _artifact_summary(root / "index.html"),
            "## 最近 Gate 结果\n" + gate_summary,
        ]
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/trace.py src/specgate/context.py tests/test_context.py
git commit -m "feat: add trace store and context builder"
```

---

## Task 7: MockLLM 与 Agent Runner 主循环

**Files:**
- Create: `src/specgate/llm.py`
- Create: `src/specgate/runner.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_runner.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.runner import AgentRunner


BROKEN_HTML = "<html><head><title>x</title></head><body></body></html>"
FIXED_HTML = """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI for Coding Knowledge Navigator</title></head><body><input type="search">""" + "".join(
    f'<section class="node" data-related="rel{i}"><h2>Node {i}</h2><p>Spec Gate Checklist 定义 {i}</p></section>'
    for i in range(10)
) + "<script>function highlightRelations(){} function filterNodes(){}</script></body></html>"


class RunnerTests(unittest.TestCase):
    def test_gate_failure_feedback_changes_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n生成知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "write_file", "args": {"path": "index.html", "content": BROKEN_HTML}},
                    {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": FIXED_HTML}},
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file", "replace_file", "read_file", "list_files", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=5).run()

            self.assertTrue(result.passed)
            self.assertEqual(llm.calls, 3)
            self.assertIn("Node 9", (root / "index.html").read_text(encoding="utf-8"))

    def test_guardrail_block_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM([
                {"schema_version": "1", "action": "run_command", "args": {"command": "dir"}},
            ])
            policy = WorkspacePolicy(root, {"write_file"}, {"TASK_SPEC.md"}, {"index.html"})

            result = AgentRunner(root, llm, policy, max_steps=1).run()

            self.assertFalse(result.passed)
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("unknown action", trace_text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.llm'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/llm.py`：

```python
from __future__ import annotations

import json
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, context: str) -> str:
        ...


class MockLLM:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls = 0

    def complete(self, context: str) -> str:
        if self.calls >= len(self.responses):
            return json.dumps({"schema_version": "1", "action": "finish", "args": {"summary": "no more responses"}})
        response = self.responses[self.calls]
        self.calls += 1
        return json.dumps(response, ensure_ascii=False)
```

创建 `src/specgate/runner.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from specgate.actions import ActionParseError, parse_action
from specgate.context import build_context_pack
from specgate.gate import GateResult, run_html_gate
from specgate.llm import LLMClient
from specgate.policy import WorkspacePolicy
from specgate.tools import ToolDispatcher
from specgate.trace import TraceStore


@dataclass(frozen=True)
class RunResult:
    passed: bool
    steps: int
    final_gate: GateResult | None


class AgentRunner:
    def __init__(self, root: Path, llm: LLMClient, policy: WorkspacePolicy, max_steps: int = 5):
        self.root = root
        self.llm = llm
        self.policy = policy
        self.max_steps = max_steps
        self.dispatcher = ToolDispatcher(policy)
        self.trace = TraceStore(root / "runs" / "latest" / "trace.jsonl")

    def run(self) -> RunResult:
        latest_gate: GateResult | None = None
        for step in range(1, self.max_steps + 1):
            context = build_context_pack(self.root, latest_gate)
            raw = self.llm.complete(context)
            self.trace.append("llm_response", {"step": step, "text": raw})

            try:
                action = parse_action(raw)
            except ActionParseError as exc:
                self.trace.append("parse_error", {"step": step, "error": str(exc)})
                continue

            tool_result = self.dispatcher.dispatch(action)
            self.trace.append("tool_result", {"step": step, "result": tool_result.__dict__})

            if action.action in {"write_file", "replace_file"} and not tool_result.blocked:
                latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                self.trace.append("gate_result", {"step": step, "passed": latest_gate.passed, "summary": latest_gate.summary})

            if action.action == "finish":
                if latest_gate is None:
                    latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
                return RunResult(latest_gate.passed, step, latest_gate)

        if latest_gate is None:
            latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
        return RunResult(latest_gate.passed, self.max_steps, latest_gate)
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/llm.py src/specgate/runner.py tests/test_runner.py
git commit -m "feat: add mock llm agent runner loop"
```

---

## Task 8: 静态报告生成

**Files:**
- Create: `src/specgate/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_report.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.gate import GateCheck, GateResult
from specgate.report import generate_report


class ReportTests(unittest.TestCase):
    def test_generate_static_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate 通过")

            output = generate_report(root, gate, steps=3)

            self.assertTrue(output.exists())
            html = output.read_text(encoding="utf-8")
            self.assertIn("SpecGate Run Report", html)
            self.assertIn("Gate 通过", html)
            self.assertIn("3", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.report'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/report.py`：

```python
from __future__ import annotations

from html import escape
from pathlib import Path

from specgate.gate import GateResult


def generate_report(root: Path, gate: GateResult, steps: int) -> Path:
    report_dir = root / "reports" / "latest"
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "index.html"
    issues = "\n".join(f"<li>{escape(issue.code)}: {escape(issue.message)}</li>" for issue in gate.issues)
    checks = "\n".join(f"<li>{escape(check.code)}: {'PASS' if check.passed else 'FAIL'}</li>" for check in gate.checks)
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpecGate Run Report</title>
  <style>body{{font-family:Arial,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;line-height:1.5}}</style>
</head>
<body>
  <h1>SpecGate Run Report</h1>
  <p>Steps: {steps}</p>
  <p>Gate: {escape(gate.summary)}</p>
  <h2>Checks</h2>
  <ul>{checks}</ul>
  <h2>Issues</h2>
  <ul>{issues}</ul>
  <p><a href="../../index.html">Final artifact</a></p>
</body>
</html>"""
    output.write_text(html, encoding="utf-8")
    return output
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected:

```text
Ran 1 test
OK
```

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/report.py tests/test_report.py
git commit -m "feat: add static run report"
```

---

## Task 9: CLI、示例任务与端到端 mock demo

**Files:**
- Create: `src/specgate/config.py`
- Create: `src/specgate/cli.py`
- Create: `tests/test_cli.py`
- Create: `specgate.toml`
- Create: `examples/knowledge_nav/TASK_SPEC.md`
- Create: `examples/knowledge_nav/CHECKLIST.md`
- Create: `examples/knowledge_nav/specgate.toml`
- Modify: `README.md`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cli.py`：

```python
import tempfile
import unittest
from pathlib import Path

from specgate.cli import run_mock_demo


class CliTests(unittest.TestCase):
    def test_run_mock_demo_creates_artifact_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n生成 AI for Coding 知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")

            exit_code = run_mock_demo(root)

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "index.html").exists())
            self.assertTrue((root / "reports" / "latest" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.cli'
```

- [ ] **Step 3: 写最小实现**

创建 `src/specgate/config.py`：

```python
from __future__ import annotations

from pathlib import Path
import tomllib

from specgate.policy import WorkspacePolicy


def load_policy(config_path: Path) -> WorkspacePolicy:
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    return WorkspacePolicy(
        root=root,
        allowed_actions=set(data["policy"]["allowed_actions"]),
        allowed_read_paths=set(data["policy"]["allowed_read_paths"]),
        allowed_write_paths=set(data["policy"]["allowed_write_paths"]),
    )
```

创建 `src/specgate/cli.py`：

```python
from __future__ import annotations

import argparse
from pathlib import Path

from specgate.gate import run_html_gate
from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.report import generate_report
from specgate.runner import AgentRunner


def _fixed_demo_html() -> str:
    nodes = "".join(
        f'<section class="node" data-related="rel{i}"><h2>Node {i}</h2><p>Spec Gate Checklist 定义 {i}</p></section>'
        for i in range(10)
    )
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI for Coding Knowledge Navigator</title></head><body><input type="search">{nodes}<script>function highlightRelations(){{}} function filterNodes(){{}}</script></body></html>"""


def run_mock_demo(root: Path) -> int:
    llm = MockLLM(
        [
            {"schema_version": "1", "action": "write_file", "args": {"path": "index.html", "content": "<html><head><title>x</title></head><body></body></html>"}},
            {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": _fixed_demo_html()}},
            {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
        ]
    )
    policy = WorkspacePolicy(
        root=root,
        allowed_actions={"write_file", "replace_file", "read_file", "list_files", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )
    result = AgentRunner(root, llm, policy, max_steps=5).run()
    gate = result.final_gate or run_html_gate(root / "index.html", root / "CHECKLIST.md")
    generate_report(root, gate, result.steps)
    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specgate")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("run-mock-demo")
    demo.add_argument("workspace")
    args = parser.parse_args(argv)
    if args.command == "run-mock-demo":
        return run_mock_demo(Path(args.workspace))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

创建示例任务 `examples/knowledge_nav/TASK_SPEC.md`：

```markdown
# AI for Coding 知识体导航器

生成一个单文件 `index.html`，展示 AI for Coding 课程知识节点。

页面必须包含搜索、至少 10 个知识节点、节点定义、节点关系和移动端可读布局。
```

创建 `examples/knowledge_nav/CHECKLIST.md`：

```markdown
- 必须包含 Spec
- 必须包含 Gate
- 必须包含 Checklist
```

创建 `examples/knowledge_nav/specgate.toml`：

```toml
[policy]
allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]
allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]
allowed_write_paths = ["index.html"]
```

创建根目录 `specgate.toml`：

```toml
[policy]
allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]
allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]
allowed_write_paths = ["index.html"]
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected:

```text
Ran 1 test
OK
```

- [ ] **Step 5: 运行 demo**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

Expected:

```text
Exit code 0
```

Expected files:

```text
examples/knowledge_nav/index.html
examples/knowledge_nav/reports/latest/index.html
examples/knowledge_nav/runs/latest/trace.jsonl
```

- [ ] **Step 6: 更新 README**

在 `README.md` 增加：

```markdown
## Mock Demo

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

运行后打开：

```text
examples/knowledge_nav/reports/latest/index.html
```
```

- [ ] **Step 7: 提交**

```powershell
git add src/specgate/config.py src/specgate/cli.py tests/test_cli.py specgate.toml examples/knowledge_nav README.md
git commit -m "feat: add cli mock demo"
```

---

## Task 10: 凭据边界、Docker、CI 与最终文档

**Files:**
- Create: `src/specgate/credentials.py`
- Create: `tests/test_credentials.py`
- Create: `Dockerfile`
- Create: `.gitlab-ci.yml`
- Create: `REFLECTION.md`
- Modify: `README.md`
- Modify: `SPEC_PROCESS.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: 写凭据测试**

创建 `tests/test_credentials.py`：

```python
import unittest

from specgate.credentials import CredentialStatus, credential_status


class CredentialTests(unittest.TestCase):
    def test_mock_mode_needs_no_credentials(self):
        status = credential_status("mock")

        self.assertEqual(status, CredentialStatus(provider="mock", configured=True, safe_to_run=True, message="mock mode does not require credentials"))

    def test_unknown_real_provider_fails_closed(self):
        status = credential_status("openai")

        self.assertFalse(status.configured)
        self.assertFalse(status.safe_to_run)
        self.assertNotIn("sk-", status.message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credentials -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.credentials'
```

- [ ] **Step 3: 写最小凭据实现**

创建 `src/specgate/credentials.py`：

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialStatus:
    provider: str
    configured: bool
    safe_to_run: bool
    message: str


def credential_status(provider: str) -> CredentialStatus:
    if provider == "mock":
        return CredentialStatus("mock", True, True, "mock mode does not require credentials")
    return CredentialStatus(
        provider=provider,
        configured=False,
        safe_to_run=False,
        message="real provider credentials are not configured; use OS keyring support before enabling this provider",
    )
```

- [ ] **Step 4: 运行凭据测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_credentials -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: 创建 Dockerfile**

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY examples /app/examples

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "specgate.cli", "run-mock-demo", "examples/knowledge_nav"]
```

- [ ] **Step 6: 创建 GitLab CI**

创建 `.gitlab-ci.yml`：

```yaml
stages:
  - test
  - build

unit-test:
  stage: test
  image: python:3.11-slim
  script:
    - export PYTHONPATH=src
    - python -m unittest discover -s tests -v

docker-build:
  stage: build
  image: docker:26
  services:
    - docker:26-dind
  script:
    - docker build -t specgate:ci .
  rules:
    - if: $CI_COMMIT_BRANCH
```

- [ ] **Step 7: 运行全量测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected:

```text
Ran <数量> tests
OK
```

- [ ] **Step 8: 验证 Docker 构建**

Run:

```powershell
docker build -t specgate:local .
```

Expected:

```text
Successfully tagged specgate:local
```

如果本机没有 Docker，记录到 `AGENT_LOG.md`，并依赖 CI 的 `docker-build` job 验证。

- [ ] **Step 9: 更新 README**

在 `README.md` 增加：

```markdown
## Docker

```powershell
docker build -t specgate:local .
docker run --rm specgate:local
```

Mock 模式不需要 API key。真实 LLM 模式尚未作为 MVP 默认能力开放。

## CI

`.gitlab-ci.yml` 包含 `unit-test` job，会运行：

```text
python -m unittest discover -s tests -v
```

## 已知限制

- MVP 不开放 shell。
- MVP 不做 Playwright。
- MVP 只处理静态单页 HTML 任务。
- WebUI 是静态报告，不是实时 dashboard。
```

- [ ] **Step 10: 创建 REFLECTION 草稿**

创建 `REFLECTION.md`，只写结构和人工待补内容，不让 AI 代写最终反思：

```markdown
# REFLECTION

> 本文件必须由学生本人完成。AI 可辅助润色，但最终观点和案例必须由本人确认。

## Superpowers 哪些技能最有用

## TDD 在 AI 协作下的作用

## Subagent 工作流的有效边界

## SPEC / PLAN 质量如何影响实现

## 最有效的 prompt / context 策略

## 凭据与分发要求带来的工程思考

## 如果重做会改变什么

## 对 Superpowers 方法论的批判
```

- [ ] **Step 11: 更新过程记录**

在 `SPEC_PROCESS.md` 增加冷启动验证结果。冷启动尚未执行时写：

```markdown
## 冷启动验证记录

尚未执行。原因：实现计划刚完成，下一步需要另一个不同类型 agent 只读取 `SPEC.md` 和 `PLAN.md` 尝试 1-2 个任务。
```

在 `AGENT_LOG.md` 记录 Task 10 验证命令和结果。

- [ ] **Step 12: 提交**

```powershell
git add src/specgate/credentials.py tests/test_credentials.py Dockerfile .gitlab-ci.yml README.md SPEC_PROCESS.md AGENT_LOG.md REFLECTION.md
git commit -m "chore: add distribution ci and credential boundary"
```

---

## 后续深化：Context Eval Harness

- [x] 新增 context strategy：`baseline`、`compressed`、`injection-safe`。
- [x] 新增 eval runner，批量运行 mock eval cases。
- [x] 新增 prompt injection 与路径越权评估样例。
- [x] 输出 `eval-runs/latest/results.json`。
- [ ] 先用 MockLLM / StubLLM 完成确定性测试后，再考虑真实 LLM 实验。

## 2. 依赖与并行关系

必须顺序执行：

1. Task 1 项目骨架。
2. Task 2 Action parser。
3. Task 3 Policy/guardrail。
4. Task 4 Tools/dispatcher。
5. Task 5 Gate。
6. Task 6 Context/trace。
7. Task 7 Runner。
8. Task 8 Report。
9. Task 9 CLI/demo。
10. Task 10 CI/Docker/docs。

可并行部分：

- Task 5 Gate 和 Task 6 Context/trace 在 Task 2 后可以由不同 subagent 并行推进，但 Task 7 需要两者都完成。
- Task 8 Report 可在 Task 5 后并行完成。
- Task 10 的 Docker/CI 文档可在 Task 9 稳定后完成。

---

## 3. 冷启动验证要求

正式实现前，需要让另一个不同类型的 agent 只读取：

```text
SPEC.md
PLAN.md
```

要求它尝试 Task 2 和 Task 3，不能读取本对话历史。它如果对 `TASK_SPEC.md`、guardrail、测试命令、文件路径有疑问，必须暂停提问。将问题记录到 `SPEC_PROCESS.md`，再修订 `SPEC.md` 或 `PLAN.md`。

---

## 4. 自检清单

SPEC 覆盖：

- 自实现 agent 主循环：Task 7。
- LLM 抽象和 `MockLLM`：Task 7。
- JSON Action Protocol：Task 2。
- 工具分发：Task 4。
- Guardrail：Task 3 + Task 4 + Task 7 演示。
- Feedback loop：Task 5 + Task 6 + Task 7。
- Memory/context：Task 6。
- Config：Task 9。
- 静态 Web 报告：Task 8。
- HTML 任务输入 `TASK_SPEC.md` + `CHECKLIST.md`：Task 9。
- 凭据边界：Task 10。
- Docker 分发：Task 10。
- `.gitlab-ci.yml` 的 `unit-test` job：Task 10。
- `REFLECTION.md`：Task 10。

占位符扫描：

- 本计划不使用未决占位语作为实现步骤。
- `REFLECTION.md` 只创建人工反思结构，因为课程要求反思由学生本人完成；这不是实现占位符。

类型一致性：

- `Action`、`ToolResult`、`GateResult`、`TraceStore`、`MockLLM`、`AgentRunner` 在各任务中命名一致。
- 测试命令统一使用 `$env:PYTHONPATH="src"` 和 `python -m unittest`。
# 2026-07-10 Context Harness Deepening Implementation Plan

### Completion Status

- [x] Task 1 completed in `526f54c` - Lightweight Retrieval Core.
- [x] Task 2 completed in `ac4842a` - RAG Select Context Strategy.
- [x] Task 3 completed in `5c6a51b` - Retrieval Evidence in Trace, Metrics, Report, and Eval.
- [x] Task 4 completed in `2b0691c` - Deterministic Context Lifecycle Compression.
- [x] Task 5 completed in `a386dff` - Role Isolation Core.
- [x] Task 6 completed in `50bbb88` - Multi-Strategy Benchmark Aggregation.
- [x] Task 7 completed in `8a602cb` - Mock Eval Cases and Documentation.
- [x] Task 8 completed by the final process-evidence commit - Final Review, Process Evidence, and Verification.

## Task 7 Mock Eval Cases and Documentation

本任务补充三个 mock-first eval case：

1. `retrieval-context-select`：用于 `rag-select` 检索相关 implementation notes。
2. `context-compression-lifecycle`：用于 `compressed-rag` 展示 tool-result clearing 和关键约束保留。
3. `isolation-role-boundary`：用于 `isolated-harness` 展示 role context/state isolation evidence。

同步更新 `README.md`、`SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md` 和 `AGENT_LOG.md`，明确本阶段仍以 mock/stub LLM 作为核心验收路径，真实 LLM 实验继续后置。

本轮新增的正式实现计划见：

`docs/superpowers/plans/2026-07-10-context-harness-deepening.md`

目标是在 `feat-context-harness-deepening` 分支上按阶段完成：

1. Lightweight Retrieval Core
2. RAG Select Context Strategy
3. Retrieval Evidence in Trace, Metrics, Report, and Eval
4. Deterministic Context Lifecycle Compression
5. Role Isolation Core
6. Multi-Strategy Benchmark Aggregation
7. Mock Eval Cases and Documentation
8. Final Review, Process Evidence, and Verification

执行约束：

- 使用 mock/stub LLM 作为核心验收路径。
- 每个任务遵循 TDD。
- 每个任务完成后进行 spec review 和 code quality review。
- 每个任务独立提交，并把 commit hash 记录回本文件、`SPEC_PROCESS.md` 和 `AGENT_LOG.md`。
- 不提交 `examples/eval_cases/eval-runs/` 运行产物。

# 2026-07-14 Gate 与 HITL 正确性加固

详细设计与逐步计划：

- `docs/superpowers/specs/2026-07-14-gate-hitl-correctness-design.md`
- `docs/superpowers/plans/2026-07-14-gate-hitl-correctness.md`

完成状态：

- [x] Task 1：Checklist 确定性规则解析与评估。
- [x] Task 2：Gate 集成、输入摘要绑定与领域硬编码清理。
- [x] Task 3：Action schema 与 Runner outcome。
- [x] Task 4：审批队列 revision、跨进程锁与 CAS。
- [x] Task 5：Runner 真正暂停、最终 Gate 与可恢复 resume。
- [x] Task 6：Web 默认覆盖审批与发布摘要绑定。
- [x] Task 7：Web 审批 API、数据库协调与前端 revision。
- [x] Task 8：真实 approve/deny Web 流程、示例扫描、中文文档与回归。
- [ ] Git 提交哈希：等待用户按课程要求自行分批提交后回填。

本轮 Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作。所有新增行为均使用 mock/stub LLM 或纯确定性组件测试，不依赖真实 LLM 与网络。

# 2026-07-14 安全凭据存储

详细设计、路线与实施计划：

- `docs/superpowers/specs/2026-07-14-secure-credentials-design.md`
- `docs/superpowers/specs/2026-07-14-post-hardening-roadmap-design.md`
- `docs/superpowers/plans/2026-07-14-secure-credentials.md`

完成状态：

- [x] Task 1：系统 keyring 存储边界与稳定错误包装。
- [x] Task 2：CLI 环境变量优先、keyring 持久化并移除 `.env` 接口。
- [x] Task 3：Web 32 字节主密钥与 AES-256-GCM 核心。
- [x] Task 4：数据库 schema v2 与旧 HMAC `requires_reentry` 迁移。
- [x] Task 5：Web 加密凭据 repository、Settings 状态与 Runner 隔离。
- [x] Task 6：Web API 安全错误映射与前端凭据状态。
- [x] Task 7：secret sentinel 回归和中文使用/部署文档。
- [x] Task 8：全量验证与最终交付审查；本地 753 个测试通过，20 个既有平台权限场景跳过。

待用户提交后回填：

- Git commit：待填写。
- PR URL：待填写。
- GitHub Ubuntu CI：待填写。

本轮仍以 MockLLM 和确定性单元测试作为验收主链路。Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作。

## GitHub Pages 合并后热修复

- 根因：Pages workflow 在全新 Ubuntu runner 中未安装 `pyproject.toml` 声明的依赖，导入 CLI 时缺少 `keyring`；同一提交的 unit-test 与 docker-build 均已通过。
- 修复：在生成 mock demo 前执行 `python -m pip install -e .`，与 CI、Docker 安装方式保持一致。
- 回归：新增 workflow 顺序测试，防止以后再次先运行 CLI、后安装依赖。
- 远端验证：等待热修复合并到 `main` 后回填 Pages 结果。
