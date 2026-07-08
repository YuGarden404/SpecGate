# SpecGate 第二阶段设计：安全修改检测

## 1. 背景

SpecGate 已经具备静态 HTML 生成/修复闭环，并且新增了 Context Manifest，用于解释哪些文件进入 LLM 上下文。

下一步需要补齐 coding agent harness 的另一个关键安全能力：保护用户工作区。真实编码智能体常见风险是，用户在 agent 运行期间手动修改了文件，但 agent 后续仍按旧上下文写入，导致人工修改被覆盖。这个问题不能只靠 prompt 约束，需要由 harness 在工具层拦截。

本阶段目标是实现一层确定性文件快照机制：runner 启动时记录允许写入文件的初始状态，工具写入前检查目标文件是否被外部修改。如果检测到变化，拒绝写入并记录 trace。

## 2. 目标

本阶段实现以下能力：

- 在一次 run 开始时，对 `allowed_write_paths` 中的文件创建快照。
- 文件存在时记录内容的 `sha256`。
- 文件不存在时记录为 missing。
- `write_file` / `replace_file` 执行前检查目标文件当前状态。
- 如果文件自 run 开始后发生外部变化，阻止写入。
- 阻止结果以 `ToolResult(blocked=True)` 返回，并写入 runner trace。
- 保持现有 CLI、MockLLM、Gate 和 policy 接口基本不变。
- 使用单元测试证明未变文件允许写入、已变文件被阻止、missing 文件状态正确处理。

## 3. 非目标

本阶段不做：

- 不做交互式用户审批。
- 不做三方 merge。
- 不调用 Git diff 或 Git index。
- 不处理多进程文件锁。
- 不开放 shell。
- 不引入外部依赖。
- 不检测非 allowlist 写入路径，因为这已经由 `WorkspacePolicy` 负责。
- 不把安全检测做成复杂权限系统；正式 Tool Registry 会在后续单独实现。

## 4. 推荐设计

新增模块：

```text
src/specgate/snapshot.py
```

核心数据结构：

```python
@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class SnapshotDecision:
    allowed: bool
    reason: str
```

核心类：

```python
class FileSnapshot:
    @classmethod
    def capture(cls, root: Path, relative_paths: set[str]) -> FileSnapshot:
        ...

    def check_unchanged(self, relative_path: str) -> SnapshotDecision:
        ...

    def update_after_write(self, relative_path: str) -> None:
        ...
```

判断规则：

- 启动时存在，写入前仍存在且 hash 相同：允许。
- 启动时存在，写入前不存在：阻止。
- 启动时存在，写入前 hash 不同：阻止。
- 启动时不存在，写入前仍不存在：允许。
- 启动时不存在，写入前出现：阻止。
- 未在快照中的路径：阻止，原因是路径不在快照范围内。正常情况下这不会发生，因为 `WorkspacePolicy` 已经先检查 allowlist。
- SpecGate 自己成功写入后，必须调用 `update_after_write()` 更新该文件的快照状态。否则第一次写入后，第二次修复写入会被误判为外部修改。

## 5. 接入点

### 5.1 ToolDispatcher

`ToolDispatcher` 增加可选参数：

```python
class ToolDispatcher:
    def __init__(self, policy: WorkspacePolicy, snapshot: FileSnapshot | None = None):
        ...
```

写入前顺序：

1. 先执行现有 `check_action()`。
2. 如果不是写入动作，按原逻辑执行。
3. 如果是 `write_file` / `replace_file`，并且存在 snapshot，则调用 `snapshot.check_unchanged(path)`。
4. 如果 snapshot 不允许，返回：

```python
ToolResult(
    ok=False,
    action=action.action,
    message="file changed since run started: index.html",
    data={"path": "index.html"},
    blocked=True,
)
```

5. 只有检查通过后才写入文件。
6. 写入成功后调用 `snapshot.update_after_write(path)`，把 harness 自己刚完成的写入记录为新的可信基线。

### 5.2 AgentRunner

`AgentRunner.__init__()` 中创建快照：

```python
snapshot = FileSnapshot.capture(root, policy.allowed_write_paths)
self.dispatcher = ToolDispatcher(policy, snapshot)
```

runner 的 trace 写入逻辑不用改，因为 `tool_result` 已经会被记录。这样安全拒绝事件天然进入 `trace.jsonl`。

## 6. 数据流

```text
AgentRunner 初始化
  -> FileSnapshot.capture(root, allowed_write_paths)
  -> ToolDispatcher(policy, snapshot)

LLM 输出 write_file / replace_file
  -> parse_action
  -> check_action(policy)
  -> snapshot.check_unchanged(path)
    -> unchanged: 执行写入
    -> changed: 返回 blocked ToolResult
  -> trace.append("tool_result", ...)
```

## 7. 错误处理

- 读取文件 hash 失败时，按 changed 处理，阻止写入，避免覆盖未知状态。
- `relative_path` 不在快照范围内时阻止写入。
- snapshot 检查失败不会抛异常给 runner，而是转成 `ToolResult`，保持 agent loop 可继续。
- policy 拒绝优先于 snapshot 拒绝；路径越界和 allowlist 问题仍由 `WorkspacePolicy` 解释。
- `update_after_write()` 只在工具写入成功后调用；被 policy 或 snapshot 拦截的写入不能更新快照。

## 8. 测试计划

新增测试文件：

```text
tests/test_snapshot.py
```

覆盖：

- `capture()` 能记录已存在文件 hash。
- 文件未变时 `check_unchanged()` 允许。
- 文件内容被修改后 `check_unchanged()` 拒绝。
- 启动时不存在、写入前仍不存在时允许。
- 启动时不存在、写入前突然出现时拒绝。
- 未在快照范围内的路径拒绝。
- SpecGate 自己成功写入后，后续写入同一路径不应被误判为外部修改。

更新测试：

```text
tests/test_tools.py
```

新增：

- 当 snapshot 检测到文件变化时，`write_file` 返回 blocked，原文件内容不被覆盖。

更新测试：

```text
tests/test_runner.py
```

新增：

- 构造一个 LLM，在第一次写入后由测试中的自定义 LLM 修改 `index.html`，第二次写入时应被 snapshot 拦截，并且 trace 中包含 `file changed since run started`。

## 9. 对现有行为的影响

预期兼容：

- CLI 命令不变。
- `WorkspacePolicy` 数据结构不变。
- `MockLLM` 基础用法不变。
- `ToolDispatcher(policy)` 仍然可用；不传 snapshot 时保持原行为，方便已有工具测试。
- `AgentRunner` 会默认启用 snapshot。

预期改进：

- harness 能证明自己不会盲目覆盖用户运行期间的文件修改。
- 安全拒绝事件进入 trace，可被报告和日志追溯。
- 为后续 Tool Registry 的权限说明提供一个真实安全机制案例。

## 10. 验收标准

- 新增 snapshot 单元测试通过。
- 工具层安全拦截测试通过。
- runner trace 安全事件测试通过。
- 全量测试 `python -m unittest discover -s tests -v` 通过。
- mock demo 仍能正常运行并生成报告。
- 不引入 shell、Git diff、真实 LLM 或外部依赖。
