# SpecGate 第二阶段设计：上下文管理增强

## 1. 背景

SpecGate 的 MVP 已经能围绕一个静态 HTML 任务完成 `TASK_SPEC.md`、`CHECKLIST.md`、`index.html`、Gate、trace 和 report 的闭环。

当前 `context.py` 的实现仍然是最小版本：固定读取 `TASK_SPEC.md`、`CHECKLIST.md` 和 `index.html` 摘要，再拼接最近 Gate 结果。这能证明 MVP 机制，但还不能体现更真实 coding agent 需要面对的问题：一个任务目录里可能有 README、已有代码、运行日志、报告、缓存文件和无关文件，harness 必须决定哪些内容进入 LLM 上下文，哪些内容跳过，并且要能解释这个选择。

本阶段目标是实现一个轻量、确定性、可测试的 Context Manifest 机制，让 SpecGate 从“固定拼接文件”升级为“扫描任务目录并按预算选择上下文”。

## 2. 目标

本阶段实现以下能力：

- 扫描目标任务目录中的文本文件。
- 按文件重要性选择上下文内容。
- 默认优先包含 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`。
- 默认跳过 `runs/`、`reports/`、`.git/`、`__pycache__/` 等运行产物或缓存目录。
- 设置总字符预算，避免一次性把过多内容喂给 LLM。
- 生成 Context Manifest，记录每个文件是 selected、skipped 还是 truncated，以及原因。
- `build_context_pack()` 使用选择结果生成上下文，并保留最近 Gate 结果。
- 单元测试能断言选择顺序、跳过规则和预算行为。

## 3. 非目标

本阶段不做：

- 不做向量数据库或复杂 RAG。
- 不做真实 LLM 接入。
- 不开放 shell。
- 不引入外部依赖。
- 不做多项目工作区或跨仓库扫描。
- 不把 `runs/` 和 `reports/` 的历史日志作为默认上下文输入。
- 不修改 HTML Gate 的验收规则。

## 4. 推荐设计

新增模块：

```text
src/specgate/context_selector.py
```

核心数据结构：

```python
@dataclass(frozen=True)
class ContextFile:
    path: str
    status: str
    reason: str
    chars: int
    priority: int
    content: str = ""


@dataclass(frozen=True)
class ContextSelection:
    files: list[ContextFile]
    budget_chars: int
    used_chars: int
```

核心函数：

```python
def select_context_files(root: Path, budget_chars: int = 12000) -> ContextSelection:
    ...
```

选择规则：

- `TASK_SPEC.md` 优先级最高。
- `CHECKLIST.md` 次之。
- `README.md` 用于补充项目背景。
- `index.html` 用于让 LLM 看到当前产物。
- 其他 `.md`、`.html`、`.css`、`.js`、`.txt` 可以低优先级进入预算。
- `runs/`、`reports/`、`.git/`、`__pycache__/`、隐藏目录默认跳过。
- 不读取明显二进制或不在文本后缀白名单内的文件。
- 如果单个文件超过剩余预算，可以截断并标记为 `truncated`；如果已经没有预算，则标记为 `skipped`。

`context.py` 保持对外接口兼容：

```python
def build_context_pack(root: Path, latest_gate: GateResult | None) -> str:
    ...
```

内部改为调用 `select_context_files()`，输出结构包括：

- Agent 固定指令。
- `## Context Manifest`：列出 selected / skipped / truncated 文件和原因。
- `## Selected Files`：放入被选中文件内容。
- `## index.html 摘要`：保留当前摘要能力。
- `## 最近 Gate 结果`：保留 Gate 反馈闭环。

## 5. 数据流

```text
AgentRunner
  -> build_context_pack(root, latest_gate)
    -> select_context_files(root, budget_chars)
      -> scan files
      -> apply exclude rules
      -> sort by priority
      -> apply budget
      -> return ContextSelection
    -> render manifest and selected content
  -> llm.complete(context)
```

## 6. 错误处理

- 文件读取失败时，不让整个 run 崩溃；该文件进入 manifest，状态为 `skipped`，原因记录为读取失败。
- 非 UTF-8 文本文件按不可读处理，跳过并记录原因。
- 预算必须为正整数；如果调用方传入非法预算，使用默认值或抛出清晰错误。实现时优先选择显式抛出 `ValueError`，方便测试。

## 7. 测试计划

新增测试文件：

```text
tests/test_context_selector.py
```

覆盖：

- 选择器优先包含 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`。
- 自动跳过 `runs/latest/trace.jsonl`、`reports/latest/index.html`、`__pycache__`。
- 预算不足时低优先级文件被跳过或截断。
- 非文本后缀文件被跳过。
- 非法预算抛出 `ValueError`。

更新现有测试：

- `tests/test_context.py` 增加断言：context pack 包含 `Context Manifest`。
- 保留原有断言：任务文档、Checklist、Gate summary、`index.html 摘要` 仍然存在。

## 8. 对现有行为的影响

预期兼容：

- CLI 命令不变。
- `AgentRunner` 调用方式不变。
- `MockLLM` 不需要修改。
- Guardrail、ToolDispatcher、Gate、Report 不需要修改。

预期改进：

- Context Pack 从固定拼接变成可解释的文件选择结果。
- 报告和 trace 之外的运行产物不会被默认喂回 LLM，避免污染上下文。
- 后续可以自然扩展到用户修改检测和正式 Tool Registry。

## 9. 验收标准

- 新增和更新的单元测试全部通过。
- 全量测试 `python -m unittest discover -s tests -v` 通过。
- mock demo 仍能生成通过 Gate 的 `index.html` 和静态报告。
- `build_context_pack()` 输出中能看到 Context Manifest。
- 设计不引入 shell、真实 LLM、外部依赖或复杂前端。
