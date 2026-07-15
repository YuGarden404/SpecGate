# Runner 运行配置接线设计

日期：2026-07-15

## 1. 背景

SpecGate 已经完成安全凭据存储和 Web 运行时加固。当前 Web run 能使用用户保存的治理策略和上下文策略，但执行路径仍存在以下断点：

- `max_steps` 在 Web MockLLM 入口中固定为 5；
- 上下文文件选择固定使用 12000 字符预算；
- 检索固定使用默认 `top_k=6` 和 9000 字符预算；
- 压缩固定使用 1200 字符工具结果阈值；
- run 没有保存不可变配置快照；
- HITL resume 会重新读取用户当前 Settings，可能与首次执行使用不同配置；
- Trace、Debug API 和 Audit 页面无法展示一份可相互核对的完整实际配置。

本阶段把这些现有配置接入真实 Web MockLLM 执行路径。目标不是新增算法，而是让配置具有明确的创建、冻结、验证、执行和审计生命周期。

## 2. 已确认决策

- 继续只使用 MockLLM，不接真实 LLM。
- 扩展现有 Settings API，并在现有设置卡片中增加简洁的高级配置表单，不重新设计页面。
- 用户可修改的运行配置固定为七项：
  - `governance_profile`
  - `context_strategy`
  - `max_steps`
  - `context_budget_chars`
  - `retrieval_top_k`
  - `retrieval_budget_chars`
  - `compression_max_tool_result_chars`
- 隔离方式继续由 `context_strategy` 控制，不新增独立隔离开关或角色列表编辑器。
- 在 `runs.runtime_config_json` 中保存带 schema 版本的规范化 JSON 快照。
- 七项配置在 run 创建时全部冻结；首次执行、重启恢复和 HITL resume 使用同一快照。
- 旧 run 在 schema v3→v4 迁移时使用迁移时用户 Settings 和新增字段默认值生成快照，并标记 `source: "migration"`。
- 上下文字符预算只约束进入上下文的工作区文件；Action Protocol、Policy Boundary、最新 Gate 等安全关键段不参与裁剪。

## 3. 目标与非目标

### 3.1 目标

- 用一个强类型配置对象统一默认值、合法范围、序列化和执行参数映射。
- 创建 run 时在同一数据库事务中读取 Settings 并写入不可变快照。
- 让 max steps、上下文文件预算、检索 top-k/预算和压缩阈值确定性改变 Runner 行为或 evidence。
- Settings 修改只影响之后创建的 run。
- resume、进程重启后的 queued 补入和恢复执行继续使用原 run 快照。
- 非法 Settings 或损坏快照在进入 Runner 前失败关闭。
- Trace、Debug API 和 Audit 页面展示同一份实际配置。
- 保持 CLI、eval、Gate、WorkspacePolicy、HITL、取消、超时和发布语义兼容。

### 3.2 非目标

- 不新增检索、压缩或隔离算法。
- 不重新设计 Settings 页面布局。
- 不允许配置改变工具白名单、读写路径、Gate 或审批规则。
- 不把 API Key、路径策略、停止信号或内部 `review_existing_writes` 写入配置快照。
- 不新增真实 LLM 配置或调用路径。
- 不在本阶段同步最终课程证据；该工作属于 `docs-final-evidence-sync`。

## 4. 强类型配置对象

新增 `src/specgate/runtime_config.py`，定义冻结的 `RunRuntimeConfig`。建议字段如下：

```python
@dataclass(frozen=True)
class RunRuntimeConfig:
    schema_version: int = 1
    source: Literal["created", "migration"] = "created"
    governance_profile: str = "review"
    context_strategy: str = "injection-safe"
    max_steps: int = 5
    context_budget_chars: int = 12000
    retrieval_top_k: int = 6
    retrieval_budget_chars: int = 9000
    compression_max_tool_result_chars: int = 1200
```

配置对象负责：

- `__post_init__()` 完成所有类型、枚举和范围校验；
- `from_settings()` 从数据库 Settings 行构造 `source="created"` 快照；
- `for_migration()` 构造 `source="migration"` 快照；
- `to_dict()` 生成稳定公共结构；
- `to_json()` 使用 `ensure_ascii=False`、`sort_keys=True` 和紧凑分隔符生成规范化 JSON；
- `from_json()` 严格拒绝非对象 JSON、未知字段、缺失字段和不支持的 schema 版本。

Python 的 `bool` 是 `int` 子类，因此整数校验必须显式拒绝布尔值。不得使用会把字符串或浮点数自动转换为整数的宽松解析。

## 5. 默认值和合法范围

| 配置 | 默认值 | 合法范围或枚举 |
| --- | ---: | --- |
| `governance_profile` | `review` | 复用 `VALID_GOVERNANCE_PROFILES` |
| `context_strategy` | `injection-safe` | 复用 `VALID_CONTEXT_STRATEGIES` |
| `max_steps` | 5 | 1–20 |
| `context_budget_chars` | 12000 | 1000–100000 |
| `retrieval_top_k` | 6 | 1–20 |
| `retrieval_budget_chars` | 9000 | 500–50000 |
| `compression_max_tool_result_chars` | 1200 | 100–10000 |

这些范围同时用于配置对象、Settings API 和前端输入属性。配置对象是最终真相来源，其他层的校验用于更早返回友好错误，不能替代配置对象验证。

## 6. 数据库 schema v4

### 6.1 新数据库

`user_settings` 增加：

```text
max_steps integer not null default 5
context_budget_chars integer not null default 12000
retrieval_top_k integer not null default 6
retrieval_budget_chars integer not null default 9000
compression_max_tool_result_chars integer not null default 1200
```

`runs` 增加：

```text
runtime_config_json text
```

新 run 必须写入非空、可解析且通过验证的快照。迁移完成后所有既有 run 也必须具有快照。SQLite v3→v4 使用 `ALTER TABLE` 时不重建带外键的 runs 表，因此非空不变量由迁移检查和应用写入路径共同保证；任何执行入口仍需重新解析并验证，不能仅信任数据库列存在。

### 6.2 v3→v4 迁移

迁移在单个 `BEGIN IMMEDIATE` 事务中执行：

1. 为 `user_settings` 增加五个带默认值的整数列。
2. 为 `runs` 增加 `runtime_config_json`。
3. 查询每个 run 及其用户 Settings。
4. 用户没有 Settings 行时使用完整默认值。
5. 为每个旧 run 写入 `source="migration"` 的规范化快照。
6. 重新查询并确认不存在空快照。
7. 写入 `pragma user_version = 4` 并提交。

任何序列化、查询或更新失败都回滚整个迁移。v1→v2→v3→v4 和 v2→v3→v4 连续迁移必须继续工作。

## 7. 原子快照创建

当前 `_reserve_initializing_run()` 已使用短写事务完成用户/项目准入和 run 插入。本阶段在这个事务内：

1. `insert or ignore` 用户 Settings 默认行；
2. 读取完整七项 Settings；
3. 构造并验证 `RunRuntimeConfig(source="created")`；
4. 把规范化 JSON 与 initializing run 一起写入。

这样 Settings 更新与 run 创建竞争时，快照只能是更新前或更新后的完整配置之一，不能由两个版本的字段拼接而成。

容量预留、运行目录初始化和失败清理保持现有顺序。全局容量拒绝仍发生在创建数据库或目录副作用之前。

## 8. Settings API 与页面

### 8.1 API

现有 `GET /api/settings` 返回七项运行配置和凭据状态。`PUT /api/settings` 请求扩展为七项配置。

Pydantic 请求模型对五个数字字段使用 `StrictInt` 和对应范围。服务函数在开启数据库事务前再次构造 `RunRuntimeConfig`，确保：

- 缺失字段不会静默使用旧值；
- 字符串、浮点数和布尔值不会被转换为整数；
- 非法治理或上下文策略返回稳定错误；
- 任一字段无效时整次更新无副作用。

响应继续包含 `llm_mode: "mock"`，且不暴露凭据明文。

### 8.2 前端

现有 Settings 卡片增加一个小型表单，包含两个 select、五个 number input、保存按钮和说明文字。number input 使用与后端一致的 `min`、`max` 和 `step="1"`。

页面明确提示：

> 设置只影响之后创建的运行；已有运行继续使用创建时配置快照。

前端校验只改善交互，后端仍执行完整严格校验。

## 9. Runner 与 Context 接线

Web 执行入口解析 run 的 `runtime_config_json`，并把配置映射到已有核心对象：

```text
max_steps
  → AgentRunner(max_steps=...)

context_budget_chars
  → build_context_pack_with_metadata(...)
  → select_context_files(budget_chars=...)

retrieval_top_k + retrieval_budget_chars
  → retrieval.RetrievalConfig(...)
  → retrieve_chunks(...)

compression_max_tool_result_chars
  → context_lifecycle.CompressionConfig(...)
  → compress_runtime_feedback(...)

context_strategy
  → 现有 baseline / injection-safe / rag-select / compressed-rag /
    isolated-harness / multi-agent-isolated 分支

governance_profile
  → GovernanceConfig(profile=...)
```

`AgentRunner`、普通上下文构建和角色上下文构建增加可选预算/配置参数，并保留现有默认值。CLI、eval 和既有单元测试调用方无需一次性迁移。

安全关键段不参与 `context_budget_chars` 的工作区文件预算。检索预算只约束选中检索片段，不能提升路径读取权限；`allowed_read_paths` 过滤继续优先于检索配置。

隔离继续由 `context_strategy` 决定。配置不能修改角色能力矩阵或 WorkspacePolicy。

## 10. 首次执行、resume 与重启恢复

`execute_run_once()` 和 `resume_run_once()` 不再调用 `get_runtime_settings()`。两者都从 run 行解析同一快照。

- 首次执行：解析快照后才构造 MockLLM 和 Runner。
- queued 补入：`RunTask` 不复制配置，只携带 run ID；worker 认领后从数据库读取快照。
- HITL resume：`queue_run_resume()` 在把状态改为 queued 前验证快照。
- 进程重启：queued run 继续保留原 JSON；恢复 provider 只重新调度，不重建快照。
- Settings 修改：不更新任何已有 run 的 JSON。

内部 `review_existing_writes` 和 `stop_check` 继续由执行层单独传递，不写入快照。

## 11. 失败关闭与稳定错误

### 11.1 Settings 错误

Settings API 对非法用户输入返回 HTTP 400，detail 使用结构化对象：

```json
{
  "code": "invalid_runtime_config",
  "message": "运行配置无效 / Invalid runtime configuration",
  "field": "max_steps"
}
```

响应不回显任意原始 JSON。数据库保持更新前状态。

### 11.2 已存快照错误

- 快照 JSON 损坏、缺字段、含未知字段或 schema 版本过新都产生 `RuntimeConfigError`。
- 首次执行在进入 Runner 前捕获错误，把 run 标记为 `failed`，稳定错误信息为 `invalid_runtime_config`，不生成或发布产物。
- resume API 在状态切换前验证；非法快照返回 HTTP 409，run 保持 `needs_approval`。
- Debug API 不返回损坏原文，只返回 `runtime_config: null` 和 `runtime_config_error: "invalid_runtime_config"`。

## 12. Trace、Debug 与 Audit

### 12.1 Trace

Web Runner 构造完成并重置或打开 audit trace 后，追加：

```json
{
  "event_type": "runtime_config_applied",
  "payload": {
    "phase": "initial",
    "config": {
      "schema_version": 1,
      "source": "created",
      "governance_profile": "review",
      "context_strategy": "injection-safe",
      "max_steps": 5,
      "context_budget_chars": 12000,
      "retrieval_top_k": 6,
      "retrieval_budget_chars": 9000,
      "compression_max_tool_result_chars": 1200
    }
  }
}
```

resume 使用 `phase: "resume"` 并追加同一快照。Trace 只记录验证后的公共结构。

### 12.2 Debug API

`build_run_debug()` 增加顶层：

```text
runtime_config
runtime_config_error
```

正常时 `runtime_config_error` 为 null；损坏时 `runtime_config` 为 null。Debug 不再依赖 Trace 反推配置真相。

### 12.3 Audit 页面

Audit 增加“实际运行配置”区域，展示 schema 版本、来源和七项配置。治理与上下文策略优先读取 `debug.runtime_config`；旧 Trace helper 只作为兼容缺失数据的展示回退，不覆盖数据库快照。

## 13. 测试策略

### 13.1 配置核心

新增 `tests/test_runtime_config.py`，覆盖：

- 默认值和规范化 JSON；
- 每个字段的最小值、最大值和越界值；
- 严格拒绝 bool、float、字符串和 null；
- 未知字段、缺失字段、非对象 JSON 和未来 schema；
- created/migration source。

### 13.2 数据库和 Settings

扩展 `tests/test_web_db.py`、`tests/test_web_settings.py` 和 `tests/test_web_app.py`：

- 新库 schema v4；
- v3 旧 run 回填；
- v1/v2 连续迁移；
- 迁移失败完整回滚；
- Settings 默认值、边界值、严格类型和原子无副作用更新；
- run 创建与 Settings 修改竞争只产生完整快照。

### 13.3 Runner 与 Context

扩展 `tests/test_context.py` 和 `tests/test_runner.py`：

- context budget 改变 manifest 选择/截断证据；
- retrieval top-k 和预算改变选中片段证据；
- compression 阈值改变 cleared/summarized evidence；
- max steps 改变确定性的 Runner 终止位置；
- 安全关键段和 allowed-read policy 不受配置削弱；
- 角色上下文使用同一配置。

### 13.4 Web run、恢复和展示

扩展 `tests/test_web_runs.py`、`tests/test_web_debug.py` 和 `tests/test_web_static.py`：

- 初次执行使用 run 快照；
- 创建后修改 Settings 不影响 queued 执行；
- needs_approval 后修改 Settings 不影响 resume；
- 重启 queued 补入保留快照；
- 非法快照不调用 Runner、不发布产物；
- Trace initial/resume 事件与数据库快照一致；
- Debug 和 Audit 显示相同值；
- 设置页包含所有字段、范围和不可变提示。

### 13.5 最终验证

最终运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
git status --short --branch
```

预期全量测试通过，跳过项只来自既有平台权限场景。

## 14. 文件职责

新增：

- `src/specgate/runtime_config.py`：强类型运行配置、验证和规范化 JSON。
- `tests/test_runtime_config.py`：配置核心契约。

修改：

- `src/specgate/web_db.py`：schema v4 和迁移。
- `src/specgate/web_settings.py`：完整 Settings 读写与验证。
- `src/specgate/web_app.py`：严格 Settings 请求和结构化错误。
- `src/specgate/web_runs.py`：原子快照、首次执行/resume 接线和 Trace。
- `src/specgate/runner.py`：接收预算、检索和压缩参数。
- `src/specgate/context.py`：传递上下文、检索和压缩配置。
- `src/specgate/web_debug.py`：验证并返回快照。
- `src/specgate/web_static/app.js`：设置表单和 Audit 配置展示。
- 相关测试文件与阶段文档。

## 15. 验收标准

- 用户修改七项 Settings 后，新 run 保存完整、规范化、不可变的 JSON 快照。
- 修改 Settings 不影响已创建 run 的首次执行、resume 或重启恢复。
- 五个新增数值配置能够确定性改变 Runner 或 evidence。
- 非法用户配置无数据库副作用；非法快照不进入 Runner。
- Trace、Debug、Audit 与数据库快照值一致。
- WorkspacePolicy、Gate、HITL、取消、超时和发布安全边界无回退。
- WebUI 和自动验收继续只使用 MockLLM。
- 聚焦测试、全量测试、编译和差异检查通过。
