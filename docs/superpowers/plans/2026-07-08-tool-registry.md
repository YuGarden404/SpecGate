# Tool Registry 实施计划

> **给执行智能体：** 必须配合 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 执行本计划。步骤使用复选框记录执行状态。

**目标：** 为 SpecGate 增加结构化工具注册表，让现有工具的名称、权限、参数和结果说明可以被测试、写入 context pack，并展示在静态报告中。

**架构：** 新增 `tool_registry.py` 集中定义现有工具元数据；`ToolDispatcher` 使用 registry 识别未知 action；`context.py` 渲染 `Tool Registry` 给 LLM；`report.py` 渲染工具区块给评审。工具执行、policy、snapshot 和 Action 协议保持兼容。

**技术栈：** Python 3.11 标准库、`dataclasses`、`html.escape`、`unittest`、现有 SpecGate 模块。

---

## 文件结构

- 创建：`src/specgate/tool_registry.py`
  - 定义 `ToolSpec`。
  - 实现 `default_tool_registry()`。
  - 实现 `render_tool_registry_for_context()`。
- 创建：`tests/test_tool_registry.py`
  - 测试默认工具集合、权限和 context 渲染。
- 修改：`src/specgate/tools.py`
  - `ToolDispatcher` 接收可选 registry。
  - `dispatch()` 先查 registry，再查 policy。
- 修改：`tests/test_tools.py`
  - 确认未知 action 由 registry 拦截。
- 修改：`src/specgate/context.py`
  - 增加 `## Tool Registry` 区块。
- 修改：`tests/test_context.py`
  - 断言 context pack 包含工具注册表。
- 修改：`src/specgate/report.py`
  - 增加 `Tools` 区块。
- 修改：`tests/test_report.py`
  - 断言 report 包含 `Tools`、`write_file`、`finish`。
- 修改：`README.md`
  - 简述工具注册表能力。
- 修改：`AGENT_LOG.md`
  - 记录工具管理第一层实现和验证结果。

---

## Task 1：新增 Tool Registry

**文件：**
- 创建：`tests/test_tool_registry.py`
- 创建：`src/specgate/tool_registry.py`

- [x] **步骤 1：写失败测试**

创建 `tests/test_tool_registry.py`：

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

- [x] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tool_registry -v
```

预期：

```text
ModuleNotFoundError: No module named 'specgate.tool_registry'
```

- [x] **步骤 3：实现工具注册表**

创建 `src/specgate/tool_registry.py`：

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

- [x] **步骤 4：运行注册表测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tool_registry -v
```

预期：

```text
Ran 3 tests ... OK
```

- [x] **步骤 5：提交**

运行：

```powershell
git add src/specgate/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: 新增工具注册表"
```

---

## Task 2：ToolDispatcher 使用 Registry 判断未知工具

**文件：**
- 修改：`src/specgate/tools.py`
- 修改：`tests/test_tools.py`

- [x] **步骤 1：更新测试期望**

在 `tests/test_tools.py` 的 `test_blocked_action_returns_tool_result` 中，保留现有断言：

```python
self.assertIn("unknown action", result.message)
```

增加这个断言：

```python
self.assertEqual(result.action, "run_command")
```

这个测试目前已经能通过；接入 registry 后，它用于证明被拦截 action 的名称仍然被保留。继续添加一个自定义 registry 测试：

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

- [x] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

预期：

```text
TypeError: ToolDispatcher.__init__() got an unexpected keyword argument 'registry'
```

- [x] **步骤 3：更新 ToolDispatcher**

修改 `src/specgate/tools.py`，增加 import：

```python
from specgate.tool_registry import ToolSpec, default_tool_registry
```

修改初始化函数：

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

在 `dispatch()` 开头加入：

```python
        if action.action not in self.registry:
            return ToolResult(False, action.action, f"unknown action: {action.action}", blocked=True)
```

保留现有 policy 检查，但让它位于 registry 检查之后。

- [x] **步骤 4：运行工具测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

预期：

```text
Ran 5 tests ... OK
```

- [x] **步骤 5：提交**

运行：

```powershell
git add src/specgate/tools.py tests/test_tools.py
git commit -m "feat: 让工具分发器使用注册表"
```

---

## Task 3：Context Pack 输出 Tool Registry

**文件：**
- 修改：`src/specgate/context.py`
- 修改：`tests/test_context.py`

- [x] **步骤 1：写失败断言**

在 `tests/test_context.py` 的 `test_context_pack_contains_task_docs_and_gate_summary` 中增加：

```python
self.assertIn("Tool Registry", pack)
self.assertIn("write_file", pack)
self.assertIn("finish", pack)
```

- [x] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context -v
```

预期：

```text
AssertionError: 'Tool Registry' not found in ...
```

- [x] **步骤 3：更新 context 渲染**

修改 `src/specgate/context.py`，增加 import：

```python
from specgate.tool_registry import render_tool_registry_for_context
```

在 `build_context_pack()` 中，把下面这段插入固定 agent 指令之后：

```python
            "## Tool Registry\n" + render_tool_registry_for_context(),
```

- [x] **步骤 4：运行 context 测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context tests.test_tool_registry -v
```

预期：

```text
OK
```

- [x] **步骤 5：提交**

运行：

```powershell
git add src/specgate/context.py tests/test_context.py
git commit -m "feat: 在context pack中加入工具注册表"
```

---

## Task 4：Report 展示 Tool Registry

**文件：**
- 修改：`src/specgate/report.py`
- 修改：`tests/test_report.py`

- [x] **步骤 1：写失败断言**

在 `tests/test_report.py` 的 `test_generate_static_report` 中增加：

```python
self.assertIn("Tools", html)
self.assertIn("write_file", html)
self.assertIn("finish", html)
```

- [x] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

预期：

```text
AssertionError: 'Tools' not found in ...
```

- [x] **步骤 3：更新报告生成逻辑**

修改 `src/specgate/report.py`，增加 import：

```python
from specgate.tool_registry import default_tool_registry
```

在 `generate_report()` 内部、`html = ...` 之前加入：

```python
    tools = "\n".join(
        f"<li><strong>{escape(tool.name)}</strong> [{escape(tool.permission)}]: {escape(tool.description)}</li>"
        for tool in default_tool_registry().values()
    )
```

在 `Final artifact` 链接之前加入：

```html
  <h2>Tools</h2>
  <ul>{tools}</ul>
```

- [x] **步骤 4：运行 report 测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

预期：

```text
Ran 1 test ... OK
```

- [x] **步骤 5：运行 CLI 回归测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

预期：

```text
Ran 1 test ... OK
```

- [x] **步骤 6：提交**

运行：

```powershell
git add src/specgate/report.py tests/test_report.py
git commit -m "feat: 在静态报告中展示工具注册表"
```

---

## Task 5：文档、日志与全量验证

**文件：**
- 修改：`README.md`
- 修改：`AGENT_LOG.md`

- [x] **步骤 1：更新 README**

在 `README.md` 的 `## 上下文管理` 小节后加入：

```markdown
## 工具管理

SpecGate 使用 `Tool Registry` 结构化描述可用工具。当前注册的工具包括 `read_file`、`write_file`、`replace_file`、`list_files` 和 `finish`。注册表会进入 context pack，并展示在静态报告中；实际权限仍由 `WorkspacePolicy` 和文件快照保护共同执行。
```

- [x] **步骤 2：更新 AGENT_LOG**

追加到 `AGENT_LOG.md`：

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

- [x] **步骤 3：运行全量测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

预期：

```text
OK
```

- [x] **步骤 4：运行 mock demo**

运行：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

预期：

```text
退出码为 0
```

CLI 可能没有输出。若无输出，确认 `examples/knowledge_nav/reports/latest/index.html` 存在即可。

- [x] **步骤 5：检查 diff 卫生**

运行：

```powershell
git diff --check
git status --short
```

预期：

```text
git diff --check
# no whitespace errors

git status --short
 M AGENT_LOG.md
 M README.md
```

如果没有 whitespace error，Windows 的 LF/CRLF warning 可以接受。

- [x] **步骤 6：提交**

运行：

```powershell
git add README.md AGENT_LOG.md
git commit -m "docs: 记录工具注册表验证结果"
```

---

## 最终验证

所有任务完成后运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m specgate.cli run-mock-demo examples/knowledge_nav
git log --oneline -8
git status
```

预期：

- 全量测试通过。
- mock demo 通过。
- 最近提交包含：
  - `docs: 记录工具注册表验证结果`
  - `feat: 在静态报告中展示工具注册表`
  - `feat: 在context pack中加入工具注册表`
  - `feat: 让工具分发器使用注册表`
  - `feat: 新增工具注册表`
- 工作区干净。
