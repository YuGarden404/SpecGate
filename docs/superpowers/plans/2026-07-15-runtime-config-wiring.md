# Runner 运行配置接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Web MockLLM run 建立强类型 Settings、创建时不可变配置快照，并把 max steps、上下文预算、检索和压缩参数接入 Runner、Trace、Debug 与 Audit。

**Architecture:** 新增 `RunRuntimeConfig` 作为默认值、范围、JSON 和错误语义的唯一真相来源；SQLite schema v4 在 run 创建事务中冻结七项配置。Web 首次执行、queued 恢复和 HITL resume 只读取 run 快照，再把预算映射到现有 AgentRunner、Context、Retrieval 和 Compression 组件。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLite、`unittest`、原生 JavaScript、MockLLM。

## 执行状态

- [x] Task 1：强类型配置核心。
- [x] Task 2：SQLite schema v4 与迁移。
- [x] Task 3：Settings 服务和 API。
- [x] Task 4：创建时原子快照。
- [x] Task 5：Context、Retrieval、Compression 接线。
- [x] Task 6：AgentRunner 显式参数。
- [x] Task 7：首次执行、resume 和恢复使用原快照。
- [x] Task 8：非法快照失败关闭。
- [x] Task 9：Debug、Audit 和 Settings 实际配置展示。
- [x] Task 10：中文材料、最终验证和交付审查。

说明：计划中的分任务 Git 步骤由用户统一执行，因此不作为 Agent 实施完成条件。

最终执行证据：

- 高风险聚焦：`Ran 282 tests in 91.153s`，`OK (skipped=1)`。
- 审查修复后的 Web 恢复组合：`Ran 144 tests in 67.966s`，`OK (skipped=1)`。
- 全量 MockLLM 回归：`Ran 822 tests in 131.279s`，`OK (skipped=20)`。
- Python 编译、JavaScript 语法和空白差异检查均通过；LF→CRLF 信息是 Windows 工作区提示，不是空白错误。
- 主线程代码审查补充了 queued resume 快照损坏和并发取消竞态回归；本轮未派发 subagent，也未执行 Git 写操作。

---

## 实施约束

- 全程只使用 MockLLM，不访问真实 LLM 或外部网络。
- 每项行为严格执行 RED → GREEN → REFACTOR。
- 不改变 WorkspacePolicy、Gate、HITL、取消、超时、发布和运行目录隔离语义。
- 不新增检索、压缩或隔离算法。
- Git 暂存、提交、推送和 PR 由用户执行；计划中的 Git 命令只作为用户操作说明。
- 当前基线为 `main@49f66a2`，上一阶段本地全量为 799 个测试、20 个跳过项；执行前必须重新记录本分支基线。

## 文件职责映射

**新增：**

- `src/specgate/runtime_config.py`：七项运行配置、默认值、严格验证、规范化 JSON 和稳定错误。
- `tests/test_runtime_config.py`：配置核心契约。

**修改：**

- `src/specgate/web_db.py`：schema v4、Settings 数值列、run JSON 快照和 v3→v4 迁移。
- `src/specgate/web_settings.py`：完整 Settings 读取、验证和原子更新。
- `src/specgate/web_app.py`：严格 Settings 请求模型、结构化 400/409 映射。
- `src/specgate/web_runs.py`：原子创建快照、执行/resume 读取、Trace 和失败关闭。
- `src/specgate/context.py`：上下文文件预算、检索配置和压缩配置传递。
- `src/specgate/runner.py`：接收并传递预算配置。
- `src/specgate/web_debug.py`：验证并返回 run 配置快照。
- `src/specgate/web_static/app.js`：Settings 表单和 Audit 实际配置表。
- `README.md`、`PLAN.md`、`AGENT_LOG.md`：本阶段行为与验证证据。
- 对应 `tests/test_*.py`：迁移、Settings、Context、Runner、Web run、Debug、API 和静态页面回归。

## Task 1：记录基线并实现强类型运行配置

**Files:**

- Create: `src/specgate/runtime_config.py`
- Create: `tests/test_runtime_config.py`

- [ ] **Step 1：运行干净分支基线**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
git status --short --branch
```

Expected: `OK (skipped=20)`，测试数不少于 799；状态只允许已有设计和计划文档为未跟踪文件。

- [ ] **Step 2：写配置默认值和规范化 JSON 的失败测试**

创建 `tests/test_runtime_config.py`：

```python
import json
import unittest

from specgate.runtime_config import RunRuntimeConfig, RuntimeConfigError


class RunRuntimeConfigTests(unittest.TestCase):
    def test_defaults_and_canonical_json_are_stable(self):
        config = RunRuntimeConfig()

        self.assertEqual(
            config.to_dict(),
            {
                "schema_version": 1,
                "source": "created",
                "governance_profile": "review",
                "context_strategy": "injection-safe",
                "max_steps": 5,
                "context_budget_chars": 12000,
                "retrieval_top_k": 6,
                "retrieval_budget_chars": 9000,
                "compression_max_tool_result_chars": 1200,
            },
        )
        self.assertEqual(
            config.to_json(),
            json.dumps(config.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(RunRuntimeConfig.from_json(config.to_json()), config)

    def test_settings_and_migration_constructors_set_source(self):
        values = {
            "governance_profile": "strict",
            "context_strategy": "rag-select",
            "max_steps": 7,
            "context_budget_chars": 16000,
            "retrieval_top_k": 4,
            "retrieval_budget_chars": 7000,
            "compression_max_tool_result_chars": 900,
        }

        self.assertEqual(RunRuntimeConfig.from_settings(values).source, "created")
        self.assertEqual(RunRuntimeConfig.for_migration(values).source, "migration")
```

- [ ] **Step 3：写边界、严格类型和 schema 失败测试**

继续加入：

```python
    def test_numeric_boundaries_are_inclusive(self):
        minimum = RunRuntimeConfig(
            max_steps=1,
            context_budget_chars=1000,
            retrieval_top_k=1,
            retrieval_budget_chars=500,
            compression_max_tool_result_chars=100,
        )
        maximum = RunRuntimeConfig(
            max_steps=20,
            context_budget_chars=100000,
            retrieval_top_k=20,
            retrieval_budget_chars=50000,
            compression_max_tool_result_chars=10000,
        )
        self.assertEqual(minimum.max_steps, 1)
        self.assertEqual(maximum.max_steps, 20)

    def test_invalid_numeric_values_report_the_field(self):
        cases = (
            ("max_steps", 0),
            ("max_steps", 21),
            ("context_budget_chars", 999),
            ("context_budget_chars", 100001),
            ("retrieval_top_k", 0),
            ("retrieval_top_k", 21),
            ("retrieval_budget_chars", 499),
            ("retrieval_budget_chars", 50001),
            ("compression_max_tool_result_chars", 99),
            ("compression_max_tool_result_chars", 10001),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeConfigError) as raised:
                RunRuntimeConfig(**{field: value})
            self.assertEqual(raised.exception.field, field)
            self.assertEqual(raised.exception.code, "invalid_runtime_config")

    def test_bool_float_string_and_none_are_not_integers(self):
        for value in (True, 5.0, "5", None):
            with self.subTest(value=value), self.assertRaises(RuntimeConfigError):
                RunRuntimeConfig(max_steps=value)

    def test_json_rejects_missing_unknown_and_future_schema_fields(self):
        valid = RunRuntimeConfig().to_dict()
        invalid_payloads = []
        missing = dict(valid)
        missing.pop("max_steps")
        invalid_payloads.append(missing)
        unknown = {**valid, "unknown": 1}
        invalid_payloads.append(unknown)
        future = {**valid, "schema_version": 2}
        invalid_payloads.append(future)
        schema_bool = {**valid, "schema_version": True}
        invalid_payloads.append(schema_bool)

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(RuntimeConfigError):
                RunRuntimeConfig.from_json(json.dumps(payload))

        for raw in ("[]", "null", "not-json"):
            with self.subTest(raw=raw), self.assertRaises(RuntimeConfigError):
                RunRuntimeConfig.from_json(raw)
```

- [ ] **Step 4：运行测试确认 RED**

Run:

```powershell
python -m unittest tests.test_runtime_config
```

Expected: FAIL with `ModuleNotFoundError: No module named 'specgate.runtime_config'`。

- [ ] **Step 5：实现配置对象和稳定错误**

创建 `src/specgate/runtime_config.py`：

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Literal, Mapping

from specgate.approvals import VALID_GOVERNANCE_PROFILES
from specgate.config import VALID_CONTEXT_STRATEGIES


class RuntimeConfigError(ValueError):
    code = "invalid_runtime_config"

    def __init__(self, field: str, message: str = "运行配置无效 / Invalid runtime configuration") -> None:
        self.field = field
        super().__init__(message)


def _strict_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeConfigError(field)
    if not minimum <= value <= maximum:
        raise RuntimeConfigError(field)
    return value


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

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise RuntimeConfigError("schema_version")
        if self.source not in {"created", "migration"}:
            raise RuntimeConfigError("source")
        if self.governance_profile not in VALID_GOVERNANCE_PROFILES:
            raise RuntimeConfigError("governance_profile")
        if self.context_strategy not in VALID_CONTEXT_STRATEGIES:
            raise RuntimeConfigError("context_strategy")
        _strict_int("max_steps", self.max_steps, 1, 20)
        _strict_int("context_budget_chars", self.context_budget_chars, 1000, 100000)
        _strict_int("retrieval_top_k", self.retrieval_top_k, 1, 20)
        _strict_int("retrieval_budget_chars", self.retrieval_budget_chars, 500, 50000)
        _strict_int(
            "compression_max_tool_result_chars",
            self.compression_max_tool_result_chars,
            100,
            10000,
        )

    @classmethod
    def from_settings(cls, values: Mapping[str, object]) -> RunRuntimeConfig:
        return cls(**{name: values[name] for name in _SETTING_FIELDS})

    @classmethod
    def for_migration(cls, values: Mapping[str, object]) -> RunRuntimeConfig:
        defaults = cls().to_dict()
        merged = {name: values.get(name, defaults[name]) for name in _SETTING_FIELDS}
        return cls(source="migration", **merged)

    @classmethod
    def from_json(cls, raw: str) -> RunRuntimeConfig:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeConfigError("runtime_config_json") from exc
        expected = {field.name for field in fields(cls)}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise RuntimeConfigError("runtime_config_json")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise RuntimeConfigError("runtime_config_json") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_SETTING_FIELDS = (
    "governance_profile",
    "context_strategy",
    "max_steps",
    "context_budget_chars",
    "retrieval_top_k",
    "retrieval_budget_chars",
    "compression_max_tool_result_chars",
)
```

- [ ] **Step 6：运行配置测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_runtime_config
```

Expected: PASS。

- [ ] **Step 7：由用户提交 Task 1**

```powershell
git add src/specgate/runtime_config.py tests/test_runtime_config.py
git commit -m "feat: 新增强类型 Runner 运行配置"
```

## Task 2：升级 SQLite schema v4 并回填旧 run

**Files:**

- Modify: `src/specgate/web_db.py`
- Modify: `tests/test_web_db.py`

- [ ] **Step 1：写新库 schema v4 失败测试**

在 `tests/test_web_db.py` 增加：

```python
    def test_new_database_uses_schema_version_four_and_runtime_config_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.sqlite3"
            init_db(db_path)

            with closing(connect_db(db_path)) as conn:
                version = conn.execute("pragma user_version").fetchone()[0]
                settings_columns = {
                    row["name"] for row in conn.execute("pragma table_info(user_settings)")
                }
                run_columns = {row["name"] for row in conn.execute("pragma table_info(runs)")}

            self.assertEqual(version, 4)
            self.assertTrue(
                {
                    "max_steps",
                    "context_budget_chars",
                    "retrieval_top_k",
                    "retrieval_budget_chars",
                    "compression_max_tool_result_chars",
                }.issubset(settings_columns)
            )
            self.assertIn("runtime_config_json", run_columns)
```

- [ ] **Step 2：写 v3 回填和连续迁移失败测试**

先在 `WebDbTests` 增加最小但字段真实的 v3 fixture：

```python
    def create_version_three_database(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "web.sqlite3"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                """
                create table users (
                    id integer primary key,
                    username text not null,
                    password_hash text not null
                );
                create table user_settings (
                    user_id integer primary key,
                    governance_profile text not null default 'review',
                    context_strategy text not null default 'injection-safe',
                    api_key_configured integer not null default 0,
                    api_key_ciphertext text
                );
                create table projects (
                    id integer primary key,
                    user_id integer not null,
                    name text not null
                );
                create table runs (
                    id integer primary key,
                    project_id integer not null,
                    user_id integer not null,
                    status text not null,
                    prompt text not null,
                    trust_level text,
                    report_path text,
                    index_artifact_path text,
                    zip_artifact_path text,
                    error_message text,
                    created_at text,
                    started_at text,
                    finished_at text,
                    cancel_requested_at text,
                    deadline_at text
                );
                pragma user_version = 3;
                """
            )
        return db_path
```

再插入 user、Settings 和 run，调用 `init_db()`：

```python
    def test_version_three_migrates_settings_and_backfills_run_snapshots(self):
        db_path = self.create_version_three_database()
        with closing(connect_db(db_path)) as conn:
            user_id = conn.execute(
                "insert into users (username, password_hash) values ('alice', 'hash')"
            ).lastrowid
            conn.execute(
                "insert into user_settings (user_id, governance_profile, context_strategy) values (?, ?, ?)",
                (user_id, "strict", "rag-select"),
            )
            project_id = conn.execute(
                "insert into projects (user_id, name) values (?, 'Site')",
                (user_id,),
            ).lastrowid
            run_id = conn.execute(
                "insert into runs (project_id, user_id, status, prompt) values (?, ?, 'queued', 'Build')",
                (project_id, user_id),
            ).lastrowid
            conn.commit()

        init_db(db_path)

        with closing(connect_db(db_path)) as conn:
            row = conn.execute("select runtime_config_json from runs where id = ?", (run_id,)).fetchone()
            settings = conn.execute("select * from user_settings where user_id = ?", (user_id,)).fetchone()
            self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 4)
        config = RunRuntimeConfig.from_json(row["runtime_config_json"])
        self.assertEqual(config.source, "migration")
        self.assertEqual(config.governance_profile, "strict")
        self.assertEqual(config.context_strategy, "rag-select")
        self.assertEqual(config.max_steps, 5)
        self.assertEqual(settings["context_budget_chars"], 12000)
```

同时把既有 v1 和 v2 测试 fixture 的 runs 表补齐 `project_id`、`user_id`，并创建对应 users、user_settings、projects 行；最终版本必须为 4 且所有旧 run 快照可解析。不得让测试 fixture 使用真实历史 schema 中不存在的简化行结构绕过迁移。

- [ ] **Step 3：写迁移回滚失败测试**

patch `specgate.web_db.RunRuntimeConfig.for_migration` 抛出 `RuntimeConfigError`，断言 `init_db()` 失败后：

```python
with closing(connect_db(db_path)) as conn:
    self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 3)
    self.assertNotIn(
        "runtime_config_json",
        {row["name"] for row in conn.execute("pragma table_info(runs)")},
    )
```

- [ ] **Step 4：运行迁移测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_db
```

Expected: FAIL because schema remains v3 and columns are missing。

- [ ] **Step 5：实现 schema 和 v3→v4 迁移**

在 `web_db.py`：

```python
LATEST_SCHEMA_VERSION = 4
```

把五个 Settings 列和 `runs.runtime_config_json` 加入 `SCHEMA`。新增：

```python
def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute("alter table user_settings add column max_steps integer not null default 5")
        conn.execute(
            "alter table user_settings add column context_budget_chars integer not null default 12000"
        )
        conn.execute("alter table user_settings add column retrieval_top_k integer not null default 6")
        conn.execute(
            "alter table user_settings add column retrieval_budget_chars integer not null default 9000"
        )
        conn.execute(
            "alter table user_settings add column compression_max_tool_result_chars integer not null default 1200"
        )
        conn.execute("alter table runs add column runtime_config_json text")
        rows = conn.execute(
            """
            select runs.id,
                   coalesce(user_settings.governance_profile, 'review') as governance_profile,
                   coalesce(user_settings.context_strategy, 'injection-safe') as context_strategy,
                   coalesce(user_settings.max_steps, 5) as max_steps,
                   coalesce(user_settings.context_budget_chars, 12000) as context_budget_chars,
                   coalesce(user_settings.retrieval_top_k, 6) as retrieval_top_k,
                   coalesce(user_settings.retrieval_budget_chars, 9000) as retrieval_budget_chars,
                   coalesce(user_settings.compression_max_tool_result_chars, 1200)
                       as compression_max_tool_result_chars
            from runs
            left join user_settings on user_settings.user_id = runs.user_id
            order by runs.id
            """
        ).fetchall()
        for row in rows:
            config = RunRuntimeConfig.for_migration(dict(row))
            conn.execute(
                "update runs set runtime_config_json = ? where id = ?",
                (config.to_json(), row["id"]),
            )
        missing = conn.execute(
            "select count(*) from runs where runtime_config_json is null"
        ).fetchone()[0]
        if missing:
            raise RuntimeError("runtime config migration left empty snapshots")
        conn.execute("pragma user_version = 4")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

在 `init_db()` 中让 v1→v2、v2→v3 后继续执行 v3→v4，只有达到 4 才返回。

- [ ] **Step 6：运行数据库回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_db
```

Expected: PASS，包括 WAL/busy timeout 既有测试。

- [ ] **Step 7：由用户提交 Task 2**

```powershell
git add src/specgate/web_db.py tests/test_web_db.py
git commit -m "feat: 升级 Web 配置快照 schema v4"
```

## Task 3：扩展 Settings 服务和 API

**Files:**

- Modify: `src/specgate/web_settings.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_settings.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写完整 Settings 默认值和更新失败测试**

更新 `tests/test_web_settings.py` 默认结构，加入五个数值字段。新增原子失败测试：

```python
    def test_invalid_runtime_setting_does_not_partially_update(self):
        before = get_runtime_settings(db_path, user_id)
        with self.assertRaises(RuntimeConfigError) as raised:
            update_settings(
                db_path,
                user_id,
                governance_profile="strict",
                context_strategy="rag-select",
                max_steps=0,
                context_budget_chars=16000,
                retrieval_top_k=4,
                retrieval_budget_chars=7000,
                compression_max_tool_result_chars=900,
                credentials=service,
            )
        self.assertEqual(raised.exception.field, "max_steps")
        self.assertEqual(get_runtime_settings(db_path, user_id), before)
```

再用最小值和最大值各更新一次，断言响应保存精确整数。

- [ ] **Step 2：写 Settings API 严格类型和结构化 400 测试**

在 `tests/test_web_app.py` 注册用户后 PUT：

```python
payload = {
    "governance_profile": "strict",
    "context_strategy": "compressed-rag",
    "max_steps": 8,
    "context_budget_chars": 20000,
    "retrieval_top_k": 5,
    "retrieval_budget_chars": 8000,
    "compression_max_tool_result_chars": 700,
}
response = client.put("/api/settings", json=payload)
self.assertEqual(response.status_code, 200, response.text)
self.assertEqual(
    {key: response.json()["settings"][key] for key in payload},
    payload,
)
```

将 `max_steps` 依次改为 `True`、`5.0`、`"5"` 和 21，断言状态 400，detail code 为 `invalid_runtime_config`，并再次 GET 确认上一次合法值未改变。

- [ ] **Step 3：运行 Settings 测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_settings tests.test_web_app.WebAppTests.test_settings_can_be_updated_and_api_key_cleared
```

Expected: FAIL because service and request model only accept two fields。

- [ ] **Step 4：扩展 Settings 服务**

`get_runtime_settings()` 查询并返回七项字段。`update_settings()` 改为关键字参数并在打开写事务前构造：

```python
config = RunRuntimeConfig.from_settings(
    {
        "governance_profile": governance_profile,
        "context_strategy": context_strategy,
        "max_steps": max_steps,
        "context_budget_chars": context_budget_chars,
        "retrieval_top_k": retrieval_top_k,
        "retrieval_budget_chars": retrieval_budget_chars,
        "compression_max_tool_result_chars": compression_max_tool_result_chars,
    }
)
```

然后使用一条 UPDATE 写入七项值。`get_settings()` 继续合并凭据状态和 `llm_mode="mock"`。

- [ ] **Step 5：扩展 Pydantic 请求和错误映射**

`SettingsRequest` 使用：

```python
class SettingsRequest(BaseModel):
    governance_profile: str
    context_strategy: str
    max_steps: StrictInt = Field(ge=1, le=20)
    context_budget_chars: StrictInt = Field(ge=1000, le=100000)
    retrieval_top_k: StrictInt = Field(ge=1, le=20)
    retrieval_budget_chars: StrictInt = Field(ge=500, le=50000)
    compression_max_tool_result_chars: StrictInt = Field(ge=100, le=10000)
```

扩展全局 `RequestValidationError` handler：当 URL 为 `/api/settings` 时返回：

```json
{
  "detail": {
    "code": "invalid_runtime_config",
    "message": "运行配置无效 / Invalid runtime configuration",
    "field": "max_steps"
  }
}
```

服务层 `RuntimeConfigError` 使用同一结构化 detail。其他接口现有 `invalid_request` 响应保持不变。

- [ ] **Step 6：运行 Settings/API 回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_settings tests.test_web_app
```

Expected: PASS。

- [ ] **Step 7：由用户提交 Task 3**

```powershell
git add src/specgate/web_settings.py src/specgate/web_app.py tests/test_web_settings.py tests/test_web_app.py
git commit -m "feat: 扩展 Web Runner 配置设置"
```

## Task 4：在 run 创建事务中冻结不可变快照

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_runs.py`

- [ ] **Step 1：写创建快照失败测试**

在 `tests/test_web_runs.py` 更新用户 Settings 后创建 run：

```python
run = create_run(
    db_path,
    project["id"],
    user["id"],
    "Build with frozen config",
    data_root=data_root,
)
config = RunRuntimeConfig.from_json(run["runtime_config_json"])
self.assertEqual(config.source, "created")
self.assertEqual(config.governance_profile, "strict")
self.assertEqual(config.context_strategy, "compressed-rag")
self.assertEqual(config.max_steps, 8)
self.assertEqual(config.context_budget_chars, 20000)
```

- [ ] **Step 2：写并发完整快照失败测试**

使用两个线程和两个 Event。patch `specgate.web_runs.RunRuntimeConfig.from_settings`，在 create 事务读取 Settings 后阻塞；另一个线程调用 `update_settings()`。释放 create 后断言：

- update 在 create 提交前不能完成；
- run 快照七项全部来自旧配置；
- update 完成后 GET Settings 七项全部来自新配置；
- 不存在旧新字段混合。

线程通过 `join(timeout=2)` 和 Event 条件等待，不使用固定 sleep。

- [ ] **Step 3：运行创建测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_create_run_records_queued_status_and_user_message tests.test_web_runs.WebRunsTests.test_create_run_freezes_complete_runtime_config
```

Expected: FAIL because runs has no populated snapshot on create。

- [ ] **Step 4：在 `_reserve_initializing_run()` 中读取并写入快照**

在现有 `BEGIN IMMEDIATE` 事务内、插入 run 前：

```python
conn.execute("insert or ignore into user_settings (user_id) values (?)", (user_id,))
settings = conn.execute(
    """
    select governance_profile, context_strategy, max_steps,
           context_budget_chars, retrieval_top_k, retrieval_budget_chars,
           compression_max_tool_result_chars
    from user_settings where user_id = ?
    """,
    (user_id,),
).fetchone()
runtime_config = RunRuntimeConfig.from_settings(dict(settings))
```

插入语句改为：

```sql
insert into runs (
    project_id, user_id, status, prompt, created_at, runtime_config_json
)
values (?, ?, ?, ?, ?, ?)
```

写入 `runtime_config.to_json()`。后续初始化、清理和 quota guard 不改顺序。

- [ ] **Step 5：运行 run 创建与并发回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_runs
```

Expected: PASS。

- [ ] **Step 6：由用户提交 Task 4**

```powershell
git add src/specgate/web_runs.py tests/test_web_runs.py
git commit -m "feat: 创建 run 时冻结运行配置"
```

## Task 5：把预算接入 Context、Retrieval 和 Compression

**Files:**

- Modify: `src/specgate/context.py`
- Modify: `tests/test_context.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1：写 Context 配置效果失败测试**

扩展 `tests/test_context.py`，构造包含任务文件、多个普通文本文件和长 runtime feedback 的 workspace：

```python
context, metadata = build_context_pack_with_metadata(
    root,
    None,
    runtime_feedback=events,
    strategy="compressed-rag",
    context_budget_chars=1000,
    retrieval_config=RetrievalConfig(top_k=1, budget_chars=500),
    compression_config=CompressionConfig(max_tool_result_chars=100),
)
self.assertIn("budget_chars: 1000", context)
self.assertEqual(metadata["retrieval"]["budget_chars"], 500)
self.assertLessEqual(len(metadata["retrieval"]["selected_chunks"]), 1)
self.assertGreaterEqual(metadata["compression"]["cleared_tool_results"], 1)
self.assertIn("## Policy Boundary", context)
self.assertIn("## Latest Gate Feedback", context)
```

再调用 `build_role_context_pack_with_metadata()`，断言相同检索和压缩配置进入角色 metadata。

- [ ] **Step 2：运行 Context 测试确认 RED**

Run:

```powershell
python -m unittest tests.test_context
```

Expected: ERROR because context builders do not accept the new keyword arguments。

- [ ] **Step 3：扩展 Context 函数签名并传递配置**

修改签名：

```python
def build_context_pack_with_metadata(
    root: Path,
    latest_gate: GateResult | None,
    runtime_feedback: list[dict] | None = None,
    strategy: str = "baseline",
    policy: WorkspacePolicy | None = None,
    *,
    context_budget_chars: int = 12000,
    retrieval_config: RetrievalConfig | None = None,
    compression_config: CompressionConfig | None = None,
) -> tuple[str, dict]:
```

内部使用：

```python
selection = select_context_files(
    root,
    budget_chars=context_budget_chars,
    allowed_read_paths=policy.allowed_read_paths if policy is not None else None,
)
resolved_retrieval = retrieval_config or RetrievalConfig()
resolved_compression = compression_config or CompressionConfig()
```

`_render_retrieved_context()` 接收 `resolved_retrieval`，不得再创建默认 `RetrievalConfig()`。所有 `compress_runtime_feedback()` 调用使用 `resolved_compression`。

`build_context_pack()` 和 `build_role_context_pack_with_metadata()` 增加相同 keyword-only 参数并原样下传。`build_role_context_pack()` 若存在同样扩展。

- [ ] **Step 4：验证预算不会绕过读取策略**

扩展既有 policy-disallowed 测试，用高预算和高 top-k 调用，仍断言被禁止文件不进入 context 或 retrieval evidence。

- [ ] **Step 5：运行 Context 与安全回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_context tests.test_runner.RunnerTests.test_rag_select_does_not_inject_policy_disallowed_read_files tests.test_runner.RunnerTests.test_compressed_rag_does_not_pin_policy_disallowed_task_spec
```

Expected: PASS。

- [ ] **Step 6：由用户提交 Task 5**

```powershell
git add src/specgate/context.py tests/test_context.py tests/test_runner.py
git commit -m "feat: 接通上下文检索与压缩预算"
```

## Task 6：让 AgentRunner 使用显式预算配置

**Files:**

- Modify: `src/specgate/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1：写 Runner 参数传递失败测试**

在 `RunnerContextStrategyTests` patch 普通 context builder：

```python
retrieval = RetrievalConfig(top_k=2, budget_chars=700)
compression = CompressionConfig(max_tool_result_chars=150)
with patch(
    "specgate.runner.build_context_pack_with_metadata",
    return_value=("context", {"retrieval": None, "compression": None, "isolation": None}),
) as builder:
    runner = AgentRunner(
        root,
        llm,
        policy,
        max_steps=1,
        context_strategy="compressed-rag",
        context_budget_chars=1400,
        retrieval_config=retrieval,
        compression_config=compression,
    )
    runner.run()

self.assertEqual(builder.call_args.kwargs["context_budget_chars"], 1400)
self.assertIs(builder.call_args.kwargs["retrieval_config"], retrieval)
self.assertIs(builder.call_args.kwargs["compression_config"], compression)
```

为 `multi-agent-isolated` patch `build_role_context_pack_with_metadata`，断言三项配置同样传递。

- [ ] **Step 2：运行 Runner 配置测试确认 RED**

Run:

```powershell
python -m unittest tests.test_runner.RunnerContextStrategyTests
```

Expected: ERROR because `AgentRunner.__init__()` does not accept these arguments。

- [ ] **Step 3：扩展 AgentRunner 并传递配置**

在构造器加入：

```python
context_budget_chars: int = 12000,
retrieval_config: RetrievalConfig | None = None,
compression_config: CompressionConfig | None = None,
```

保存：

```python
self.context_budget_chars = context_budget_chars
self.retrieval_config = retrieval_config or RetrievalConfig()
self.compression_config = compression_config or CompressionConfig()
```

普通循环和多角色循环调用 context builder 时统一传：

```python
context_budget_chars=self.context_budget_chars,
retrieval_config=self.retrieval_config,
compression_config=self.compression_config,
```

不改变 CLI/eval 现有调用默认行为。

- [ ] **Step 4：写 max steps 和预算 evidence 的行为测试**

使用确定性 MockLLM：

- `max_steps=1` 时只调用一次并产生 `max_steps_reached`；
- `max_steps=3` 时允许第三步 finish；
- `retrieval_top_k=1` 的 evidence 最多一条；
- 较小压缩阈值产生更多 cleared/summarized evidence。

复用现有 runner fixture 和临时 workspace，不调用真实模型。

- [ ] **Step 5：运行完整 Runner 回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_runner
```

Expected: PASS。

- [ ] **Step 6：由用户提交 Task 6**

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: 让 Runner 使用显式运行预算"
```

## Task 7：首次执行和 HITL resume 使用同一快照

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_approvals.py`

- [ ] **Step 1：写首次执行不读取最新 Settings 的失败测试**

创建 run 后更新用户 Settings，再 patch `_run_mock_agent` 捕获配置：

```python
observed = []
original_agent = web_runs._run_mock_agent

def capture_agent(paths, config, **kwargs):
    observed.append(config)
    return original_agent(paths, config, **kwargs)

with patch("specgate.web_runs._run_mock_agent", side_effect=capture_agent) as agent:
    execute_run_once(db_path, data_root, run["id"])

self.assertEqual(observed[0], RunRuntimeConfig.from_json(run["runtime_config_json"]))
self.assertNotEqual(observed[0].max_steps, get_runtime_settings(db_path, user["id"])["max_steps"])
```

fixture 的完成结果必须带当前 Gate artifact SHA-256，沿用现有 `_run_mock_agent` patch 测试的构造方式。

- [ ] **Step 2：写 resume 不读取最新 Settings 的失败测试**

创建 needs_approval run 并批准动作；更新 Settings；调用 `queue_run_resume()` 和 `resume_run_once()`。patch `_run_resume_agent`，断言收到创建时快照，Trace 最后一个 `runtime_config_applied` 的 phase 为 `resume` 且 config 相同。

- [ ] **Step 3：运行快照执行测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_execute_uses_created_runtime_snapshot tests.test_web_approvals.WebApprovalsTests.test_resume_uses_original_runtime_snapshot
```

Expected: FAIL because执行路径仍调用 `get_runtime_settings()`。

- [ ] **Step 4：重构 Web agent 入口为强类型配置**

新增：

```python
def _parse_run_runtime_config(run: sqlite3.Row) -> RunRuntimeConfig:
    raw = run["runtime_config_json"]
    if not isinstance(raw, str):
        raise RuntimeConfigError("runtime_config_json")
    return RunRuntimeConfig.from_json(raw)
```

`execute_run_once()` 和 `resume_run_once()` 在调用 agent 前解析 run 行，不再调用 `get_runtime_settings()`。

修改入口：

```python
def _run_mock_agent(
    paths: RunPaths,
    config: RunRuntimeConfig,
    *,
    review_existing_writes: bool = True,
    stop_check: Callable[[], None] | None = None,
) -> RunResult:
```

resume 入口使用相同参数。构造 Runner：

```python
retrieval = RetrievalConfig(
    top_k=config.retrieval_top_k,
    budget_chars=config.retrieval_budget_chars,
)
compression = CompressionConfig(
    max_tool_result_chars=config.compression_max_tool_result_chars,
)
workspace_config = WorkspaceConfig(
    policy=policy,
    governance=governance,
    context=ContextConfig(
        strategy=config.context_strategy,
        budget_chars=config.context_budget_chars,
    ),
)
runner = AgentRunner(
    paths.workspace,
    llm,
    workspace_config.policy,
    max_steps=config.max_steps,
    context_strategy=config.context_strategy,
    governance_config=workspace_config.governance,
    context_budget_chars=config.context_budget_chars,
    retrieval_config=retrieval,
    compression_config=compression,
    audit_dir=paths.audit,
    approval_queue_file=paths.approval_queue,
    reset_audit=reset_audit,
    stop_check=stop_check,
)
```

- [ ] **Step 5：记录验证后的 Trace 配置事件**

Runner 构造完成后、调用 run/resume 前：

```python
runner.trace.append(
    "runtime_config_applied",
    {"phase": phase, "config": config.to_dict()},
)
```

initial 的 trace 已由 Runner reset 后再追加；resume 使用 `reset_audit=False` 追加，不覆盖首次执行记录。

- [ ] **Step 6：让 `queue_run_resume()` 在改状态前验证快照**

读取 run 后立即调用 `_parse_run_runtime_config(run)`，再读取审批候选并开启状态更新事务。解析失败不得把 needs_approval 改为 queued。

- [ ] **Step 7：运行执行、审批和 Trace 回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_runs tests.test_web_approvals
```

Expected: PASS；旧“resume 使用当前 Settings”的测试改为不可变快照语义。

- [ ] **Step 8：由用户提交 Task 7**

```powershell
git add src/specgate/web_runs.py tests/test_web_runs.py tests/test_web_approvals.py
git commit -m "feat: 用不可变快照执行和恢复 run"
```

## Task 8：非法快照失败关闭并保持恢复一致性

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写首次执行非法快照失败测试**

把 queued run 的 JSON 改为 `{"schema_version":99}`，patch `_run_mock_agent`：

```python
execute_run_once(db_path, data_root, run["id"])
stored = get_run(db_path, user["id"], run["id"])
self.assertEqual(stored["status"], "failed")
self.assertEqual(stored["error_message"], "invalid_runtime_config")
agent.assert_not_called()
self.assertFalse(paths.index_artifact.exists())
self.assertFalse(paths.zip_artifact.exists())
```

- [ ] **Step 2：写 resume 非法快照保持 needs_approval 测试**

为已批准的 needs_approval run 写入损坏 JSON，POST `/api/runs/{id}/resume`，断言：

```python
self.assertEqual(response.status_code, 409)
self.assertEqual(response.json()["detail"]["code"], "invalid_runtime_config")
self.assertEqual(client.get(f"/api/runs/{run_id}").json()["run"]["status"], "needs_approval")
self.assertNotIn(run_id, app.state.runtime.scheduled_run_ids())
```

- [ ] **Step 3：写 queued 重启补入保留快照测试**

预置非默认快照和 queued run，启动 TestClient 触发 refill，patch执行入口捕获配置，断言捕获值与数据库 JSON 完全一致，Settings 当前值不同也不影响。

- [ ] **Step 4：运行失败关闭测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_invalid_runtime_snapshot_never_calls_agent tests.test_web_app.WebAppTests.test_resume_rejects_invalid_runtime_snapshot_without_scheduling
```

Expected: FAIL because错误仍被通用异常消息处理或 API 映射不稳定。

- [ ] **Step 5：实现稳定失败和 HTTP 409**

在 `execute_run_once()` 的异常处理内识别 `RuntimeConfigError`，使用固定 `invalid_runtime_config` 调用 `_mark_failed()`；不得使用原始 JSON 或详细解析异常。

在 resume API 捕获 `RuntimeConfigError`：

```python
raise HTTPException(
    status_code=409,
    detail={
        "code": exc.code,
        "message": "运行配置快照无效 / Invalid runtime configuration snapshot",
        "field": exc.field,
    },
) from exc
```

reservation 必须在抛出前 release。

- [ ] **Step 6：运行恢复、取消和发布组合回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_runtime tests.test_web_runs tests.test_web_approvals tests.test_web_app
```

Expected: PASS；非法快照不覆盖取消终态，不进入 publishing。

- [ ] **Step 7：由用户提交 Task 8**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 为非法 run 配置增加失败关闭"
```

## Task 9：在 Debug、Audit 和 Settings 页面展示实际配置

**Files:**

- Modify: `src/specgate/web_debug.py`
- Modify: `src/specgate/web_static/app.js`
- Modify: `tests/test_web_debug.py`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1：写 Debug 配置返回失败测试**

在 `tests/test_web_debug.py` 创建带非默认快照的 run：

```python
payload = build_run_debug(db_path, data_root, user_id, run_id)
self.assertEqual(payload["runtime_config"], config.to_dict())
self.assertIsNone(payload["runtime_config_error"])
```

损坏快照时：

```python
self.assertIsNone(payload["runtime_config"])
self.assertEqual(payload["runtime_config_error"], "invalid_runtime_config")
self.assertNotIn("raw-sentinel", json.dumps(payload, ensure_ascii=False))
```

- [ ] **Step 2：写前端 Settings 和 Audit 静态契约失败测试**

在 `tests/test_web_static.py` 断言 `app.js` 包含：

```python
for field in (
    "max_steps",
    "context_budget_chars",
    "retrieval_top_k",
    "retrieval_budget_chars",
    "compression_max_tool_result_chars",
):
    self.assertIn(field, app_js)
self.assertIn("设置只影响之后创建的运行", app_js)
self.assertIn("实际运行配置", app_js)
self.assertIn("runtime_config_error", app_js)
self.assertIn("runtime_config_applied", app_js)
```

同时断言每个 number input 的 min/max 与规格一致。

- [ ] **Step 3：运行 Debug/静态测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_debug tests.test_web_static
```

Expected: FAIL because Debug 和页面没有新字段。

- [ ] **Step 4：实现 Debug 安全解析**

`build_run_debug()` 在关闭数据库连接前读取 run JSON，连接外执行：

```python
try:
    runtime_config = RunRuntimeConfig.from_json(run["runtime_config_json"]).to_dict()
    runtime_config_error = None
except RuntimeConfigError:
    runtime_config = None
    runtime_config_error = "invalid_runtime_config"
```

返回顶层 `runtime_config` 和 `runtime_config_error`。不得把原始 JSON放入 payload。

- [ ] **Step 5：实现现有 Settings 卡片中的配置表单**

在 `renderSettingsDetail()` 动态创建 form：

- 两个 select 使用现有合法策略选项；
- 五个 number input 使用确定的 id、当前值、`min`、`max`、`step="1"`；
- submit listener 调用 `updateSettings`；
- 说明文字为“设置只影响之后创建的运行；已有运行继续使用创建时配置快照。”

扩展 `loadSettings()` 和 `updateSettings()` 读取/提交全部字段。提交数字使用 `Number(input.value)`；后端严格验证仍是最终边界。

- [ ] **Step 6：实现 Audit 实际配置表**

新增：

```javascript
function appendDefinitionRows(section, rows) {
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [String(value)]));
  }
  section.append(dl);
  return section;
}

function renderRuntimeConfig(debug) {
  const section = el("section", { className: "audit-section" });
  section.append(el("h3", {}, ["实际运行配置"]));
  if (debug.runtime_config_error) {
    section.append(el("p", { className: "message-line error" }, ["运行配置快照无效"]));
    return section;
  }
  const config = debug.runtime_config;
  if (!config) {
    section.append(el("p", { className: "muted" }, ["暂无运行配置"]));
    return section;
  }
  return appendDefinitionRows(section, [
    ["来源", config.source],
    ["Schema", config.schema_version],
    ["治理策略", config.governance_profile],
    ["上下文策略", config.context_strategy],
    ["最大步骤", config.max_steps],
    ["上下文预算", config.context_budget_chars],
    ["检索 Top-K", config.retrieval_top_k],
    ["检索预算", config.retrieval_budget_chars],
    ["压缩阈值", config.compression_max_tool_result_chars],
  ]);
}
```

把 Audit overview 的重复 dl 构建改用 `appendDefinitionRows()`，并让 `renderAuditDetail()` 在 overview 后插入 `renderRuntimeConfig(debug)`。

`auditRunStrategy()` 优先读 `debug.runtime_config`；只在缺失时回退 Trace。Trace 描述映射增加 `runtime_config_applied: "应用运行配置"`。

- [ ] **Step 7：运行 Debug、API 和前端回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_debug tests.test_web_static tests.test_web_app
```

Expected: PASS。

- [ ] **Step 8：由用户提交 Task 9**

```powershell
git add src/specgate/web_debug.py src/specgate/web_static/app.js tests/test_web_debug.py tests/test_web_static.py
git commit -m "feat: 展示实际 Runner 运行配置"
```

## Task 10：同步阶段文档并完成最终验证

**Files:**

- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/superpowers/plans/2026-07-15-runtime-config-wiring.md`
- Verify: all modified source and tests

- [ ] **Step 1：更新 README 配置说明**

在 WebUI 章节写清：

- 七项 Settings 和默认值；
- 合法范围；
- 配置只影响新 run；
- resume 和重启恢复使用创建时快照；
- Debug/Audit 可核对实际配置；
- Web 与验收继续只使用 MockLLM。

- [ ] **Step 2：更新 PLAN 和 AGENT_LOG**

`PLAN.md` 增加本阶段设计、计划、Task 1–10 状态和验证命令。`AGENT_LOG.md` 记录：

- 用户确认的七项配置、JSON 快照和迁移策略；
- 各 Task 的 RED 失败原因与 GREEN 结果；
- schema v4 迁移证据；
- Settings 并发与 resume 不可变证据；
- 非法快照失败关闭证据；
- 未使用真实 LLM、未派发 subagent、Git/PR 由用户执行。

- [ ] **Step 3：运行高风险聚焦测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runtime_config tests.test_web_db tests.test_web_settings tests.test_context tests.test_runner tests.test_web_runs tests.test_web_approvals tests.test_web_debug tests.test_web_app tests.test_web_static
```

Expected: PASS，无 failure/error。

- [ ] **Step 4：运行全量 MockLLM 测试**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: `OK (skipped=20)`，测试数大于本阶段基线。

- [ ] **Step 5：运行编译和差异检查**

Run:

```powershell
python -m compileall -q src tests
git diff --check
git status --short --branch
```

Expected:

- compileall 无输出且退出码 0；
- `git diff --check` 无空白错误；Windows LF→CRLF 提示不属于错误；
- 状态只包含本计划列出的源代码、测试和直接相关文档。

- [ ] **Step 6：核对设计验收矩阵**

逐项确认：

```text
强类型配置/范围/JSON          -> tests/test_runtime_config.py
schema v4/迁移/回滚           -> tests/test_web_db.py
Settings 严格 API/无副作用    -> tests/test_web_settings.py + tests/test_web_app.py
创建事务不可变快照            -> tests/test_web_runs.py
Context/Retrieval/Compression -> tests/test_context.py + tests/test_runner.py
首次执行/resume/重启一致性     -> tests/test_web_runs.py + tests/test_web_approvals.py
非法快照失败关闭              -> tests/test_web_runs.py + tests/test_web_app.py
Trace/Debug/Audit 一致性       -> tests/test_web_debug.py + tests/test_web_static.py
```

- [ ] **Step 7：由用户提交最终阶段材料**

```powershell
git add README.md PLAN.md AGENT_LOG.md `
  docs/superpowers/specs/2026-07-15-runtime-config-wiring-design.md `
  docs/superpowers/plans/2026-07-15-runtime-config-wiring.md
git commit -m "docs: 记录 Runner 配置接线与验证证据"
```

## 最终 PR 建议

全部实现和验证完成后，PR 标题使用：

```text
feat: 接通 Runner 运行配置
```

PR 正文必须根据最终实际测试数填写，并覆盖：schema v4、七项 Settings、原子 JSON 快照、首次执行/resume/重启一致性、Context/检索/压缩接线、非法快照失败关闭、Trace/Debug/Audit 证据和 MockLLM 边界。
