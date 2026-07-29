# SpecGate v0.2.0 Agent Runtime 分层迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SpecGate 的集中式 Runner 迁移为独立 AgentLoop、统一 ActionPipeline、渐进式 Skill、AgentService 与结构化 Workflow，同时保持现有 Gate、HITL、WorkspacePolicy、Windows 文件安全、CLI 和 WebUI 行为。

**Architecture:** 先建立类型化状态、停止信号和事件协议，再把现有工具逐个迁移到 Pydantic ToolDefinition/Handler，并在其外组合 Hook、Governance 与 Gate。随后用兼容适配器将单 Agent 路径切换到通用 AgentLoop，加入 Skill 和 AgentService，最后把旧多角色 coordinator 改造成只消费结构化 Artifact 的 Workflow。

**Tech Stack:** Python 3.11+、`unittest`、Pydantic 2、PyYAML 6、FastAPI、现有 `workspace_fs` / `WorkspacePolicy` / `FileSnapshot` / `ApprovalStore` / HTML Gate。

**Design:** `docs/superpowers/specs/2026-07-29-v020-agent-runtime-architecture-design.md`

---

## 实施约束

- 所有任务严格执行 red -> green -> focused regression -> commit。
- 不在同一个提交中同时引入新协议和删除旧兼容入口。
- `AgentRunner` 在 Task 17 之前保留，作为 CLI、eval 和 WebUI 的兼容外壳。
- 所有工作区读写继续调用 `workspace_fs`；新代码禁止直接写受保护路径。
- 所有动态 Trace、状态 observation 和错误文本在持久化前调用现有 `redact()`。
- 核心测试不得访问真实网络或真实模型。
- 每个任务开始前运行 `git status --short --branch`，确认没有混入其他任务改动。

## 文件职责图

### 新增运行时模块

- `src/specgate/run_state.py`：`RunStatus`、`RunState`、`StateDelta`、CAS Store。
- `src/specgate/run_control.py`：取消、超时和 `StopPolicy`。
- `src/specgate/runtime_events.py`：统一 `RunEventSink` 与 Trace adapter。
- `src/specgate/hooks.py`：Hook 事件、注册、控制结果和失败策略。
- `src/specgate/governance.py`：强制治理决策，不执行工具。
- `src/specgate/tool_handlers.py`：五个现有工具的领域 Handler。
- `src/specgate/tool_runtime.py`：工具解析、Pydantic 校验和 Handler 调用。
- `src/specgate/action_pipeline.py`：Hook、Governance、ToolRuntime、Gate 的唯一组合点。
- `src/specgate/agent_loop.py`：角色无关、工具无关的通用循环。
- `src/specgate/skill_registry.py`：Skill Catalog、指令、资源和 Session。
- `src/specgate/skill_tools.py`：`load_skill`、`read_skill_resource` Handler。
- `src/specgate/agent_service.py`：运行、恢复、取消、预算和委派边界。
- `src/specgate/artifacts.py`：版本化 AgentArtifact 模型。
- `src/specgate/workflows.py`：`SequentialReviewWorkflow`。

### 主要修改文件

- `src/specgate/actions.py`：仅校验 Action 外层协议，工具参数交给 Pydantic。
- `src/specgate/tool_registry.py`：从描述型 `ToolSpec` 升级为可执行 `ToolDefinition`。
- `src/specgate/tools.py`：保留兼容 `ToolDispatcher`，内部委托新 ToolRuntime。
- `src/specgate/trace.py`：支持固定时钟并实现事件 Sink adapter。
- `src/specgate/context.py`：实现通用 ContextBuilder 与 Skill contributor。
- `src/specgate/runner.py`：逐步缩减为兼容 facade，移除具体循环和多角色控制流。
- `src/specgate/multi_agent.py`：删除字符串 repair 判断，只保留兼容导出后最终删除。
- `src/specgate/isolation.py`：从静态角色常量迁移为 AgentDefinition/Artifact 证据 adapter。
- `src/specgate/cli.py`、`src/specgate/eval_runner.py`、`src/specgate/web_runs.py`：最终接入 AgentService。
- `src/specgate/report.py`、`src/specgate/metrics.py`：展示新事件、Skill、Agent 和 Workflow 证据。
- `pyproject.toml`、`src/specgate/__init__.py`：依赖与最终版本号。

---

### Task 1: 声明直接依赖并锁定基线

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_imports.py`

- [ ] **Step 1: 写依赖声明失败测试**

在 `tests/test_imports.py` 增加：

```python
from pathlib import Path
import unittest


class RuntimeDependencyTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared_directly(self):
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"pydantic>=2.10,<3"', pyproject)
        self.assertIn('"PyYAML>=6,<7"', pyproject)
```

- [ ] **Step 2: 验证测试因缺少直接依赖声明而失败**

Run: `python -m unittest tests.test_imports.RuntimeDependencyTests -v`

Expected: FAIL，指出 `pydantic` 或 `PyYAML` 声明不存在。

- [ ] **Step 3: 在项目依赖中加入明确版本范围**

在 `pyproject.toml` 的 `dependencies` 中加入：

```toml
    "pydantic>=2.10,<3",
    "PyYAML>=6,<7",
```

- [ ] **Step 4: 安装并验证基线**

Run: `python -m pip install -e .`

Expected: exit 0。

Run: `python -m unittest tests.test_imports tests.test_actions tests.test_tools tests.test_runner -v`

Expected: PASS。

- [ ] **Step 5: 提交依赖基线**

```powershell
git add pyproject.toml tests/test_imports.py
git commit -m "build: 声明 Agent Runtime 直接依赖"
```

### Task 2: 建立类型化 RunState 与 CAS Store

**Files:**
- Create: `src/specgate/run_state.py`
- Create: `tests/test_run_state.py`
- Modify: `src/specgate/metrics.py`

- [ ] **Step 1: 写 StateDelta、不可变状态和过期 revision 测试**

```python
import unittest

from specgate.run_state import (
    InMemoryRunStateStore,
    Observation,
    RunState,
    RunStateConflict,
    RunStatus,
    StateDelta,
)


class RunStateTests(unittest.TestCase):
    def test_apply_appends_observation_and_increments_revision(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1"))

        updated = store.apply(
            "run-1",
            expected_revision=0,
            delta=StateDelta(
                append_observations=(Observation("tool_result", {"ok": True}),),
            ),
        )

        self.assertEqual(updated.revision, 1)
        self.assertEqual(updated.observations[0].kind, "tool_result")

    def test_stale_revision_is_rejected_without_mutation(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1"))
        store.apply("run-1", 0, StateDelta(step=1))

        with self.assertRaises(RunStateConflict):
            store.apply("run-1", 0, StateDelta(step=2))

        self.assertEqual(store.get("run-1").step, 1)
```

- [ ] **Step 2: 运行测试并确认缺少模块**

Run: `python -m unittest tests.test_run_state -v`

Expected: ERROR with `ModuleNotFoundError: specgate.run_state`。

- [ ] **Step 3: 实现类型化状态与唯一写入入口**

`src/specgate/run_state.py` 的核心定义为：

```python
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Protocol

from specgate.gate import GateResult
from specgate.metrics import RunMetrics, add_run_metrics


class RunStatus(str, Enum):
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Observation:
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunState:
    run_id: str
    revision: int = 0
    status: RunStatus = RunStatus.RUNNING
    step: int = 0
    observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    finish_requested: bool = False
    metrics: RunMetrics = field(default_factory=RunMetrics)


@dataclass(frozen=True)
class StateDelta:
    status: RunStatus | None = None
    step: int | None = None
    append_observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    clear_pending_approval: bool = False
    finish_requested: bool | None = None
    metrics: RunMetrics = field(default_factory=RunMetrics)


class RunStateConflict(RuntimeError):
    pass


class RunStateStore(Protocol):
    def create(self, state: RunState) -> RunState: ...
    def get(self, run_id: str) -> RunState: ...
    def apply(self, run_id: str, expected_revision: int, delta: StateDelta) -> RunState: ...


class InMemoryRunStateStore:
    def __init__(self) -> None:
        self._states: dict[str, RunState] = {}

    def create(self, state: RunState) -> RunState:
        if state.run_id in self._states:
            raise RunStateConflict(f"run already exists: {state.run_id}")
        self._states[state.run_id] = state
        return state

    def get(self, run_id: str) -> RunState:
        return self._states[run_id]

    def apply(self, run_id: str, expected_revision: int, delta: StateDelta) -> RunState:
        current = self.get(run_id)
        if current.revision != expected_revision:
            raise RunStateConflict(
                f"stale run state: expected {expected_revision}, actual {current.revision}"
            )
        updated = replace(
            current,
            revision=current.revision + 1,
            status=delta.status or current.status,
            step=current.step if delta.step is None else delta.step,
            observations=current.observations + delta.append_observations,
            latest_gate=delta.latest_gate or current.latest_gate,
            pending_approval_id=(
                None if delta.clear_pending_approval
                else delta.pending_approval_id or current.pending_approval_id
            ),
            finish_requested=(
                current.finish_requested
                if delta.finish_requested is None
                else delta.finish_requested
            ),
            metrics=add_run_metrics(current.metrics, delta.metrics),
        )
        self._states[run_id] = updated
        return updated
```

在 `src/specgate/metrics.py` 增加一个按字段相加、布尔字段取 OR 的 `add_run_metrics(current, delta)`；使用 `dataclasses.fields(RunMetrics)` 遍历，避免重复维护字段表。

- [ ] **Step 4: 验证状态测试与现有 metrics 测试**

Run: `python -m unittest tests.test_run_state tests.test_metrics -v`

Expected: PASS。

- [ ] **Step 5: 提交状态协议**

```powershell
git add src/specgate/run_state.py src/specgate/metrics.py tests/test_run_state.py
git commit -m "refactor: 建立类型化运行状态协议"
```

### Task 3: 建立取消、超时与 StopPolicy

**Files:**
- Create: `src/specgate/run_control.py`
- Create: `tests/test_run_control.py`
- Modify: `src/specgate/web_runtime.py`

- [ ] **Step 1: 写继续、挂起、完成、取消和超时测试**

测试必须覆盖：运行态返回 `CONTINUE`；审批态返回 `SUSPEND`；完成/失败/取消/超时返回 `TERMINATE`；`CallbackCancellationToken` 保持现有 `stop_check` 异常行为；用户取消优先于超时。

```python
def test_approval_state_suspends_without_terminating(self):
    decision = DefaultStopPolicy(max_steps=5).decide(
        RunState("run-1", status=RunStatus.NEEDS_APPROVAL)
    )
    self.assertEqual(decision.kind, LoopDecisionKind.SUSPEND)
    self.assertEqual(decision.reason, "approval_required")
```

- [ ] **Step 2: 验证测试因缺少控制协议而失败**

Run: `python -m unittest tests.test_run_control -v`

Expected: ERROR with `ModuleNotFoundError: specgate.run_control`。

- [ ] **Step 3: 实现明确的控制类型**

```python
class LoopDecisionKind(str, Enum):
    CONTINUE = "continue"
    SUSPEND = "suspend"
    TERMINATE = "terminate"


@dataclass(frozen=True)
class LoopDecision:
    kind: LoopDecisionKind
    outcome: RunStatus | None = None
    reason: str = ""


class CancellationToken(Protocol):
    def check(self) -> None: ...
    def remaining_seconds(self) -> float: ...


@dataclass(frozen=True)
class CallbackCancellationToken:
    stop_check: Callable[[], None]
    remaining: Callable[[], float] = lambda: float("inf")

    def check(self) -> None:
        self.stop_check()

    def remaining_seconds(self) -> float:
        return self.remaining()
```

`DefaultStopPolicy.decide()` 必须先处理终态，再处理 `needs_approval`，再处理 `max_steps`，最后根据 `finish_requested` 与最终 Gate 决定完成或继续。

- [ ] **Step 4: 让 Web RunControl 适配 CancellationToken**

给 `RunControl` 保留现有 `check()` / `remaining_seconds()` 方法，并增加契约测试确认它可直接传给 AgentService，不复制取消逻辑。

Run: `python -m unittest tests.test_run_control tests.test_web_runtime -v`

Expected: PASS。

- [ ] **Step 5: 提交运行控制协议**

```powershell
git add src/specgate/run_control.py src/specgate/web_runtime.py tests/test_run_control.py tests/test_web_runtime.py
git commit -m "refactor: 统一运行停止与挂起语义"
```

### Task 4: 建立强制 RunEventSink

**Files:**
- Create: `src/specgate/runtime_events.py`
- Create: `tests/test_runtime_events.py`
- Modify: `src/specgate/trace.py`
- Modify: `tests/test_context.py`

- [ ] **Step 1: 写固定时间、层级 ID 与脱敏测试**

```python
def test_trace_sink_adds_run_identity_and_redacts_payload(self):
    sink = InMemoryRunEventSink(clock=lambda: "2026-07-29T00:00:00Z")
    sink.emit(
        RunEventContext("run-1", "agent-1", "parent-1"),
        "ToolCompleted",
        {"token": "sk-secret-1234567890"},
        step=2,
        phase="tool",
    )
    event = sink.events[0]
    self.assertEqual(event.timestamp, "2026-07-29T00:00:00Z")
    self.assertEqual(event.agent_run_id, "agent-1")
    self.assertNotIn("sk-secret", str(event.payload))
```

- [ ] **Step 2: 运行测试并确认缺少事件模块**

Run: `python -m unittest tests.test_runtime_events -v`

Expected: ERROR。

- [ ] **Step 3: 实现 RunEvent、Context、协议和两个 Sink**

`runtime_events.py` 定义不可变 `RunEvent`、`RunEventContext`、`RunEventSink` Protocol、`InMemoryRunEventSink` 和 `TraceRunEventSink`。`TraceRunEventSink` 只负责把统一事件映射到现有 `TraceStore.append()`；所有 payload 先调用 `redact()`。

同时把 `TraceStore` 的当前时间改为构造器注入：

```python
class TraceStore:
    def __init__(self, path: Path, reset: bool = False, clock=_utc_now):
        self.clock = clock

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": self.clock(),
            "event_type": event_type,
            "payload": redact(payload),
        }
        self._append_event(event)
```

- [ ] **Step 4: 验证事件与旧 Trace 兼容**

Run: `python -m unittest tests.test_runtime_events tests.test_context tests.test_web_approvals -v`

Expected: PASS。

- [ ] **Step 5: 提交事件基础设施**

```powershell
git add src/specgate/runtime_events.py src/specgate/trace.py tests/test_runtime_events.py tests/test_context.py
git commit -m "refactor: 建立统一运行事件流"
```

### Task 5: 将 Tool Registry 升级为可执行定义

**Files:**
- Modify: `src/specgate/tool_registry.py`
- Modify: `src/specgate/actions.py`
- Create: `src/specgate/tool_handlers.py`
- Modify: `tests/test_tool_registry.py`
- Modify: `tests/test_actions.py`

- [ ] **Step 1: 写重复注册、Pydantic 参数和 Handler 独立测试**

```python
def test_duplicate_tool_name_fails_closed(self):
    registry = ToolRegistry()
    registry.register(make_read_file_definition())
    with self.assertRaises(DuplicateToolError):
        registry.register(make_read_file_definition())

def test_action_parser_leaves_tool_specific_validation_to_runtime(self):
    action = parse_action(
        '{"schema_version":"1","action":"write_file","args":{"path":"index.html"}}'
    )
    self.assertEqual(action.action, "write_file")
```

- [ ] **Step 2: 运行聚焦测试并确认旧实现失败**

Run: `python -m unittest tests.test_tool_registry tests.test_actions -v`

Expected: FAIL，因为没有可执行 Registry，且 parser 仍校验写入 content。

- [ ] **Step 3: 定义工具模型和注册协议**

使用 Pydantic `BaseModel` 定义 `ReadFileArgs`、`WriteFileArgs`、`ListFilesArgs`、`FinishArgs` 及对应 Result。ToolDefinition 的元数据、权限和副作用类别使用明确类型：

```python
class PermissionClass(str, Enum):
    READ = "read"
    WRITE = "write"
    INSPECT = "inspect"
    CONTROL = "control"


class SideEffectClass(str, Enum):
    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    RUN_CONTROL = "run_control"


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str


@dataclass(frozen=True)
class ToolDefinition:
    metadata: ToolMetadata
    permission_class: PermissionClass
    side_effect_class: SideEffectClass
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.metadata.name


class ToolRegistry:
    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise DuplicateToolError(definition.name)
        self._definitions[definition.name] = definition

    def resolve(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def values(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())
```

`parse_action()` 继续严格校验 JSON 外层协议，但删除 `_validate_action_args()`；每个工具的字段与类型由其 `args_model` 唯一负责。`default_tool_registry()` 返回 ToolRegistry；它保留 `values()` 和按名称 resolve 的兼容读取能力，供 context/report 使用。

- [ ] **Step 4: 实现五个 Handler，保持安全文件 API**

Handler 接收 `ToolExecutionContext(policy, snapshot)`，读写实现从旧 `ToolDispatcher` 原样迁移，并继续调用 `workspace_fs`。`WriteFileHandler` 成功后更新 FileSnapshot；任何 `WorkspacePathError` 转换为带原 `rule_family` 的领域错误。

迁移映射固定为：

```python
def default_tool_definitions() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(ToolMetadata("read_file", "Read allowed UTF-8 workspace text."), PermissionClass.READ, SideEffectClass.NONE, ReadFileArgs, ReadFileResult, ReadFileHandler()),
        ToolDefinition(ToolMetadata("write_file", "Write allowed UTF-8 workspace text."), PermissionClass.WRITE, SideEffectClass.WORKSPACE_WRITE, WriteFileArgs, WriteFileResult, WriteFileHandler()),
        ToolDefinition(ToolMetadata("replace_file", "Replace allowed UTF-8 workspace text."), PermissionClass.WRITE, SideEffectClass.WORKSPACE_WRITE, WriteFileArgs, WriteFileResult, WriteFileHandler()),
        ToolDefinition(ToolMetadata("list_files", "List policy-readable workspace files."), PermissionClass.INSPECT, SideEffectClass.NONE, ListFilesArgs, ListFilesResult, ListFilesHandler()),
        ToolDefinition(ToolMetadata("finish", "Request final Gate and completion."), PermissionClass.CONTROL, SideEffectClass.RUN_CONTROL, FinishArgs, FinishResult, FinishHandler()),
    )
```

`ReadFileHandler.execute()`、`WriteFileHandler.execute()` 与 `ListFilesHandler.execute()` 分别移动 `ToolDispatcher._read_file()`、`_write_file()`、`_list_files()` 的现有安全 I/O 主体，不改变异常分类或 snapshot 更新时机。FinishHandler 只返回 summary，不自行结束 Loop。

Run: `python -m unittest tests.test_tool_registry tests.test_actions -v`

Expected: PASS。

- [ ] **Step 5: 提交 ToolDefinition 与 Handler**

```powershell
git add src/specgate/tool_registry.py src/specgate/actions.py src/specgate/tool_handlers.py tests/test_tool_registry.py tests/test_actions.py
git commit -m "refactor: 建立可执行工具定义"
```

### Task 6: 实现通用 ToolRuntime 与兼容 Dispatcher

**Files:**
- Create: `src/specgate/tool_runtime.py`
- Modify: `src/specgate/tools.py`
- Create: `tests/test_tool_runtime.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: 写 prepare 参数失败、Handler 成功和异常映射测试**

```python
def test_runtime_validates_args_before_handler(self):
    handler = Mock()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            metadata=ToolMetadata("write_file", "write a file"),
            permission_class=PermissionClass.WRITE,
            side_effect_class=SideEffectClass.WORKSPACE_WRITE,
            args_model=WriteFileArgs,
            result_model=WriteFileResult,
            handler=handler,
        )
    )
    runtime = ToolRuntime(registry)
    result = runtime.prepare(Action("1", "write_file", {"path": "index.html"}))
    self.assertEqual(result.failure.code, "tool_validation_failed")
    handler.execute.assert_not_called()
```

- [ ] **Step 2: 运行测试并确认缺少 ToolRuntime**

Run: `python -m unittest tests.test_tool_runtime -v`

Expected: ERROR。

- [ ] **Step 3: 实现无工具名分支的运行时**

ToolRuntime 拆为准备与执行两步，让 Hook/Governance 可以安全插入参数验证和 Handler 之间。返回兼容 `ToolResult`，并新增稳定 `code` 字段：`ok`、`unknown_tool`、`tool_validation_failed`、`tool_execution_failed` 及具体 workspace rule family。给 `ToolResult` 增加 `success()` / `failure()` classmethod，二者必须显式填写 `code`，不得从 message 推断。

```python
@dataclass(frozen=True)
class PreparedToolCall:
    definition: ToolDefinition
    args: BaseModel


@dataclass(frozen=True)
class ToolPreparation:
    call: PreparedToolCall | None = None
    failure: ToolResult | None = None


def prepare(self, action: Action) -> ToolPreparation:
    try:
        definition = self.registry.resolve(action.action)
        args = definition.args_model.model_validate(action.args)
    except UnknownToolError:
        return ToolPreparation(
            failure=ToolResult.failure(action.action, "unknown_tool", blocked=True)
        )
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors())
        return ToolPreparation(
            failure=ToolResult.failure(
                action.action,
                "tool_validation_failed",
                message=f"invalid tool arguments: {fields}",
                blocked=True,
            )
        )
    return ToolPreparation(call=PreparedToolCall(definition, args))


def execute_prepared(
    self,
    call: PreparedToolCall,
    context: ToolExecutionContext,
) -> ToolResult:
    try:
        raw_result = call.definition.handler.execute(call.args, context)
        result = call.definition.result_model.model_validate(raw_result)
    except ToolExecutionError as exc:
        return ToolResult.failure(
            call.definition.name,
            exc.code,
            message=exc.safe_message,
            blocked=exc.blocked,
        )
    return ToolResult.success(
        call.definition.name,
        result.model_dump(mode="json"),
    )
```

Pydantic ValidationError 的 message 只渲染字段位置与稳定错误码，禁止直接使用可能包含用户 content 的 `str(exc)`。新增 `tool_validation_failures` metric；顶层 JSON 协议错误仍计入 `parse_errors`，工具参数错误只计入新指标。

- [ ] **Step 4: 把旧 ToolDispatcher 改为兼容 facade**

`ToolDispatcher.dispatch()` 先执行现有 `check_action()`，再调用 `prepare()` 和 `execute_prepared()`。构造器同时接受 ToolRegistry 或旧式 mapping，并通过明确 adapter 转换；传入空 mapping 仍表示没有可用工具。这样 Task 9 引入 GovernanceEngine 前，旧 Runner 的安全行为不变。所有 `tests/test_tools.py` 原断言必须继续通过。

Run: `python -m unittest tests.test_tool_runtime tests.test_tools tests.test_runner -v`

Expected: PASS。

- [ ] **Step 5: 提交通用 ToolRuntime**

```powershell
git add src/specgate/tool_runtime.py src/specgate/tools.py tests/test_tool_runtime.py tests/test_tools.py
git commit -m "refactor: 统一工具运行时"
```

### Task 7: 实现 HookBus MVP

**Files:**
- Create: `src/specgate/hooks.py`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: 写五类事件和控制权限测试**

测试覆盖：事件注册顺序稳定；只有 BeforeTool 返回控制结果；普通 observer 异常被记录后继续；enforcing BeforeTool 异常返回 Block；Hook 不能返回 AllowOverride。

```python
def test_enforcing_before_tool_failure_blocks(self):
    bus = HookBus(event_sink=self.sink)
    bus.register_before_tool(lambda event: 1 / 0, enforcing=True)
    result = bus.before_tool(self.event)
    self.assertEqual(result.kind, BeforeToolDecisionKind.BLOCK)
    self.assertEqual(result.code, "hook_failed_closed")
```

- [ ] **Step 2: 运行测试并确认缺少 HookBus**

Run: `python -m unittest tests.test_hooks -v`

Expected: ERROR。

- [ ] **Step 3: 实现最小 Hook 模型**

定义 `RunStarted`、`BeforeTool`、`AfterTool`、`AfterGate`、`RunFinished` 事件 dataclass。`BeforeToolDecisionKind` 只有 `CONTINUE`、`BLOCK`、`REQUIRE_APPROVAL`。HookBus 为每种事件维护独立有序列表；observer 收到冻结事件对象，不接收可变 RunState。

```python
class HookBus:
    def register_before_tool(
        self,
        hook: Callable[[BeforeTool], BeforeToolDecision],
        *,
        enforcing: bool = False,
    ) -> None:
        self._before_tool.append((hook, enforcing))

    def before_tool(self, event: BeforeTool) -> BeforeToolDecision:
        for hook, enforcing in self._before_tool:
            try:
                decision = hook(event)
            except Exception as exc:
                self._record_hook_error("BeforeTool", exc)
                if enforcing:
                    return BeforeToolDecision.block("hook_failed_closed")
                continue
            if decision.kind is not BeforeToolDecisionKind.CONTINUE:
                return decision
        return BeforeToolDecision.continue_()
```

- [ ] **Step 4: 验证失败策略与事件脱敏**

Run: `python -m unittest tests.test_hooks tests.test_runtime_events -v`

Expected: PASS，且测试确认异常文本写入 Sink 前经过 `redact()`。

- [ ] **Step 5: 提交 HookBus**

```powershell
git add src/specgate/hooks.py tests/test_hooks.py
git commit -m "feat: 增加 Agent 生命周期 HookBus"
```

### Task 8: 抽取强制 GovernanceEngine

**Files:**
- Create: `src/specgate/governance.py`
- Create: `tests/test_governance.py`
- Modify: `src/specgate/approvals.py`

- [ ] **Step 1: 写能力交集、策略拒绝和审批决策测试**

```python
def test_capability_cannot_expand_workspace_policy(self):
    decision = self.engine.evaluate(
        Action("1", "write_file", {"path": "index.html", "content": "x"}),
        capabilities=frozenset({"write_file"}),
        policy=WorkspacePolicy(self.root, {"read_file"}, {"index.html"}, set()),
    )
    self.assertEqual(decision.kind, GovernanceDecisionKind.BLOCK)
    self.assertEqual(decision.code, "action")
```

同时覆盖 review profile 返回 `REQUIRE_APPROVAL`，strict profile 对同一风险返回 `BLOCK`，安全动作返回 `ALLOW`。

- [ ] **Step 2: 运行测试并确认缺少 GovernanceEngine**

Run: `python -m unittest tests.test_governance -v`

Expected: ERROR。

- [ ] **Step 3: 实现单一治理决策接口**

`GovernanceEngine.evaluate(call, capabilities, policy, config)` 接收已经 Pydantic 校验的 PreparedToolCall，先检查 capability，再把规范化参数适配为现有 Action 调用 `check_action()`，最后复用 `classify_action_risk()`。返回不可变 `GovernanceDecision(kind, code, reason, rule_family, risk)`；它不执行工具、不写 ApprovalQueue。

```python
class GovernanceDecisionKind(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class GovernanceDecision:
    kind: GovernanceDecisionKind
    code: str
    reason: str
    rule_family: str
    risk: ActionRisk | None = None
```

- [ ] **Step 4: 抽取 ApprovalRequester 协议**

在 `approvals.py` 增加 `ApprovalRequester` Protocol 与复用现有 `ApprovalStore` 的 `WorkspaceApprovalRequester`。`request()` 负责唯一 ID、参数预览、目标快照和 revision/CAS；输入为已通过基础 Governance 校验的 Action。

```python
class ApprovalRequester(Protocol):
    def request(self, action: Action, *, step: int, reason: str) -> PendingApproval:
        raise NotImplementedError
```

Run: `python -m unittest tests.test_governance tests.test_approvals -v`

Expected: PASS。

- [ ] **Step 5: 提交治理层**

```powershell
git add src/specgate/governance.py src/specgate/approvals.py tests/test_governance.py tests/test_approvals.py
git commit -m "refactor: 抽取强制治理引擎"
```

### Task 9: 组合 ActionPipeline、GateRunner 与 ValidationPolicy

**Files:**
- Create: `src/specgate/action_pipeline.py`
- Create: `src/specgate/validation.py`
- Create: `tests/test_action_pipeline.py`
- Modify: `src/specgate/gate.py`

- [ ] **Step 1: 用记录型 fake 写严格调用顺序测试**

```python
def test_pipeline_order_for_write(self):
    outcome = self.pipeline.execute(self.write_action, self.context)
    self.assertEqual(
        self.calls,
        ["before_tool", "governance", "handler", "after_tool", "gate", "after_gate"],
    )
    self.assertEqual(outcome.status, ExecutionStatus.SUCCEEDED)
```

再覆盖 BeforeTool block/approval 时 Governance 与 Handler 均不调用；Governance block/approval 时 Handler 不调用；纯 read 不跑 Gate；finish 与成功写入必须跑 Gate；Gate fail 返回 feedback 而非 suspend。

- [ ] **Step 2: 运行测试并确认缺少 Pipeline**

Run: `python -m unittest tests.test_action_pipeline -v`

Expected: ERROR。

- [ ] **Step 3: 实现稳定 Outcome 与验证适配器**

```python
class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class RuntimeErrorInfo:
    code: str
    message: str


@dataclass(frozen=True)
class ExecutionOutcome:
    status: ExecutionStatus
    state_delta: StateDelta
    tool_result: ToolResult | None = None
    gate_result: GateResult | None = None
    approval_request: PendingApproval | None = None
    feedback: Observation | None = None
    error: RuntimeErrorInfo | None = None
```

`DefaultValidationPolicy.should_validate(call, result)` 根据 ToolDefinition.side_effect_class 判断：`WORKSPACE_WRITE` 与 `RUN_CONTROL` 返回 True，`NONE` 返回 False。这样新增工具只声明副作用类别，不修改 Pipeline。`HtmlGateRunner.run(GateContext)` 封装现有 `run_html_gate()`，GateContext 只包含 root、policy 与 checklist/artifact 逻辑路径，不修改 Gate 规则。

- [ ] **Step 4: 实现唯一 Pipeline 编排顺序**

ActionPipeline 严格执行 `prepare -> BeforeTool -> Governance -> execute_prepared -> AfterTool -> ValidationPolicy -> GateRunner -> AfterGate`。只有已声明 Tool/Hook/Governance/Gate 错误转换 Outcome；`RunStateConflict`、AssertionError 和未知程序错误不得伪装成工具失败。所有 observation 在写入 StateDelta 前脱敏。RUN_CONTROL 的 finish 只有最终 Gate 通过时才把 `finish_requested=True` 写入 StateDelta；Gate 失败只追加修复 feedback。

Run: `python -m unittest tests.test_action_pipeline tests.test_gate tests.test_governance tests.test_hooks tests.test_tool_runtime -v`

Expected: PASS。

- [ ] **Step 5: 提交 ActionPipeline**

```powershell
git add src/specgate/action_pipeline.py src/specgate/validation.py src/specgate/gate.py tests/test_action_pipeline.py
git commit -m "refactor: 组合统一动作执行管线"
```

### Task 10: 实现角色无关 AgentLoop

**Files:**
- Create: `src/specgate/agent_loop.py`
- Create: `tests/test_agent_loop.py`

- [ ] **Step 1: 写脚本化 Loop 场景测试**

用 fake ContextBuilder、MockLLM、ActionExecutor、StateStore、StopPolicy 和 EventSink 覆盖：成功 finish、parse error 反馈、Gate repair、审批挂起、max steps、取消、超时、Pipeline 程序错误持久化为 failed 后重新抛出。

再增加 `LLMProviderError` 场景：认证、限流、不可用和请求超时都写稳定错误码并结束为 `failed` 或 `timed_out`；Trace 不记录 API key 或 transport 原始响应。

```python
def test_approval_outcome_suspends_and_preserves_state(self):
    result = self.make_loop(
        outcomes=[approval_required_outcome("approval-1")]
    ).run("run-1")
    self.assertEqual(result.status, RunStatus.NEEDS_APPROVAL)
    self.assertEqual(result.pending_approval_id, "approval-1")
```

- [ ] **Step 2: 运行测试并确认缺少 AgentLoop**

Run: `python -m unittest tests.test_agent_loop -v`

Expected: ERROR。

- [ ] **Step 3: 实现 ContextBuilder 与 ToolExecutor 协议**

`agent_loop.py` 定义 `ContextBuild(text, metadata)`、`ContextBuilder.build(state)` 和 `ActionExecutor.execute(action, state)` Protocol。Loop 构造器只接收这些协议、`LLMClient`、Action parser、RunStateStore、StopPolicy、CancellationToken 和 RunEventSink。

- [ ] **Step 4: 实现最小通用循环并加源码不变量测试**

循环严格执行 `check -> decide -> context -> LLM -> check -> parse -> execute -> apply`。源码契约测试使用 `inspect.getsource(specgate.agent_loop)`，断言不含 `write_file`、`planner`、`reviewer`、`SkillRegistry` 和 `multi-agent-isolated`。

```python
def run(self, run_id: str) -> RunState:
    while True:
        self.cancel_token.check()
        state = self.state_store.get(run_id)
        decision = self.stop_policy.decide(state)
        if decision.kind is not LoopDecisionKind.CONTINUE:
            if decision.outcome is not None and decision.outcome is not state.status:
                state = self.state_store.apply(
                    run_id,
                    state.revision,
                    StateDelta(status=decision.outcome),
                )
            return state

        built = self.context_builder.build(state)
        self.event_sink.emit(self.event_context, "ContextBuilt", built.metadata, step=state.step)
        raw = self.llm.complete(built.text)
        self.cancel_token.check()

        try:
            action = self.parse_action(raw)
        except ActionParseError as exc:
            delta = parse_error_delta(state, exc)
        else:
            outcome = self.action_executor.execute(action, state)
            delta = outcome.state_delta

        self.state_store.apply(run_id, state.revision, delta)
```

`parse_error_delta()` 只记录脱敏后的稳定 `action_parse_failed` observation 和 parse_errors 增量。LLMProviderError、取消/超时及未知异常分别由独立 `except` 分支处理；未知异常先尽力 CAS 写入 failed 状态并发出 `RunFailed`，随后重新抛出原异常。

Run: `python -m unittest tests.test_agent_loop -v`

Expected: PASS。

- [ ] **Step 5: 提交通用 Loop**

```powershell
git add src/specgate/agent_loop.py tests/test_agent_loop.py
git commit -m "feat: 增加角色无关 AgentLoop"
```

### Task 11: 将单 Agent Runner 接入新 Loop

**Files:**
- Modify: `src/specgate/context.py`
- Modify: `src/specgate/runner.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_context.py`

- [ ] **Step 1: 写兼容 RunResult 和事件序列回归测试**

新增测试确认 baseline MockLLM 仍生成相同 `RunResult.outcome`、metrics、permission decisions、Gate feedback 和 trace 文件；同时断言新事件序列含 `RunStarted`、`ToolCompleted`、`GateCompleted`、`RunFinished`。

- [ ] **Step 2: 运行测试并确认仍走 `_run_loop`**

Run: `python -m unittest tests.test_runner.RunnerTests.test_successful_write_finish_records_metrics_and_trust -v`

Expected: FAIL 新事件断言。

- [ ] **Step 3: 增加 LegacyContextBuilder 与结果 adapter**

`LegacyContextBuilder` 封装 `build_context_pack_with_metadata()`；它从 RunState observations 构造原 `runtime_feedback`，并保持 context budget、retrieval 与 compression 配置。Runner adapter 将新 RunState 转为现有 `RunResult`，保证 CLI/Web 调用方暂时不变。

- [ ] **Step 4: 只切换非 multi-agent 的 run 路径**

`AgentRunner.run()` 对普通策略创建 RunState、ActionPipeline、AgentLoop 并执行；`multi-agent-isolated` 和 `resume_from_approval()` 暂时继续旧路径。旧 `_run_loop` 保留为 `_legacy_run_loop`，只供尚未迁移的 resume 调用。

Run: `python -m unittest tests.test_runner tests.test_context tests.test_cli tests.test_eval_runner -v`

Expected: PASS。

- [ ] **Step 5: 提交单 Agent 迁移**

```powershell
git add src/specgate/context.py src/specgate/runner.py tests/test_runner.py tests/test_context.py
git commit -m "refactor: 用通用 Loop 执行单 Agent 运行"
```

### Task 12: 实现安全 SkillRegistry 与 SkillSession

**Files:**
- Create: `src/specgate/skill_registry.py`
- Create: `tests/test_skill_registry.py`

- [ ] **Step 1: 写 Catalog、加载和 fail-closed 测试**

使用 `TemporaryDirectory` 构造 Skill，覆盖：只读显式 root；Catalog 只暴露 name/description/source；UTF-8 指令成功；重复名称、非法 YAML、缺字段、非 UTF-8、资源越界和 symlink/reparse path 全部失败；不同 AgentRun Session 不共享已加载集合。

```python
def test_sessions_are_isolated_per_agent_run(self):
    first = SkillSession(agent_run_id="agent-1")
    second = SkillSession(agent_run_id="agent-2")
    first.activate("demo")
    self.assertEqual(first.active_names, ("demo",))
    self.assertEqual(second.active_names, ())
```

- [ ] **Step 2: 运行测试并确认缺少 SkillRegistry**

Run: `python -m unittest tests.test_skill_registry -v`

Expected: ERROR。

- [ ] **Step 3: 实现 frontmatter 与显式 root 扫描**

定义 `SkillCatalogEntry`、`SkillInstructions`、`SkillResource`、`SkillSession`。只读取 `<root>/<skill>/SKILL.md`；用 `yaml.safe_load()` 解析 `---` 包围的 frontmatter，要求 `name`、`description` 是非空字符串。读取前调用 `workspace_fs` 的安全状态/读取函数，不使用裸 `Path.read_text()`。

```python
def parse_skill_document(text: str, source: SkillSource) -> SkillInstructions:
    if not text.startswith("---\n"):
        raise InvalidSkillError("missing_frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise InvalidSkillError("unterminated_frontmatter")
    metadata = yaml.safe_load(text[4:marker])
    if not isinstance(metadata, dict):
        raise InvalidSkillError("frontmatter_must_be_mapping")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise InvalidSkillError("invalid_skill_name")
    if not isinstance(description, str) or not description.strip():
        raise InvalidSkillError("invalid_skill_description")
    return SkillInstructions(
        name=name.strip(),
        description=description.strip(),
        body=text[marker + 5 :],
        source=source,
    )
```

- [ ] **Step 4: 实现资源边界和来源冲突规则**

资源路径先经 `normalize_workspace_relative()`，再限定在当前 Skill 根目录。内置和工作区来源同名时抛 `DuplicateSkillError`，错误中只包含安全名称，不包含资源内容。

Run: `python -m unittest tests.test_skill_registry tests.test_workspace_fs -v`

Expected: PASS。

- [ ] **Step 5: 提交 Skill Registry**

```powershell
git add src/specgate/skill_registry.py tests/test_skill_registry.py
git commit -m "feat: 增加安全 Skill Registry"
```

### Task 13: 注册 Skill 工具并贡献上下文

**Files:**
- Create: `src/specgate/skill_tools.py`
- Modify: `src/specgate/tool_registry.py`
- Modify: `src/specgate/context.py`
- Create: `tests/test_skill_tools.py`
- Modify: `tests/test_context.py`

- [ ] **Step 1: 写渐进披露和权限不扩张测试**

测试初始上下文只含 Catalog；执行 `load_skill` 后后续上下文含 Instructions；只有调用 `read_skill_resource` 才返回资源正文；两个工具不能修改 CapabilitySet 或 WorkspacePolicy；未加载 Skill 的资源不可读。

- [ ] **Step 2: 运行测试并确认工具未注册**

Run: `python -m unittest tests.test_skill_tools tests.test_context -v`

Expected: FAIL。

- [ ] **Step 3: 实现两个 ToolHandler**

`LoadSkillArgs(name)` / `LoadSkillResult(name, instructions)` 与 `ReadSkillResourceArgs(name, path)` / `ReadSkillResourceResult(name, path, content)` 使用 Pydantic。Handler 只调用注入的 SkillRegistry/SkillSession，不直接访问任意文件路径。

```python
class LoadSkillArgs(BaseModel):
    name: str


class ReadSkillResourceArgs(BaseModel):
    name: str
    path: str


class LoadSkillHandler:
    def execute(self, args: LoadSkillArgs, context: ToolExecutionContext) -> dict[str, str]:
        instructions = context.skill_registry.load(args.name)
        context.skill_session.activate(args.name)
        return {"name": args.name, "instructions": instructions.body}
```

这两个 Definition 只在 composition root 收到非空显式 Skill roots 时注册，并同步加入该 AgentDefinition 的 CapabilitySet 与 WorkspacePolicy.allowed_actions；它们仍需经过 BeforeTool 和 Governance，注册本身不能授权其他工具。

- [ ] **Step 4: 增加 SkillContextContributor**

ContextBuilder 接受 `context_contributors: tuple[ContextContributor, ...]`。契约固定为 `ContextContributor.render(state: RunState) -> tuple[str, str]`，返回 section name 与已脱敏正文。`SkillContextContributor` 渲染 Catalog 和 Session 中已激活指令；旧 `build_context_pack_with_metadata()` 通过默认空 contributor 保持输出兼容。

```python
class ContextContributor(Protocol):
    def render(self, state: RunState) -> tuple[str, str]:
        raise NotImplementedError


@dataclass(frozen=True)
class SkillContextContributor:
    registry: SkillRegistry
    session: SkillSession

    def render(self, state: RunState) -> tuple[str, str]:
        return "Skills", render_skill_context(self.registry, self.session)
```

Run: `python -m unittest tests.test_skill_tools tests.test_skill_registry tests.test_context tests.test_tool_registry -v`

Expected: PASS。

- [ ] **Step 5: 提交 Skill Runtime 接入**

```powershell
git add src/specgate/skill_tools.py src/specgate/tool_registry.py src/specgate/context.py tests/test_skill_tools.py tests/test_context.py
git commit -m "feat: 接入渐进式 Skill 工具"
```

### Task 14: 实现 AgentDefinition、AgentService 与持久化状态

**Files:**
- Create: `src/specgate/agent_service.py`
- Modify: `src/specgate/run_state.py`
- Create: `tests/test_agent_service.py`
- Modify: `tests/test_approvals.py`

- [ ] **Step 1: 写运行隔离、能力交集、预算和状态持久化测试**

```python
def test_child_capabilities_are_three_way_intersection(self):
    effective = effective_child_capabilities(
        child=frozenset({"read_file", "write_file"}),
        parent=frozenset({"read_file"}),
        workspace=frozenset({"read_file", "list_files"}),
    )
    self.assertEqual(effective, frozenset({"read_file"}))
```

同时测试每个 AgentRun 获得不同 `agent_run_id` 和 SkillSession；无 DelegationPolicy 时拒绝子 Agent；子预算不能超过 Workflow 预留；状态文件 revision 冲突 fail closed。

- [ ] **Step 2: 运行测试并确认缺少 AgentService**

Run: `python -m unittest tests.test_agent_service -v`

Expected: ERROR。

- [ ] **Step 3: 实现 AgentDefinition 与运行工厂**

定义 `CapabilitySet = frozenset[str]`、`AgentBudget(max_steps, context_chars, child_runs)`、`DelegationPolicy(max_depth, max_children)`、`AgentDefinition`、`AgentRunRequest`、`AgentRunResult`。服务签名固定为：

```python
class AgentService:
    def run(
        self,
        definition: AgentDefinition,
        task: str,
        parent_run_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> AgentRunResult:
        return self._run_new_agent(definition, task, parent_run_id, cancel_token)
```

`AgentService.run()` 为每次调用创建 AgentRun identity、SkillSession、StateStore、ContextBuilder 和 AgentLoop；角色差异只来自 Definition。Service 在第一次调用 Loop 前触发一次 HookBus `RunStarted`，只在 completed/failed/cancelled/timed_out 时触发一次 `RunFinished`；审批挂起不触发 `RunFinished`，恢复时写 `RunResumed` Trace 而不重复触发 `RunStarted`。

- [ ] **Step 4: 实现安全 FileRunStateStore**

状态保存为运行审计目录内的 `state.json`，使用 `workspace_fs.read_workspace_text()` / `write_workspace_text()`、显式 schema version、revision CAS 和 `redact()`。不把 API key、LLM transport 或可调用对象序列化。`apply()` 必须在 `workspace_fs.workspace_file_lock()` 内重新读取当前 revision、比较 `expected_revision` 并完成安全原子写；禁止在锁外读取后直接覆盖。GateResult 和 Observation 使用显式 encoder/decoder，未知 schema version 或字段类型 fail closed。

Run: `python -m unittest tests.test_agent_service tests.test_run_state tests.test_workspace_fs -v`

Expected: PASS。

- [ ] **Step 5: 提交 AgentService 基础**

```powershell
git add src/specgate/agent_service.py src/specgate/run_state.py tests/test_agent_service.py tests/test_approvals.py
git commit -m "feat: 增加 AgentService 运行边界"
```

### Task 15: 将审批恢复迁移到 AgentService

**Files:**
- Modify: `src/specgate/agent_service.py`
- Modify: `src/specgate/approvals.py`
- Modify: `src/specgate/runner.py`
- Modify: `tests/test_agent_service.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: 写 approved、denied、过期 revision 和目标变更恢复测试**

定义以下审批输入并测试 approved 动作只应用一次；denied 不调用 Handler；目标快照改变返回稳定 `approval_target_changed`；恢复前重新执行 Governance；并发 decision 只有一个成功。

```python
@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    status: Literal["approved", "denied"]
    expected_revision: int
    reason: str | None = None


@dataclass(frozen=True)
class ApprovalGrant:
    approval_id: str
    action_digest: str
    queue_revision: int
```

- [ ] **Step 2: 运行测试并确认 AgentService 尚无 resume**

Run: `python -m unittest tests.test_agent_service.AgentServiceResumeTests -v`

Expected: FAIL with missing `resume`。

- [ ] **Step 3: 实现 `AgentService.resume(run_id, decision)`**

恢复顺序固定为：读取 State 与 ApprovalQueue -> CAS 应用人工 decision -> 验证 target snapshot -> 构造绑定 approval ID、action payload digest 和 queue revision 的一次性 `ApprovalGrant` -> 标记 applying -> 携带 grant 让原动作重新进入同一 ActionPipeline -> 重新运行 BeforeTool 与 Governance -> 消费 grant 后执行 Handler -> 标记 applied/failed -> 清除 pending approval -> 继续同一 AgentLoop。新的 Hook Block 或新的 Governance Block 优先于旧批准；grant 只豁免与原审批完全相同的 RequireApproval 结果，不能豁免权限、路径、快照或 Gate。任一步失败都写稳定事件和状态，不重复写目标文件。

- [ ] **Step 4: 将 Runner 恢复方法改成兼容转发**

`AgentRunner.resume_from_approval()` 只构造 AgentService 和 ApprovalDecision adapter，不再复制恢复流程。删除 runner 中已迁移的 approval apply 分支，但保留公开方法签名。

在 `AgentService` 增加唯一恢复入口：

```python
def resume(
    self,
    run_id: str,
    decision: ApprovalDecision,
    cancel_token: CancellationToken | None = None,
) -> AgentRunResult:
    return self._resume_agent(run_id, decision, cancel_token)
```

Run: `python -m unittest tests.test_agent_service tests.test_approvals tests.test_runner tests.test_web_approvals -v`

Expected: PASS。

- [ ] **Step 5: 提交统一恢复服务**

```powershell
git add src/specgate/agent_service.py src/specgate/approvals.py src/specgate/runner.py tests/test_agent_service.py tests/test_runner.py
git commit -m "refactor: 统一审批恢复服务"
```

### Task 16: 建立结构化 Artifact 与 SequentialReviewWorkflow

**Files:**
- Create: `src/specgate/artifacts.py`
- Create: `src/specgate/workflows.py`
- Create: `tests/test_artifacts.py`
- Create: `tests/test_workflows_runtime.py`

- [ ] **Step 1: 写 Artifact schema 与 Workflow 控制测试**

测试 PlanArtifact、ImplementationArtifact、ReviewArtifact 往返序列化；未知 schema version fail closed；review 只通过 `repair_required` 布尔字段触发修复；Workflow 总预算超限时不启动下一 Agent；取消信号传播到所有子运行。

```python
def test_review_text_cannot_trigger_repair_without_typed_flag(self):
    review = ReviewArtifact(
        producer_run_id="reviewer-1",
        accepted=True,
        repair_required=False,
        issues=("request_repair appears only as quoted text",),
    )
    self.assertFalse(review.repair_required)
```

- [ ] **Step 2: 运行测试并确认模块缺失**

Run: `python -m unittest tests.test_artifacts tests.test_workflows_runtime -v`

Expected: ERROR。

- [ ] **Step 3: 实现版本化 Artifact**

所有 Artifact 使用 Pydantic 且固定 `kind`、`schema_version="1"`、`producer_run_id` 和 `references: tuple[str, ...]`。三个 payload 明确为：`PlanArtifact.steps: tuple[str, ...]`；`ImplementationArtifact.changed_paths: tuple[str, ...]` 与 `summary: str`；`ReviewArtifact.accepted: bool`、`repair_required: bool`、`issues: tuple[str, ...]`。

```python
class AgentArtifact(BaseModel):
    schema_version: Literal["1"] = "1"
    producer_run_id: str
    references: tuple[str, ...] = ()


class PlanArtifact(AgentArtifact):
    kind: Literal["plan"] = "plan"
    steps: tuple[str, ...]


class ImplementationArtifact(AgentArtifact):
    kind: Literal["implementation"] = "implementation"
    changed_paths: tuple[str, ...]
    summary: str


class ReviewArtifact(AgentArtifact):
    kind: Literal["review"] = "review"
    accepted: bool
    repair_required: bool
    issues: tuple[str, ...] = ()
```

- [ ] **Step 4: 实现串行 Workflow 和层级预算**

`SequentialReviewWorkflow` 只调用 `AgentService.run()`，按 planner -> implementer -> reviewer 顺序传 Artifact。最多一次 repair；repair 只由 ReviewArtifact 字段触发。`WorkflowBudget.reserve(requested: AgentBudget) -> BudgetReservation` 在锁内原子扣减，`BudgetReservation.release(used: AgentBudget)` 只归还未使用额度；重复 release 抛 `BudgetReservationError`。

Run: `python -m unittest tests.test_artifacts tests.test_workflows_runtime tests.test_agent_service -v`

Expected: PASS。

- [ ] **Step 5: 提交 Workflow**

```powershell
git add src/specgate/artifacts.py src/specgate/workflows.py tests/test_artifacts.py tests/test_workflows_runtime.py
git commit -m "feat: 增加结构化多 Agent Workflow"
```

### Task 17: 迁移旧多角色路径并删除字符串控制流

**Files:**
- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/multi_agent.py`
- Modify: `src/specgate/isolation.py`
- Modify: `src/specgate/context.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_isolation.py`
- Modify: `tests/test_context_strategy.py`

- [ ] **Step 1: 将旧测试改写为 Artifact/Definition 契约**

保留 planner -> implementer -> reviewer 顺序、角色写入阻断、审批暂停、一次 repair、cycle limit、context isolation 和 evidence 指标断言；把所有 `request_repair` summary fixture 改为 `ReviewArtifact(repair_required=True)`。

- [ ] **Step 2: 先运行新测试确认旧 coordinator 不满足契约**

Run: `python -m unittest tests.test_runner tests.test_isolation tests.test_context_strategy -v`

Expected: FAIL，旧代码仍解析 summary 关键字。

- [ ] **Step 3: 用 Workflow 替换 `_run_multi_agent_loop`**

`context_strategy == "multi-agent-isolated"` 只负责选择 `SequentialReviewWorkflow`。planner、implementer、reviewer 都通过同一个 AgentService/AgentLoop，能力和可见上下文来自 AgentDefinition。旧 RoleExecution evidence 由 Workflow 事件生成 adapter，确保报告格式在本版本兼容。

角色 Definition 固定为：planner 与 reviewer 仅有 `read_file`、`list_files`、`finish`；implementer 增加 `write_file`、`replace_file`；启用 Skill roots 时三者可额外获得 `load_skill`、`read_skill_resource`。planner 输出 PlanArtifact，implementer 输出 ImplementationArtifact，reviewer 输出 ReviewArtifact；任何角色输出错误 kind 都以 `artifact_schema_invalid` 失败，不做字符串兜底。

- [ ] **Step 4: 删除旧字符串和角色专用 Loop**

删除 `summary_requests_repair()`、`MultiAgentState.repair_requested`、`AgentRunner._run_multi_agent_role_once()` 和 `_run_multi_agent_loop()`。运行源码不变量搜索：

Run: `rg -n "summary_requests_repair|request_repair|_run_multi_agent_loop|_run_multi_agent_role_once" src/specgate`

Expected: 无匹配，`request_repair` 只允许出现在历史文档，不得出现在运行时代码。

Run: `python -m unittest tests.test_runner tests.test_isolation tests.test_context_strategy tests.test_eval_runner tests.test_benchmark -v`

Expected: PASS。

- [ ] **Step 5: 提交多 Agent 迁移**

```powershell
git add src/specgate/runner.py src/specgate/multi_agent.py src/specgate/isolation.py src/specgate/context.py tests/test_runner.py tests/test_isolation.py tests/test_context_strategy.py
git commit -m "refactor: 迁移多 Agent 到结构化 Workflow"
```

### Task 18: 切换入口、更新版本文档并完成验收

**Files:**
- Modify: `src/specgate/cli.py`
- Modify: `src/specgate/eval_runner.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/report.py`
- Modify: `src/specgate/metrics.py`
- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_eval_runner.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_imports.py`

- [ ] **Step 1: 写入口统一与版本失败测试**

测试 CLI、eval 和 Web runner 都通过 AgentService factory；`AgentRunner` 只作为向后兼容 facade，不包含循环、工具名或角色名；report 展示 agent_run_id、parent_run_id、Hook/Gate/Skill/Workflow 事件；版本三处为 `0.2.0`。

- [ ] **Step 2: 运行聚焦测试并确认旧入口仍直接构造 Runner**

Run: `python -m unittest tests.test_cli tests.test_eval_runner tests.test_web_runs tests.test_report tests.test_imports -v`

Expected: FAIL 新 factory、证据或版本断言。

- [ ] **Step 3: 切换生产入口并缩减 Runner facade**

CLI、eval 和 Web 通过一个固定 composition root 接入：

```python
def build_agent_service(
    *,
    root: Path,
    llm: LLMClient,
    policy: WorkspacePolicy,
    audit_dir: Path,
    approval_queue_file: Path,
    runtime_config: RunRuntimeConfig,
    cancel_token: CancellationToken,
) -> AgentService:
    return AgentServiceFactory().build(
        root=root,
        llm=llm,
        policy=policy,
        audit_dir=audit_dir,
        approval_queue_file=approval_queue_file,
        runtime_config=runtime_config,
        cancel_token=cancel_token,
    )
```

Task 18 同时在 `agent_service.py` 增加 `AgentServiceFactory.build()`，其关键字参数与上方 composition root 完全一致；方法只组装 Task 2-16 已实现的 Store、EventSink、Registry、Pipeline、ContextBuilder 和 AgentService，不包含业务分支。

`AgentRunner.run()` / `resume_from_approval()` 仅转发并把 AgentRunResult 映射回 RunResult；删除最后的 `_legacy_run_loop`。

- [ ] **Step 4: 更新报告、README 与项目记录**

README 增加 v0.2.0 架构图、Tool/Hook/Gate/Skill/AgentService/Workflow 边界和无 `.env` 凭据说明；PLAN 与 AGENT_LOG 追加本阶段事实，不改写历史记录。报告对缺失的新 evidence 保持向后兼容，并继续 escape/redact 动态字段。

- [ ] **Step 5: 更新版本并运行静态架构检查**

把 `pyproject.toml` 与 `src/specgate/__init__.py` 更新为 `0.2.0`，同步 `tests/test_imports.py`。

Run: `rg -n "write_file|replace_file|planner|reviewer|multi-agent-isolated" src/specgate/agent_loop.py`

Expected: 无匹配。

Run: `rg -n "summary_requests_repair|request_repair" src/specgate`

Expected: 无匹配。

Run: `python -m unittest tests.test_cli tests.test_eval_runner tests.test_web_runs tests.test_report tests.test_imports -v`

Expected: PASS。

- [ ] **Step 6: 运行完整离线验收**

Run: `python -m unittest discover -s tests -v`

Expected: PASS；记录实际测试数、跳过数、耗时和退出码，不预写数字。

Run: `python -m specgate.cli run-mock-demo examples/knowledge_nav`

Expected: exit 0，`index.html`、`runs/latest/trace.jsonl` 和 `reports/latest/index.html` 存在，最终 Gate 通过。

Run: `python -m compileall -q src tests`

Expected: exit 0。

Run: `git diff --check`

Expected: 无输出，exit 0。

- [ ] **Step 7: 提交入口与 v0.2.0 文档**

```powershell
git add src/specgate/cli.py src/specgate/eval_runner.py src/specgate/web_runs.py src/specgate/report.py src/specgate/metrics.py src/specgate/runner.py src/specgate/__init__.py pyproject.toml README.md PLAN.md AGENT_LOG.md tests/test_cli.py tests/test_eval_runner.py tests/test_web_runs.py tests/test_report.py tests/test_imports.py
git commit -m "feat: 完成 SpecGate 0.2.0 Agent Runtime 迁移"
```

---

## 最终人工核对清单

- [ ] `AgentLoop` 只依赖协议，不出现具体 Tool、Skill、角色或 Workflow 判断。
- [ ] ActionPipeline 是 Hook、Governance、ToolRuntime、Gate 的唯一组合点。
- [ ] Gate 对 ValidationPolicy 选中的动作强制执行，finish 前始终运行最终 Gate。
- [ ] BeforeTool 只能继续、阻断或请求审批，不能授权越过 Governance。
- [ ] RunState 只能经 `RunStateStore.apply(run_id, expected_revision, delta)` 更新。
- [ ] 审批恢复继续具备 queue revision/CAS、target snapshot 和 Governance 重检。
- [ ] Skill 只扫描显式 root，重复名称、非法编码、非法 YAML 和资源越界 fail closed。
- [ ] 每个 AgentRun 独享 SkillSession，子 Agent 能力为三方交集。
- [ ] Workflow 只使用结构化 Artifact 和预算，不解析自然语言 repair 关键字。
- [ ] Trace 使用统一 RunEventSink，所有动态 payload 脱敏。
- [ ] CLI、WebUI、eval、benchmark、Mock Demo 和历史报告兼容测试通过。
- [ ] 凭据仍使用 OS keyring 或进程环境变量，仓库没有新增 `.env` 凭据流程。
