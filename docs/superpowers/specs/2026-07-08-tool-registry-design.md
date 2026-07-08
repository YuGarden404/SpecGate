# SpecGate 第二阶段设计：工具注册表

## 1. 背景

SpecGate 已经完成了 MVP 主闭环，并补齐了 Context Manifest 和运行级文件快照保护。

当前工具管理仍然停留在 `ToolDispatcher.dispatch()` 内部的硬编码分支：`write_file`、`replace_file`、`read_file`、`list_files`、`finish`。这可以执行，但不够像一个真正的 coding agent harness：工具有哪些、每个工具需要什么参数、属于什么权限类型、返回什么结果，都没有一个结构化位置可供 context、report 和测试复用。

本阶段目标是实现工具管理第一层：建立一个确定性 Tool Registry，把现有工具的能力和边界结构化，并把这份说明展示给 LLM 上下文和静态报告。范围只做“描述与注册”，不新增危险能力。

## 2. 目标

本阶段实现以下能力：

- 新增 `tool_registry.py`，集中定义现有工具元数据。
- 每个工具包含：
  - `name`
  - `description`
  - `permission`
  - `args_schema`
  - `result_schema`
- 注册现有工具：
  - `read_file`
  - `write_file`
  - `replace_file`
  - `list_files`
  - `finish`
- `ToolDispatcher` 使用 registry 判断未知工具，而不是只依赖硬编码 fallback。
- `build_context_pack()` 输出 `## Tool Registry`，让 LLM 明确可用动作和参数格式。
- 静态 report 展示工具注册表，方便评审看到工具边界。
- 单元测试覆盖工具元数据、context 输出和 report 输出。

## 3. 非目标

本阶段不做：

- 不新增 shell、网络、MCP 或浏览器工具。
- 不引入 `jsonschema`、`pydantic` 或外部依赖。
- 不改变 Action JSON 协议。
- 不把 registry 做成插件系统。
- 不实现复杂参数校验器。
- 不移除现有 `WorkspacePolicy`，权限执行仍由 policy 和 snapshot 负责。
- 不把 report 改造成复杂前端。

## 4. 推荐设计

新增模块：

```text
src/specgate/tool_registry.py
```

核心数据结构：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: str
    args_schema: dict[str, str]
    result_schema: dict[str, str]
```

核心函数：

```python
def default_tool_registry() -> dict[str, ToolSpec]:
    ...

def render_tool_registry_for_context(registry: dict[str, ToolSpec] | None = None) -> str:
    ...
```

权限类型使用简单字符串：

- `read`：读取 allowlist 内文件。
- `write`：写入 allowlist 内文件，需要 policy 和 snapshot 保护。
- `inspect`：列出工作区文件，不写入。
- `control`：控制 agent loop，例如 `finish`。

## 5. Tool Spec 内容

### read_file

- `permission`: `read`
- `args_schema`: `{"path": "relative path allowed by policy"}`
- `result_schema`: `{"path": "relative path", "content": "utf-8 text content"}`

### write_file

- `permission`: `write`
- `args_schema`: `{"path": "relative path allowed by policy", "content": "utf-8 text content"}`
- `result_schema`: `{"path": "written relative path"}`

### replace_file

- `permission`: `write`
- `args_schema`: `{"path": "relative path allowed by policy", "content": "utf-8 text content"}`
- `result_schema`: `{"path": "replaced relative path"}`

### list_files

- `permission`: `inspect`
- `args_schema`: `{}`
- `result_schema`: `{"files": "list of relative paths"}`

### finish

- `permission`: `control`
- `args_schema`: `{"summary": "short final summary"}`
- `result_schema`: `{"summary": "final summary"}`

## 6. 接入点

### 6.1 ToolDispatcher

`ToolDispatcher` 初始化时加载默认 registry：

```python
class ToolDispatcher:
    def __init__(
        self,
        policy: WorkspacePolicy,
        snapshot: FileSnapshot | None = None,
        registry: dict[str, ToolSpec] | None = None,
    ):
        self.registry = registry or default_tool_registry()
```

`dispatch()` 顺序：

1. 如果 `action.action` 不在 registry 中，返回 blocked：`unknown action: <name>`。
2. 再执行现有 `check_action(action, policy)`。
3. 再进入具体工具分发分支。

这样未知工具的来源更明确：registry 是工具目录，policy 是工作区权限边界。

### 6.2 Context Pack

`build_context_pack()` 增加：

```text
## Tool Registry
- write_file [write]: ...
  args: path, content
```

这让 LLM 在每轮调用前看到工具边界，而不是只依赖 prompt 的一句话。

### 6.3 Report

`generate_report()` 增加一个 `Tools` 区块，展示：

- 工具名。
- 权限类型。
- 简短描述。

report 不展示完整 schema 也可以，但至少要让评审看到 harness 工具面。

## 7. 错误处理

- registry 中没有的 action 直接 blocked。
- registry 只描述工具，不替代 `parse_action()` 的 JSON 结构校验。
- registry 只描述权限类型，不替代 `WorkspacePolicy` 的路径 allowlist 检查。
- report 渲染 registry 时需要 HTML escape，避免工具说明影响静态页面。

## 8. 测试计划

新增测试：

```text
tests/test_tool_registry.py
```

覆盖：

- 默认 registry 包含 5 个现有工具。
- `write_file` 和 `replace_file` 权限为 `write`。
- `render_tool_registry_for_context()` 包含工具名、权限和参数名。

更新测试：

```text
tests/test_tools.py
```

覆盖：

- registry 中不存在的 action 被 blocked，并返回 `unknown action`。

更新测试：

```text
tests/test_context.py
```

覆盖：

- context pack 包含 `Tool Registry`。
- context pack 包含 `write_file` 和 `finish`。

更新测试：

```text
tests/test_report.py
```

覆盖：

- report HTML 包含 `Tools`。
- report HTML 包含 `write_file` 和 `finish`。

## 9. 对现有行为的影响

预期兼容：

- 现有 Action JSON 不变。
- 现有 policy allowlist 不变。
- 现有 snapshot 写入保护不变。
- CLI 命令不变。
- Mock demo 不需要改任务输入。

预期改进：

- 工具能力从硬编码分支变成可测试、可展示的注册表。
- LLM context 能明确看到工具边界。
- 静态 report 能展示 harness 的工具管理能力。
- 后续如果扩展真实 LLM 或工具审批，可以复用 registry 元数据。

## 10. 验收标准

- 新增 tool registry 单元测试通过。
- context pack 测试通过并包含 `Tool Registry`。
- report 测试通过并包含工具区块。
- 全量测试 `python -m unittest discover -s tests -v` 通过。
- mock demo 仍能运行并生成报告。
- 不引入 shell、网络工具、外部依赖或复杂前端。
