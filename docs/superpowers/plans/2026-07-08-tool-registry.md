# Tool Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 SpecGate 增加结构化工具注册表，让现有工具的名称、权限、参数和结果说明可以被测试、写入 context pack，并展示在静态报告中。

**Architecture:** 新增 `tool_registry.py` 集中定义现有工具元数据；`ToolDispatcher` 使用 registry 识别未知 action；`context.py` 渲染 `Tool Registry` 给 LLM；`report.py` 渲染工具区块给评审。工具执行、policy、snapshot 和 Action 协议保持兼容。

**Tech Stack:** Python 3.11 标准库、`dataclasses`、`html.escape`、`unittest`、现有 SpecGate 模块。

---

## File Structure

- Create: `src/specgate/tool_registry.py`
  - 定义 `ToolSpec`。
  - 实现 `default_tool_registry()`。
  - 实现 `render_tool_registry_for_context()`。
- Create: `tests/test_tool_registry.py`
  - 测试默认工具集合、权限和 context 渲染。
- Modify: `src/specgate/tools.py`
  - `ToolDispatcher` 接收可选 registry。
  - `dispatch()` 先查 registry，再查 policy。
- Modify: `tests/test_tools.py`
  - 确认未知 action 由 registry 拦截。
- Modify: `src/specgate/context.py`
  - 增加 `## Tool Registry` 区块。
- Modify: `tests/test_context.py`
  - 断言 context pack 包含工具注册表。
- Modify: `src/specgate/report.py`
  - 增加 `Tools` 区块。
- Modify: `tests/test_report.py`
  - 断言 report 包含 `Tools`、`write_file`、`finish`。
- Modify: `README.md`
  - 简述工具注册表能力。
- Modify: `AGENT_LOG.md`
  - 记录工具管理第一层实现和验证结果。

---

## Task 1: 新增 Tool Registry

**Files:**
- Create: `tests/test_tool_registry.py`
- Create: `src/specgate/tool_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tool_registry.py`:

```python
import unittest

from specgate.tool_registry import default_tool_registry, render_tool_registry_for_context


class ToolRegistryTests(unittest.TestCase):
    def test_default_registry_contains_mvp_tools(self):
        registry = default_tool_registry()

        self.assertEqual(
            set(registry),
            {"read_file", "write_file", "replace_file", "list_files", "finish"},
        )

    def test_write_tools_have_write_permission(self):
        registry = default_tool_registry()

        self.assertEqual(registry["write_file"].permission, "write")
        self.assertEqual(registry["replace_file"].permission, "write")
        self.assertIn("content", registry["write_file"].args_schema)

    def test_render_tool_registry_for_context(self):
        rendered = render_tool_registry_for_context()

        self.assertIn("write_file [write]", rendered)
        self.assertIn("finish [control]", rendered)
        self.assertIn("args: path, content", rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tool_registry -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.tool_registry'
```

- [ ] **Step 3: Implement tool registry**

Create `src/specgate/tool_registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: str
    args_schema: dict[str, str]
    result_schema: dict[str, str]


def default_tool_registry() -> dict[str, ToolSpec]:
    tools = [
        ToolSpec(
            "read_file",
            "Read a UTF-8 text file allowed by workspace policy.",
            "read",
            {"path": "relative path allowed by policy"},
            {"path": "relative path", "content": "utf-8 text content"},
        ),
        ToolSpec(
            "write_file",
            "Write a UTF-8 text file allowed by workspace policy and snapshot protection.",
            "write",
            {"path": "relative path allowed by policy", "content": "utf-8 text content"},
            {"path": "written relative path"},
        ),
        ToolSpec(
            "replace_file",
            "Replace a UTF-8 text file allowed by workspace policy and snapshot protection.",
            "write",
            {"path": "relative path allowed by policy", "content": "utf-8 text content"},
            {"path": "replaced relative path"},
        ),
        ToolSpec(
            "list_files",
            "List files inside the workspace.",
            "inspect",
            {},
            {"files": "list of relative paths"},
        ),
        ToolSpec(
            "finish",
            "Finish the agent loop with a short summary.",
            "control",
            {"summary": "short final summary"},
            {"summary": "final summary"},
        ),
    ]
    return {tool.name: tool for tool in tools}


def render_tool_registry_for_context(registry: dict[str, ToolSpec] | None = None) -> str:
    selected = registry or default_tool_registry()
    lines: list[str] = []
    for name in sorted(selected):
        tool = selected[name]
        args = ", ".join(tool.args_schema) if tool.args_schema else "none"
        results = ", ".join(tool.result_schema) if tool.result_schema else "none"
        lines.append(f"- {tool.name} [{tool.permission}]: {tool.description}")
        lines.append(f"  args: {args}")
        lines.append(f"  result: {results}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run registry tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tool_registry -v
```

Expected:

```text
Ran 3 tests ... OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: 新增工具注册表"
```

---

## Task 2: ToolDispatcher 使用 Registry 判断未知工具

**Files:**
- Modify: `src/specgate/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Update test expectation**

Modify `tests/test_tools.py`, in `test_blocked_action_returns_tool_result`, keep the existing assertion:

```python
self.assertIn("unknown action", result.message)
```

Add this assertion:

```python
self.assertEqual(result.action, "run_command")
```

This test already passes by behavior, but after registry integration it proves action identity is preserved. Add a custom registry test:

```python
    def test_custom_registry_blocks_tools_not_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(root, {"write_file"}, {"index.html"}, {"index.html"})
            dispatcher = ToolDispatcher(policy, registry={})

            result = dispatcher.dispatch(Action("1", "write_file", {"path": "index.html", "content": "x"}))

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("unknown action", result.message)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
TypeError: ToolDispatcher.__init__() got an unexpected keyword argument 'registry'
```

- [ ] **Step 3: Update ToolDispatcher**

Modify `src/specgate/tools.py`, add import:

```python
from specgate.tool_registry import ToolSpec, default_tool_registry
```

Change initializer:

```python
class ToolDispatcher:
    def __init__(
        self,
        policy: WorkspacePolicy,
        snapshot: FileSnapshot | None = None,
        registry: dict[str, ToolSpec] | None = None,
    ):
        self.policy = policy
        self.snapshot = snapshot
        self.registry = default_tool_registry() if registry is None else registry
```

At the top of `dispatch()` add:

```python
        if action.action not in self.registry:
            return ToolResult(False, action.action, f"unknown action: {action.action}", blocked=True)
```

Leave the existing policy check immediately after registry check.

- [ ] **Step 4: Run tool tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
Ran 5 tests ... OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/tools.py tests/test_tools.py
git commit -m "feat: 让工具分发器使用注册表"
```

---

## Task 3: Context Pack 输出 Tool Registry

**Files:**
- Modify: `src/specgate/context.py`
- Modify: `tests/test_context.py`

- [ ] **Step 1: Write failing context assertions**

Modify `tests/test_context.py`, in `test_context_pack_contains_task_docs_and_gate_summary`, add:

```python
self.assertIn("Tool Registry", pack)
self.assertIn("write_file", pack)
self.assertIn("finish", pack)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context -v
```

Expected:

```text
AssertionError: 'Tool Registry' not found in ...
```

- [ ] **Step 3: Update context rendering**

Modify `src/specgate/context.py`, add import:

```python
from specgate.tool_registry import render_tool_registry_for_context
```

In `build_context_pack()`, insert this section after the fixed agent instruction:

```python
            "## Tool Registry\n" + render_tool_registry_for_context(),
```

- [ ] **Step 4: Run context tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context tests.test_tool_registry -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/context.py tests/test_context.py
git commit -m "feat: 在context pack中加入工具注册表"
```

---

## Task 4: Report 展示 Tool Registry

**Files:**
- Modify: `src/specgate/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: Write failing report assertions**

Modify `tests/test_report.py`, in `test_generate_static_report`, add:

```python
self.assertIn("Tools", html)
self.assertIn("write_file", html)
self.assertIn("finish", html)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected:

```text
AssertionError: 'Tools' not found in ...
```

- [ ] **Step 3: Update report generation**

Modify `src/specgate/report.py`, add import:

```python
from specgate.tool_registry import default_tool_registry
```

Inside `generate_report()`, before `html = ...`, add:

```python
    tools = "\n".join(
        f"<li><strong>{escape(tool.name)}</strong> [{escape(tool.permission)}]: {escape(tool.description)}</li>"
        for tool in default_tool_registry().values()
    )
```

Add this block before `Final artifact`:

```html
  <h2>Tools</h2>
  <ul>{tools}</ul>
```

- [ ] **Step 4: Run report tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected:

```text
Ran 1 test ... OK
```

- [ ] **Step 5: Run CLI regression**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected:

```text
Ran 1 test ... OK
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/specgate/report.py tests/test_report.py
git commit -m "feat: 在静态报告中展示工具注册表"
```

---

## Task 5: 文档、日志与全量验证

**Files:**
- Modify: `README.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Update README**

In `README.md`, after the `## 上下文管理` section, add:

```markdown
## 工具管理

SpecGate 使用 `Tool Registry` 结构化描述可用工具。当前注册的工具包括 `read_file`、`write_file`、`replace_file`、`list_files` 和 `finish`。注册表会进入 context pack，并展示在静态报告中；实际权限仍由 `WorkspacePolicy` 和文件快照保护共同执行。
```

- [ ] **Step 2: Update AGENT_LOG**

Append to `AGENT_LOG.md`:

```markdown
## 2026-07-08

- Task：第二阶段工具注册表。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/tool_registry.py`，定义现有工具的名称、权限、参数和结果说明。
  - 新增 `tests/test_tool_registry.py`，覆盖默认工具集合、权限和 context 渲染。
  - 更新 `src/specgate/tools.py`，让工具分发器先检查 registry。
  - 更新 `src/specgate/context.py`，让 context pack 输出 Tool Registry。
  - 更新 `src/specgate/report.py`，让静态报告展示工具列表。
  - 更新 `README.md`，说明工具管理边界。
- 代码作用：
  - 将工具能力从硬编码分支提升为可测试、可展示的结构化注册表。
  - 不新增 shell、网络、MCP 或浏览器工具。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认先让 Context / Safety / Tooling 三个方向都有可测试第一层，再考虑深挖。
```

- [ ] **Step 3: Run full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Run mock demo**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

Expected:

```text
exit code 0
```

The CLI may print no output. If so, verify `examples/knowledge_nav/reports/latest/index.html` exists.

- [ ] **Step 5: Check diff hygiene**

Run:

```powershell
git diff --check
git status --short
```

Expected:

```text
git diff --check
# no whitespace errors

git status --short
 M AGENT_LOG.md
 M README.md
```

Windows LF/CRLF warnings are acceptable if no whitespace errors are reported.

- [ ] **Step 6: Commit**

Run:

```powershell
git add README.md AGENT_LOG.md
git commit -m "docs: 记录工具注册表验证结果"
```

---

## Final Verification

After all tasks:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m specgate.cli run-mock-demo examples/knowledge_nav
git log --oneline -8
git status
```

Expected:

- 全量测试通过。
- mock demo 通过。
- 最近提交包含：
  - `docs: 记录工具注册表验证结果`
  - `feat: 在静态报告中展示工具注册表`
  - `feat: 在context pack中加入工具注册表`
  - `feat: 让工具分发器使用注册表`
  - `feat: 新增工具注册表`
- 工作区干净。
