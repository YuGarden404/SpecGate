# Web 运行时并发与恢复加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为单进程 Web MockLLM 运行路径增加有界执行、用户级准入、协作式取消与超时、完整启动恢复和 SQLite 并发治理。

**Architecture:** 新增独立 `WebRuntimeCoordinator`，使用固定 worker、显式有界队列和每 run 控制信号统一管理首次执行与 HITL 恢复。Web 层先预留全局容量，再通过 SQLite 短事务检查用户与项目配额；Runner 只接收通用停止检查回调，取消、超时、恢复和终态持久化留在 Web 运行层。

**Tech Stack:** Python 3.11、FastAPI、SQLite、`threading.Condition` / `Event`、`unittest`、原生 JavaScript、MockLLM。

---

## 执行结果（2026-07-14）

以下汇总是最终完成状态；任务正文中的逐步复现命令保留为可重复执行清单。

- [x] Task 1：SQLite schema v3、WAL、`synchronous=NORMAL`、5 秒 busy timeout 与迁移回归。
- [x] Task 2–3：严格运行时配置、固定 worker、有界队列、容量预留、去重与 FIFO refill。
- [x] Task 4：Runner 首次执行、步骤、LLM、工具、Gate、HITL 和多角色停止边界。
- [x] Task 5：取消/超时终态、发布前停止检查、CAS 竞争与产物清理。
- [x] Task 6–8：全局/用户/项目准入、取消 API、异步 HITL resume 与结构化 429。
- [x] Task 9：`queued` 补入、`running`/`cancel_requested` 重启收敛及恢复顺序。
- [x] Task 10：两阶段主动关闭、数据库状态写入与统一 5 秒 join deadline。
- [x] Task 11：Web 取消按钮、持续轮询和完整中文状态映射。
- [x] Task 12：中文使用/部署材料、全量 MockLLM 验收和差异检查。

最终证据：高风险组合测试运行 247 个测试并通过，跳过 1 个既有平台场景；全量运行 799 个测试并通过，跳过 20 个既有平台权限场景。`python -m compileall -q src tests` 和 `git diff --check` 均退出码为 0。实施期间发现并修复一个 queued 双语义回归：只有带已决定审批候选的 queued run 才进入 resume，普通首次运行 queued 保持幂等无操作。

本轮未接入真实 LLM、未访问网络、未派发 subagent，也未执行 Git 暂存、提交、推送或 PR 操作。

## 实施约束

- 全程使用 MockLLM，不接真实 LLM，不访问外部网络。
- 严格执行 RED → GREEN → REFACTOR；每个行为先看到预期失败，再写最小实现。
- 不重复修改既有 ZIP、路径安全、Gate、HITL CAS、运行目录和发布恢复语义。
- Git 暂存、提交、推送和 PR 均由用户执行。计划中的提交步骤只提供命令，不由实现代理运行。
- 每完成一个 Task，先运行该 Task 的定向测试；最终再运行全量 754+ 测试。

## 文件职责映射

**新增：**

- `src/specgate/web_runtime.py`：运行时配置、容量预留、有界队列、worker、取消事件、deadline 与关闭协调。
- `tests/test_web_runtime.py`：配置、队列、并发、取消信号和关闭的确定性测试。

**修改：**

- `src/specgate/web_db.py`：schema v3、WAL、busy timeout 与 v2→v3 迁移。
- `src/specgate/runner.py`：注入通用 `stop_check`，在稳定步骤边界检查。
- `src/specgate/web_runs.py`：用户/项目准入、deadline 认领、取消/超时终态、resume 排队与启动恢复查询。
- `src/specgate/web_app.py`：构造协调器，接通 create/resume/cancel API 和 lifespan 恢复/关闭。
- `src/specgate/web_static/app.js`：取消按钮、轮询状态和中文映射。
- `tests/test_web_db.py`：schema 与 PRAGMA 测试。
- `tests/test_runner.py`：停止检查边界测试。
- `tests/test_web_runs.py`：准入、状态转换、恢复和发布前停止测试。
- `tests/test_web_app.py`：429、取消、resume、恢复和关闭集成测试。
- `tests/test_web_static.py`：取消 UI 与中文状态静态契约测试。
- `README.md`、`docs/DEPLOYMENT.md`、`PLAN.md`、`AGENT_LOG.md`：本阶段直接相关说明和验证证据。

## Task 1：记录基线并升级 SQLite schema v3

**Files:**

- Modify: `src/specgate/web_db.py`
- Modify: `tests/test_web_db.py`

- [ ] **Step 1：运行当前分支基线**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

Expected: `Ran 754 tests`，`OK (skipped=20)`。若数量因已合并测试变化，可接受更大的数量，但不得有 failure 或 error。

- [ ] **Step 2：写 schema v3 与连接 PRAGMA 的失败测试**

在 `tests/test_web_db.py` 增加：

```python
def test_new_database_uses_schema_version_three_and_runtime_columns(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"
        init_db(db_path)
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 3)
            columns = {
                row["name"]
                for row in conn.execute("pragma table_info(runs)").fetchall()
            }
        self.assertIn("cancel_requested_at", columns)
        self.assertIn("deadline_at", columns)

def test_connect_db_enables_runtime_concurrency_pragmas(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"
        init_db(db_path)
        with closing(connect_db(db_path)) as conn:
            self.assertEqual(conn.execute("pragma foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("pragma journal_mode").fetchone()[0], "wal")
            self.assertEqual(conn.execute("pragma synchronous").fetchone()[0], 1)
            self.assertEqual(conn.execute("pragma busy_timeout").fetchone()[0], 5000)
```

增加短写锁竞争测试：

```python
def test_short_writer_contention_completes_with_busy_timeout(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"
        init_db(db_path)
        first = connect_db(db_path)
        self.addCleanup(first.close)
        first.execute("begin immediate")
        first.execute(
            "insert into users (username, password_hash) values ('first', 'hash')"
        )
        attempting = threading.Event()
        result = []

        def second_writer():
            try:
                with closing(connect_db(db_path)) as conn:
                    attempting.set()
                    conn.execute(
                        "insert into users (username, password_hash) values ('second', 'hash')"
                    )
                    conn.commit()
                result.append("committed")
            except Exception as exc:
                result.append(type(exc).__name__)

        thread = threading.Thread(target=second_writer)
        thread.start()
        self.assertTrue(attempting.wait(timeout=1))
        first.commit()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["committed"])
```

同时在 `tests/test_web_db.py` 导入 `threading`。

v2 数据库迁移测试使用以下完整最小旧库：

```python
def test_version_two_migrates_runtime_columns_without_data_loss(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "web.sqlite3"
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                """
                create table runs (
                    id integer primary key,
                    status text not null,
                    prompt text not null
                );
                insert into runs (id, status, prompt) values (7, 'queued', 'legacy');
                pragma user_version = 2;
                """
            )
        init_db(db_path)
        with closing(connect_db(db_path)) as conn:
            row = conn.execute("select * from runs where id = 7").fetchone()
            self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 3)
        self.assertEqual(row["prompt"], "legacy")
        self.assertIsNone(row["cancel_requested_at"])
        self.assertIsNone(row["deadline_at"])
```

- [ ] **Step 3：运行定向测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_db.WebDbTests.test_new_database_uses_schema_version_three_and_runtime_columns tests.test_web_db.WebDbTests.test_connect_db_enables_runtime_concurrency_pragmas tests.test_web_db.WebDbTests.test_version_two_migrates_runtime_columns_without_data_loss
```

Expected: FAIL；当前版本仍为 2，且 `runs` 不含新列。

- [ ] **Step 4：实现 schema v3 与迁移**

在 `src/specgate/web_db.py` 将版本改为 3，在新库 `runs` 建表语句中加入两个可空列，并增加迁移：

```python
LATEST_SCHEMA_VERSION = 3


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma synchronous = normal")
    conn.execute("pragma busy_timeout = 5000")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _configure_connection(conn)
    return conn


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    conn.execute("begin immediate")
    try:
        conn.execute("alter table runs add column cancel_requested_at text")
        conn.execute("alter table runs add column deadline_at text")
        conn.execute("pragma user_version = 3")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

`SCHEMA` 中的 `runs` 列和末尾 `pragma user_version` 同步改为 v3。`init_db()` 在 version 2 时调用 `_migrate_v2_to_v3()`；version 1 先完成现有 v1→v2，再继续 v2→v3，不在中途返回。

- [ ] **Step 5：验证 GREEN 与旧迁移回归**

Run:

```powershell
python -m unittest tests.test_web_db
```

Expected: PASS；v1→v2→v3、直接 v2→v3、新库 v3、短锁竞争和未来版本失败关闭全部通过。

- [ ] **Step 6：由用户提交 Task 1**

```powershell
git add src/specgate/web_db.py tests/test_web_db.py
git commit -m "feat: 升级 Web 运行数据库并启用 WAL"
```

## Task 2：实现严格的 Web 运行时配置

**Files:**

- Create: `src/specgate/web_runtime.py`
- Create: `tests/test_web_runtime.py`

- [ ] **Step 1：写默认值、优先级和边界失败测试**

创建 `tests/test_web_runtime.py`，包含以下默认值、环境覆盖、非法输入和组合边界测试：

```python
import unittest
import threading
from time import monotonic

from specgate.web_runtime import WebRuntimeConfig, load_web_runtime_config


class WebRuntimeConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_documented(self):
        config = load_web_runtime_config({})
        self.assertEqual(config.worker_count, 4)
        self.assertEqual(config.queue_capacity, 32)
        self.assertEqual(config.max_active_runs_per_user, 4)
        self.assertEqual(config.run_timeout_seconds, 60)

    def test_environment_values_override_defaults(self):
        config = load_web_runtime_config(
            {
                "SPECGATE_WEB_WORKERS": "2",
                "SPECGATE_WEB_QUEUE_CAPACITY": "8",
                "SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER": "3",
                "SPECGATE_WEB_RUN_TIMEOUT_SECONDS": "120",
            }
        )
        self.assertEqual(config, WebRuntimeConfig(2, 8, 3, 120))

    def test_invalid_environment_value_fails_closed(self):
        for value in ("", "0", "1.5", "true", "17"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    load_web_runtime_config({"SPECGATE_WEB_WORKERS": value})

    def test_user_limit_cannot_exceed_total_runtime_capacity(self):
        with self.assertRaisesRegex(ValueError, "max_active_runs_per_user"):
            WebRuntimeConfig(1, 1, 3, 60)
```

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runtime.WebRuntimeConfigTests
```

Expected: ERROR，`specgate.web_runtime` 尚不存在。

- [ ] **Step 3：实现配置对象与严格解析**

在 `src/specgate/web_runtime.py` 增加：

```python
from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping


@dataclass(frozen=True)
class WebRuntimeConfig:
    worker_count: int = 4
    queue_capacity: int = 32
    max_active_runs_per_user: int = 4
    run_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        _require_range("worker_count", self.worker_count, 1, 16)
        _require_range("queue_capacity", self.queue_capacity, 1, 256)
        _require_range("max_active_runs_per_user", self.max_active_runs_per_user, 1, 32)
        _require_range("run_timeout_seconds", self.run_timeout_seconds, 1, 3600)
        if self.max_active_runs_per_user > self.worker_count + self.queue_capacity:
            raise ValueError("max_active_runs_per_user exceeds total runtime capacity")


def _require_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _parse_integer(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"{name} must be a decimal integer")
    return int(raw)


def load_web_runtime_config(source: Mapping[str, str] | None = None) -> WebRuntimeConfig:
    values = environ if source is None else source
    return WebRuntimeConfig(
        worker_count=_parse_integer(values, "SPECGATE_WEB_WORKERS", 4),
        queue_capacity=_parse_integer(values, "SPECGATE_WEB_QUEUE_CAPACITY", 32),
        max_active_runs_per_user=_parse_integer(
            values,
            "SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER",
            4,
        ),
        run_timeout_seconds=_parse_integer(values, "SPECGATE_WEB_RUN_TIMEOUT_SECONDS", 60),
    )
```

- [ ] **Step 4：运行配置测试，确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_runtime.WebRuntimeConfigTests
```

Expected: PASS。

- [ ] **Step 5：由用户提交 Task 2**

```powershell
git add src/specgate/web_runtime.py tests/test_web_runtime.py
git commit -m "feat: 增加 Web 运行时安全配置"
```

## Task 3：实现可预留、可移除的有界运行协调器

**Files:**

- Modify: `src/specgate/web_runtime.py`
- Modify: `tests/test_web_runtime.py`

- [ ] **Step 1：写 worker、队列、预留和去重失败测试**

在 `tests/test_web_runtime.py` 增加使用 `threading.Event` 和 barrier 的测试：

```python
def wait_until(predicate, timeout=1.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return predicate()


def make_blocked_runtime(release, *, workers, queue_capacity):
    def execute(task, control):
        release.wait(timeout=2)

    runtime = WebRuntimeCoordinator(
        WebRuntimeConfig(workers, queue_capacity, workers + queue_capacity, 60),
        execute,
    )
    runtime.start()
    return runtime


def test_coordinator_bounds_workers_and_pending_queue(self):
    release = threading.Event()
    started = []
    lock = threading.Lock()

    def execute(task, control):
        with lock:
            started.append(task.run_id)
        release.wait(timeout=2)

    runtime = WebRuntimeCoordinator(
        WebRuntimeConfig(2, 3, 5, 60),
        execute,
    )
    runtime.start()
    self.addCleanup(runtime.shutdown, 1.0)
    for run_id in range(1, 6):
        reservation = runtime.reserve()
        runtime.submit(reservation, RunTask(run_id, 1, False))

    self.assertTrue(wait_until(lambda: runtime.running_count == 2))
    self.assertEqual(runtime.pending_count, 3)
    with self.assertRaises(RuntimeCapacityExceeded) as raised:
        runtime.reserve()
    self.assertEqual(raised.exception.scope, "global")
    release.set()

def test_pending_run_can_be_removed_and_releases_capacity(self):
    release = threading.Event()
    runtime = make_blocked_runtime(release, workers=1, queue_capacity=1)
    first = runtime.reserve()
    runtime.submit(first, RunTask(1, 1, False))
    self.assertTrue(wait_until(lambda: runtime.running_count == 1))
    second = runtime.reserve()
    runtime.submit(second, RunTask(2, 1, False))
    self.assertTrue(runtime.discard_pending(2))
    replacement = runtime.reserve()
    runtime.submit(replacement, RunTask(3, 1, False))
    self.assertEqual(runtime.pending_run_ids(), (3,))
    release.set()

def test_same_run_cannot_be_submitted_twice(self):
    runtime = WebRuntimeCoordinator(WebRuntimeConfig(1, 1, 2, 60), lambda task, control: None)
    runtime.start()
    self.addCleanup(runtime.shutdown, 1.0)
    first = runtime.reserve()
    runtime.submit(first, RunTask(7, 1, False))
    second = runtime.reserve()
    with self.assertRaisesRegex(ValueError, "already scheduled"):
        runtime.submit(second, RunTask(7, 1, False))
    second.release()
```

测试辅助函数 `wait_until()` 使用最多 1 秒的单调 deadline 和 `Event.wait(0.01)`，不得使用固定长 sleep。

- [ ] **Step 2：运行协调器测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runtime.WebRuntimeCoordinatorTests
```

Expected: FAIL；协调器类型和方法尚未定义。

- [ ] **Step 3：实现公开任务、预留和控制类型**

在 `src/specgate/web_runtime.py` 增加以下稳定接口：

```python
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Condition, Event, Lock, Thread
from time import monotonic
from typing import Callable, Literal


class RuntimeCapacityExceeded(ValueError):
    code = "runtime_capacity_exceeded"

    def __init__(self, scope: str = "global") -> None:
        self.scope = scope
        super().__init__("Web 运行队列已满 / Web runtime capacity is full")


class RunCancelled(RuntimeError):
    pass


class RunTimedOut(RuntimeError):
    pass


@dataclass(frozen=True)
class RunTask:
    run_id: int
    user_id: int
    resume: bool


@dataclass
class RunControl:
    cancel_event: Event
    deadline_at: str
    deadline_monotonic: float
    monotonic_clock: Callable[[], float]

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise RunCancelled("运行已取消")
        if self.monotonic_clock() >= self.deadline_monotonic:
            raise RunTimedOut("运行已超时")


@dataclass(frozen=True)
class _QueuedTask:
    task: RunTask
    reservation_kind: Literal["worker", "queue"]


class RuntimeReservation:
    def __init__(self, coordinator: "WebRuntimeCoordinator", kind: Literal["worker", "queue"]):
        self._coordinator = coordinator
        self.kind = kind
        self._active = True
        self._run_id: int | None = None

    def bind(self, run_id: int) -> None:
        if not self._active:
            raise RuntimeError("runtime reservation is no longer active")
        self._coordinator._bind_reserved(self, run_id)
        self._run_id = run_id

    def submit(self, task: RunTask) -> None:
        if not self._active:
            raise RuntimeError("runtime reservation is no longer active")
        self._coordinator._submit_reserved(self, task)
        self._active = False

    def release(self) -> None:
        if not self._active:
            return
        self._coordinator._release_reserved(self)
        self._active = False
```

`RuntimeReservation` 只允许 `submit()` 或 `release()` 一次；析构不承担正确性，所有调用点必须在 `try/except` 中显式释放。

- [ ] **Step 4：实现协调器核心循环**

实现 `WebRuntimeCoordinator`，公开方法签名固定为：

```python
class WebRuntimeCoordinator:
    def __init__(
        self,
        config: WebRuntimeConfig,
        execute: Callable[[RunTask, RunControl], None],
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.config = config
        self._execute = execute
        self._monotonic = monotonic_clock
        self._utc_clock = utc_clock
        self._condition = Condition(Lock())
        self._pending: deque[_QueuedTask] = deque()
        self._controls: dict[int, RunControl] = {}
        self._reserved_run_ids: dict[int, RuntimeReservation] = {}
        self._threads: list[Thread] = []
        self._running = 0
        self._reserved_workers = 0
        self._queued_slots = 0
        self._accepting = True
        self._stopping = False

    def start(self) -> None:
        with self._condition:
            if self._threads:
                return
            self._threads = [
                Thread(target=self._worker, name=f"specgate-web-run-{index + 1}", daemon=True)
                for index in range(self.config.worker_count)
            ]
            threads = tuple(self._threads)
        for thread in threads:
            thread.start()

    def reserve(self) -> RuntimeReservation:
        with self._condition:
            if not self._accepting:
                raise RuntimeCapacityExceeded("shutdown")
            if self._running + self._reserved_workers < self.config.worker_count:
                self._reserved_workers += 1
                return RuntimeReservation(self, "worker")
            if self._queued_slots < self.config.queue_capacity:
                self._queued_slots += 1
                return RuntimeReservation(self, "queue")
            raise RuntimeCapacityExceeded("global")

    def submit(self, reservation: RuntimeReservation, task: RunTask) -> None:
        reservation.submit(task)

    def _submit_reserved(self, reservation: RuntimeReservation, task: RunTask) -> None:
        with self._condition:
            scheduled = (
                {item.task.run_id for item in self._pending}
                | set(self._controls)
                | set(self._reserved_run_ids)
            )
            if reservation._run_id is not None and reservation._run_id != task.run_id:
                raise ValueError("runtime reservation is bound to another run")
            if reservation._run_id == task.run_id:
                self._reserved_run_ids.pop(task.run_id, None)
                scheduled.discard(task.run_id)
            if task.run_id in scheduled:
                raise ValueError("run is already scheduled")
            self._pending.append(_QueuedTask(task, reservation.kind))
            self._condition.notify_all()

    def _bind_reserved(self, reservation: RuntimeReservation, run_id: int) -> None:
        with self._condition:
            scheduled = (
                {item.task.run_id for item in self._pending}
                | set(self._controls)
                | set(self._reserved_run_ids)
            )
            if run_id in scheduled:
                raise ValueError("run is already scheduled")
            self._reserved_run_ids[run_id] = reservation

    def _release_reserved(self, reservation: RuntimeReservation) -> None:
        with self._condition:
            if reservation._run_id is not None:
                self._reserved_run_ids.pop(reservation._run_id, None)
            self._release_kind(reservation.kind)
            self._condition.notify_all()

    def _release_kind(self, kind: Literal["worker", "queue"]) -> None:
        if kind == "worker":
            self._reserved_workers -= 1
        else:
            self._queued_slots -= 1
        if self._reserved_workers < 0 or self._queued_slots < 0:
            raise RuntimeError("runtime capacity accounting underflow")

    def discard_pending(self, run_id: int) -> bool:
        with self._condition:
            for index, item in enumerate(self._pending):
                if item.task.run_id == run_id:
                    del self._pending[index]
                    self._release_kind(item.reservation_kind)
                    self._condition.notify_all()
                    return True
            return False

    def signal_cancel(self, run_id: int) -> bool:
        with self._condition:
            control = self._controls.get(run_id)
            if control is None:
                return False
            control.cancel_event.set()
            return True

    def shutdown(self, timeout_seconds: float = 1.0) -> None:
        with self._condition:
            self._accepting = False
            self._stopping = True
            for item in self._pending:
                self._release_kind(item.reservation_kind)
            self._pending.clear()
            for control in self._controls.values():
                control.cancel_event.set()
            self._condition.notify_all()
        for thread in tuple(self._threads):
            thread.join(timeout=timeout_seconds)

    @property
    def running_count(self) -> int:
        with self._condition:
            return self._running

    @property
    def pending_count(self) -> int:
        with self._condition:
            return self._queued_slots

    def pending_run_ids(self) -> tuple[int, ...]:
        with self._condition:
            return tuple(item.task.run_id for item in self._pending)
```

`_worker()` 与任务选择逻辑实现为：

```python
def _take_runnable_locked(self) -> _QueuedTask | None:
    for index, item in enumerate(self._pending):
        if item.reservation_kind == "worker":
            del self._pending[index]
            self._reserved_workers -= 1
            self._running += 1
            return item
    if self._running + self._reserved_workers >= self.config.worker_count:
        return None
    for index, item in enumerate(self._pending):
        if item.reservation_kind == "queue":
            del self._pending[index]
            self._queued_slots -= 1
            self._running += 1
            return item
    return None


def _worker(self) -> None:
    while True:
        with self._condition:
            item = self._take_runnable_locked()
            while item is None:
                if self._stopping and not self._pending:
                    return
                self._condition.wait()
                item = self._take_runnable_locked()

            started_monotonic = self._monotonic()
            deadline_at = self._utc_clock() + timedelta(
                seconds=self.config.run_timeout_seconds
            )
            control = RunControl(
                cancel_event=Event(),
                deadline_at=deadline_at.isoformat(),
                deadline_monotonic=started_monotonic + self.config.run_timeout_seconds,
                monotonic_clock=self._monotonic,
            )
            self._controls[item.task.run_id] = control

        try:
            self._execute(item.task, control)
        except Exception:
            pass
        finally:
            with self._condition:
                self._controls.pop(item.task.run_id, None)
                self._running -= 1
                if self._running < 0:
                    raise RuntimeError("runtime running count underflow")
                self._condition.notify_all()
```

worker 捕获单个任务异常是为了保持线程存活；业务执行入口负责把异常安全落库，测试执行回调的裸异常只用于验证 worker 隔离。direct worker 预留优先于普通 queue 项；未提交的 worker 预留会暂时保留对应 worker 容量，保证后续 `submit()` 不会失败。deadline 在 worker 真正认领任务时创建，因此排队和初始化时间不计入超时。

- [ ] **Step 5：验证有界性、释放和异常隔离**

增加以下 worker 异常隔离测试，然后运行：

```python
def test_worker_survives_task_exception_and_releases_capacity(self):
    completed = threading.Event()

    def execute(task, control):
        if task.run_id == 1:
            raise RuntimeError("boom")
        completed.set()

    runtime = WebRuntimeCoordinator(WebRuntimeConfig(1, 1, 2, 60), execute)
    runtime.start()
    self.addCleanup(runtime.shutdown, 1.0)
    first = runtime.reserve()
    runtime.submit(first, RunTask(1, 1, False))
    self.assertTrue(wait_until(lambda: runtime.running_count == 0))
    second = runtime.reserve()
    runtime.submit(second, RunTask(2, 1, False))
    self.assertTrue(completed.wait(timeout=1))
```

```powershell
python -m unittest tests.test_web_runtime
```

Expected: PASS；最大 running 为 worker 数、最大逻辑 pending 为 queue capacity、异常后容量全部释放。

- [ ] **Step 6：由用户提交 Task 3**

```powershell
git add src/specgate/web_runtime.py tests/test_web_runtime.py
git commit -m "feat: 实现有界 Web 运行协调器"
```

## Task 4：为 AgentRunner 增加协作式停止检查

**Files:**

- Modify: `src/specgate/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1：写步骤边界停止测试**

在 `tests/test_runner.py` 增加本地异常和 checker：

```python
class TestStop(RuntimeError):
    pass


def test_stop_check_can_abort_before_first_llm_call(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("# Task", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        llm = RecordingLLM()
        policy = WorkspacePolicy(
            root,
            {"finish"},
            {"TASK_SPEC.md", "CHECKLIST.md"},
            set(),
        )

        def stop_check():
            raise TestStop("stop before llm")

        runner = AgentRunner(
            root,
            llm,
            policy,
            stop_check=stop_check,
        )
        with self.assertRaisesRegex(TestStop, "stop before llm"):
            runner.run()
        self.assertEqual(llm.contexts, [])
```

再增加两个明确边界测试：

- 工具 dispatcher 返回后 checker 抛出，断言没有下一次 LLM 调用；
- `resume_from_approval()` 在应用已批准动作之前 checker 抛出，断言目标文件没有变化。

- [ ] **Step 2：运行定向测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_runner.RunnerTests.test_stop_check_can_abort_before_first_llm_call tests.test_runner.RunnerTests.test_stop_check_aborts_after_tool_before_next_llm tests.test_runner.RunnerTests.test_resume_stop_check_aborts_before_approved_action
```

Expected: FAIL；`AgentRunner.__init__()` 尚不接受 `stop_check`。

- [ ] **Step 3：实现无 Web 依赖的停止接口**

在 `AgentRunner.__init__()` 增加：

```python
stop_check: Callable[[], None] | None = None,
```

保存并封装：

```python
self._stop_check = stop_check or (lambda: None)


def _check_stop(self) -> None:
    self._stop_check()
```

在以下稳定边界调用 `_check_stop()`：

```python
def run(self) -> RunResult:
    self._check_stop()
    if self.context_strategy == "multi-agent-isolated":
        return self._run_multi_agent_loop(reset_queue=True)
    return self._run_loop(reset_queue=True)
```

并在 `_run_loop()` 每一步构造 context 前、`llm.complete()` 后、`dispatcher.dispatch()` 后、每次 Gate 前后、返回 `_finish_result()` 前调用。`_run_multi_agent_loop()` 在每个角色开始和结束时调用；`resume_from_approval()` 在读取候选后、执行批准动作前、dispatcher 返回后以及重新进入 `_run_loop()` 前调用。

停止异常不得被 Runner 捕获或转换，必须原样传播给 Web 运行层。未传 `stop_check` 的 CLI、eval 和既有单测保持不变。

- [ ] **Step 4：运行 Runner 全量测试**

Run:

```powershell
python -m unittest tests.test_runner
```

Expected: PASS，既有 HITL、Gate、多角色和 MockLLM 测试全部通过。

- [ ] **Step 5：由用户提交 Task 4**

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: 为 Runner 增加协作式停止边界"
```

## Task 5：接通 deadline、取消和超时终态

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_runs.py`

- [ ] **Step 1：写认领 deadline 与终态失败测试**

在 `tests/test_web_runs.py` 增加：

```python
def test_execute_run_records_deadline_when_worker_claims_queue(self):
    db_path, data_root, user, project = self.make_context()
    run = create_run(db_path, project["id"], user["id"], "Build", data_root=data_root)
    with patch("specgate.web_runs._run_mock_agent", side_effect=RunTimedOut("运行已超时")):
        execute_run_once(
            db_path,
            data_root,
            run["id"],
            stop_check=lambda: None,
            deadline_at="2026-07-14T12:01:00+00:00",
        )
    updated = get_run(db_path, user["id"], run["id"])
    self.assertEqual(updated["status"], "timed_out")
    self.assertEqual(updated["deadline_at"], "2026-07-14T12:01:00+00:00")
    self.assertIsNotNone(updated["finished_at"])

def test_cancelled_execution_never_prepares_publication(self):
    db_path, data_root, user, project = self.make_context()
    run = create_run(db_path, project["id"], user["id"], "Build", data_root=data_root)
    with patch("specgate.web_runs._run_mock_agent", side_effect=RunCancelled("运行已取消")), patch(
        "specgate.web_runs._prepare_run_publication"
    ) as prepare:
        execute_run_once(db_path, data_root, run["id"], stop_check=lambda: None)
    prepare.assert_not_called()
    self.assertEqual(get_run(db_path, user["id"], run["id"])["status"], "cancelled")
```

再写“发布 CAS 与取消竞争时不被 `_mark_failed()` 覆盖”的测试：让 `_prepare_run_publication` 前把数据库状态改为 `cancel_requested` 并抛 `RunCancelled`，断言最终为 `cancelled`。

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_execute_run_records_deadline_when_worker_claims_queue tests.test_web_runs.WebRunsTests.test_cancelled_execution_never_prepares_publication tests.test_web_runs.WebRunsTests.test_publication_cancel_race_finishes_cancelled
```

Expected: FAIL；执行入口没有 stop/deadline 参数，也没有取消和超时终态。

- [ ] **Step 3：让首次执行和恢复执行接收控制参数**

修改签名：

```python
def execute_run_once(
    db_path: Path,
    data_root: Path,
    run_id: int,
    *,
    review_existing_writes: bool = True,
    stop_check: Callable[[], None] | None = None,
    deadline_at: str | None = None,
) -> None:
```

`resume_run_once()` 增加相同的 `stop_check` 和 `deadline_at` 关键字参数。默认 checker 是空函数，保持直接单测和非 Web 调用兼容。

`_mark_running()` 与 `_mark_resume_running()` 在条件更新中写入 `deadline_at`。`_run_mock_agent()` / `_run_resume_agent()` 把 checker 传给 `AgentRunner(stop_check=stop_check)`。

- [ ] **Step 4：增加专用停止终态写入**

在 `web_runs.py` 增加：

```python
def _mark_stopped(db_path: Path, run_id: int, *, status: str, error_message: str) -> None:
    if status not in {"cancelled", "timed_out"}:
        raise ValueError("invalid stopped run status")
    now = utc_now().isoformat()
    with closing(connect_db(db_path)) as conn:
        conn.execute("begin immediate")
        cursor = conn.execute(
            """
            update runs
            set status = ?, trust_level = 'failed', error_message = ?, finished_at = ?,
                index_artifact_path = null, zip_artifact_path = null,
                cancel_requested_at = case
                    when ? = 'cancelled' then coalesce(cancel_requested_at, ?)
                    else cancel_requested_at
                end
            where id = ? and status in ('running', 'cancel_requested')
            """,
            (status, error_message, now, status, now, run_id),
        )
        if cursor.rowcount == 1:
            conn.execute("delete from artifacts where run_id = ?", (run_id,))
            conn.execute(
                """
                update projects set last_run_status = ?, updated_at = ?
                where id = (select project_id from runs where id = ?)
                """,
                (status, now, run_id),
            )
        conn.commit()
```

在两条执行路径中分别捕获 `RunCancelled` 和 `RunTimedOut`，调用 `_mark_stopped()` 后返回。普通异常处理前再次调用 checker；如果此时收到停止异常，必须走 stopped 终态，不得调用 `_mark_failed()`。

- [ ] **Step 5：在发布前加入最后停止检查**

首次执行与恢复执行在以下位置调用 checker：Runner 前、Runner 返回后、生成 artifact 前、取得发布锁后、写 publication manifest 前、`_prepare_run_publication()` 前。`_prepare_run_publication()` 仍使用 `where status='running'` CAS；CAS 失败时读取当前状态，若为 `cancel_requested` 则抛 `RunCancelled`。

- [ ] **Step 6：运行 Web run 回归**

Run:

```powershell
python -m unittest tests.test_web_runs
```

Expected: PASS；既有 Gate 摘要绑定、workspace promotion 和 publishing 恢复测试不回归。

- [ ] **Step 7：由用户提交 Task 5**

```powershell
git add src/specgate/web_runs.py tests/test_web_runs.py
git commit -m "feat: 接通 Web 运行取消与超时终态"
```

## Task 6：实现每用户/每项目准入并接通新 run 调度

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写每用户和项目 429 失败测试**

在 `tests/test_web_runs.py` 增加：创建同一用户的多个项目，并预置活动状态。调用 `create_run(db_path, third_project_id, user_id, "Third", data_root=data_root, max_active_runs_per_user=2)` 时，第三个项目必须抛出 scope 为 `user` 的 `RunLimitExceeded`，且 run 行数与运行目录数量不变。项目已有任一活动状态时必须抛 scope 为 `project`；活动集合覆盖：

```python
ACTIVE_RUN_STATUSES = (
    "initializing",
    "queued",
    "running",
    "needs_approval",
    "cancel_requested",
    "publishing",
)
```

在 `tests/test_web_app.py` 把现有项目冲突断言从 409 改为稳定 429，并新增全局容量已满测试：注入 `WebRuntimeConfig(1, 1, 2, 60)`，让一个任务运行、一个任务排队，第三个请求断言：

```python
self.assertEqual(response.status_code, 429, response.text)
self.assertEqual(response.json()["detail"]["code"], "runtime_capacity_exceeded")
self.assertEqual(response.json()["detail"]["scope"], "global")
```

同时断言第三个项目没有新增 run 行、消息和 `runs/<id>` 目录。

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_create_run_rejects_user_active_limit_without_side_effects tests.test_web_runs.WebRunsTests.test_create_run_treats_cancel_requested_as_active tests.test_web_app.WebAppTests.test_post_run_returns_429_without_db_or_storage_when_runtime_is_full
```

Expected: FAIL；当前只有项目 409，且 Web 仍调用 `start_run_background()`。

- [ ] **Step 3：实现数据库级用户和项目配额**

在 `src/specgate/web_runs.py` 增加：

```python
ACTIVE_RUN_STATUSES_SQL = (
    "'initializing', 'queued', 'running', "
    "'needs_approval', 'cancel_requested', 'publishing'"
)


class RunLimitExceeded(ValueError):
    code = "run_limit_exceeded"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        messages = {
            "user": "当前用户的活动运行已达上限 / User active run limit reached",
            "project": "该项目已有进行中的运行 / This project already has an active run",
        }
        super().__init__(messages[scope])
```

`create_run()` 和 `_reserve_initializing_run()` 增加 `max_active_runs_per_user: int` 参数；`create_run()` 另增加 `on_reserved_run: Callable[[int], None] | None = None`。在现有 `BEGIN IMMEDIATE` 事务中，先验证项目所有权，再查询当前用户活动 run 数；达到上限抛 `RunLimitExceeded("user")`。随后查询当前项目活动 run；存在时抛 `RunLimitExceeded("project")`。两项检查都必须在 `run_quarantine_capacity_guard()`、插入 run 和创建目录之前完成。

`_reserve_initializing_run()` 返回 run ID 后、初始化运行目录前调用：

```python
if on_reserved_run is not None:
    on_reserved_run(run_id)
```

这会让协调器在 run 进入 `queued` 前就知道该 ID，避免启动恢复 refill 抢先提交同一个 run。

- [ ] **Step 4：在 create_app 构造唯一协调器**

修改 `create_app()` 签名：

```python
def create_app(
    data_root: Path | None = None,
    db_path: Path | None = None,
    secure_cookies: bool | None = None,
    credential_key: str | None = None,
    runtime_config: WebRuntimeConfig | None = None,
) -> FastAPI:
```

解析配置并创建执行回调：

```python
resolved_runtime_config = runtime_config or load_web_runtime_config()

def execute_runtime_task(task: RunTask, control: RunControl) -> None:
    if task.resume:
        resume_run_once(
            resolved_db_path,
            resolved_data_root,
            task.user_id,
            task.run_id,
            stop_check=control.check,
            deadline_at=control.deadline_at,
        )
    else:
        execute_run_once(
            resolved_db_path,
            resolved_data_root,
            task.run_id,
            stop_check=control.check,
            deadline_at=control.deadline_at,
        )

app.state.runtime_config = resolved_runtime_config
app.state.runtime = WebRuntimeCoordinator(resolved_runtime_config, execute_runtime_task)
```

在 lifespan 进入时调用 `app.state.runtime.start()`。删除 `run_threads`、`run_threads_lock` 和 `start_run_background` 的应用状态与导入。

- [ ] **Step 5：改造创建 run 路由为预留后提交**

路由核心固定为：

```python
reservation = app.state.runtime.reserve()
try:
    run = create_run(
        app.state.db_path,
        project_id,
        int(user["id"]),
        payload.prompt,
        data_root=app.state.data_root,
        max_active_runs_per_user=app.state.runtime_config.max_active_runs_per_user,
        on_reserved_run=reservation.bind,
    )
    app.state.runtime.submit(
        reservation,
        RunTask(int(run["id"]), int(user["id"]), False),
    )
except Exception:
    reservation.release()
    raise
```

`RuntimeCapacityExceeded` 和 `RunLimitExceeded` 映射为 HTTP 429：

```python
detail = {
    "code": exc.code,
    "scope": exc.scope,
    "message": str(exc),
}
```

若预留成功但 run 初始化失败，必须释放预留；若提交成功，reservation 已失效，重复 release 是安全空操作或明确拒绝，但不能减少两次容量。

- [ ] **Step 6：增加两个并发准入测试**

使用 `ThreadPoolExecutor(max_workers=2)` 和 barrier 同时请求：

- 同一用户、不同项目、用户上限为 1：只有一个 200，另一个 429 user；
- 同一项目两个请求：只有一个 200，另一个 429 project。

断言数据库最终只有一个 run，且没有 `sqlite3.OperationalError` 或静默覆盖。

- [ ] **Step 7：运行定向测试与 Web app 回归**

Run:

```powershell
python -m unittest tests.test_web_runs tests.test_web_app
```

Expected: PASS；旧 `start_run_background` 和线程列表测试已被协调器测试替换。

- [ ] **Step 8：由用户提交 Task 6**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 限制用户与项目活动运行"
```

## Task 7：实现取消服务与取消 API

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写排队、运行、审批和冲突取消失败测试**

在 `tests/test_web_runs.py` 增加状态表驱动测试：

```python
def test_cancel_run_transitions_supported_states(self):
    cases = {
        "queued": "cancelled",
        "running": "cancel_requested",
        "needs_approval": "cancelled",
        "cancel_requested": "cancel_requested",
    }
    for original, expected in cases.items():
        with self.subTest(original=original):
            db_path, data_root, user, project = self.make_context()
            run = create_run(db_path, project["id"], user["id"], "Build", data_root=data_root)
            with closing(connect_db(db_path)) as conn:
                conn.execute("update runs set status = ? where id = ?", (original, run["id"]))
                conn.commit()
            result = cancel_run(db_path, user["id"], run["id"])
            self.assertEqual(result["status"], expected)
```

另写 `publishing`、`completed`、`failed`、`cancelled`、`timed_out` 抛 `RunCancellationConflict`；其他用户访问统一 `run not found`。

在 `tests/test_web_app.py` 使用阻塞执行回调覆盖：

- 排队 run 取消后从协调器 pending 移除，永不执行；
- running 取消返回 `cancel_requested`，随后 worker checker 确认并变为 `cancelled`；
- publishing 返回 409；
- 他人取消返回与不存在相同的 404。

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_cancel_run_transitions_supported_states tests.test_web_app.WebAppTests.test_cancel_queued_run_removes_pending_work tests.test_web_app.WebAppTests.test_cancel_running_run_signals_worker
```

Expected: FAIL；取消服务和路由尚不存在。

- [ ] **Step 3：实现事务化取消服务**

在 `web_runs.py` 增加：

```python
class RunCancellationConflict(ValueError):
    code = "run_cancellation_conflict"


def cancel_run(db_path: Path, user_id: int, run_id: int) -> sqlite3.Row:
    now = utc_now().isoformat()
    with closing(connect_db(db_path)) as conn:
        conn.execute("begin immediate")
        run = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise ValueError("run not found")
        if run["status"] == "queued":
            target = "cancelled"
        elif run["status"] == "running":
            target = "cancel_requested"
        elif run["status"] == "needs_approval":
            target = "cancelled"
        elif run["status"] == "cancel_requested":
            conn.commit()
            return run
        else:
            raise RunCancellationConflict("run cannot be cancelled from current status")

        finished_at = now if target == "cancelled" else None
        cursor = conn.execute(
            """
            update runs
            set status = ?, cancel_requested_at = ?, finished_at = ?, error_message = ?,
                trust_level = case when ? = 'cancelled' then 'failed' else trust_level end,
                index_artifact_path = case when ? = 'cancelled' then null else index_artifact_path end,
                zip_artifact_path = case when ? = 'cancelled' then null else zip_artifact_path end
            where id = ? and user_id = ? and status = ?
            """,
            (target, now, finished_at, "运行已取消" if target == "cancelled" else None,
             target, target, target, run_id, user_id, run["status"]),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("run status changed during cancellation")
        if target == "cancelled":
            conn.execute("delete from artifacts where run_id = ?", (run_id,))
            conn.execute(
                """
                update projects set last_run_status = 'cancelled', updated_at = ?
                where id = (select project_id from runs where id = ?)
                """,
                (now, run_id),
            )
        updated = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        conn.commit()
        return updated
```

将上面竞争分支改为有界重读：事务回滚后只重新读取一次并重新判定，不使用递归或无界循环。测试必须模拟一次 CAS 失败并确认函数有界结束。

- [ ] **Step 4：实现取消路由与协调器联动**

在 `web_app.py` 增加：

```python
@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
    try:
        run = cancel_run(app.state.db_path, int(user["id"]), run_id)
    except RunCancellationConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise _http_error_for_value_error(exc) from exc

    if run["status"] == "cancelled":
        app.state.runtime.discard_pending(run_id)
    elif run["status"] == "cancel_requested":
        app.state.runtime.signal_cancel(run_id)
    return {"run": _run_dict(run)}
```

`_run_dict()` 暴露 `cancel_requested_at` 和 `deadline_at`，但继续隐藏 `project_id` 与文件系统路径。

- [ ] **Step 5：验证取消 API 和竞争路径**

Run:

```powershell
python -m unittest tests.test_web_runs tests.test_web_app
```

Expected: PASS；取消后容量可复用，且取消/发布竞争不会把 `publishing` 覆盖成 cancelled。

- [ ] **Step 6：由用户提交 Task 7**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 增加 Web 运行取消接口"
```

## Task 8：把 HITL resume 改为有界排队执行

**Files:**

- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写 resume 不阻塞 HTTP 且受容量限制的失败测试**

在 `tests/test_web_app.py` 建立 `needs_approval` run 和已批准审批队列，patch `resume_run_once` 为阻塞函数。调用 `/api/runs/{id}/resume` 后应立即返回 `queued`，且阻塞工作在协调器 worker 中执行，不占用请求线程。

再填满 runtime，调用 resume 断言：

```python
self.assertEqual(response.status_code, 429)
self.assertEqual(response.json()["detail"]["scope"], "global")
self.assertEqual(client.get(f"/api/runs/{run_id}").json()["run"]["status"], "needs_approval")
```

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_app.WebAppTests.test_resume_is_queued_on_bounded_runtime tests.test_web_app.WebAppTests.test_resume_capacity_failure_preserves_needs_approval
```

Expected: FAIL；当前 resume 在 HTTP 请求内同步执行。

- [ ] **Step 3：增加 resume 排队事务**

在 `web_runs.py` 增加：

```python
def queue_run_resume(db_path: Path, data_root: Path, user_id: int, run_id: int) -> sqlite3.Row:
    run = get_run(db_path, user_id, run_id)
    if run["status"] != "needs_approval":
        raise ValueError("run is not waiting for approval")
    project = _load_project(db_path, int(run["project_id"]), user_id)
    paths = web_run_paths(project_paths(data_root, user_id, int(project["id"])), run_id)
    if ApprovalQueue.read(paths.approval_queue).next_resume_candidate() is None:
        raise ValueError("no approved or denied approval to resume")
    with closing(connect_db(db_path)) as conn:
        conn.execute("begin immediate")
        cursor = conn.execute(
            """
            update runs set status = 'queued', deadline_at = null, finished_at = null
            where id = ? and user_id = ? and status = 'needs_approval'
            """,
            (run_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("run is no longer waiting for approval")
        queued = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        conn.commit()
        return queued
```

修改 `resume_run_once()`：输入 run 必须为 `queued`，确认独立审批队列存在 resume candidate，再通过带 deadline 的 `queued -> running` CAS 认领。不要再次执行 `needs_approval -> running`。

- [ ] **Step 4：改造 resume 路由**

路由先 reserve，立即执行 `reservation.bind(run_id)`，再调用 `queue_run_resume()`，成功后提交：

```python
app.state.runtime.submit(
    reservation,
    RunTask(run_id, int(user["id"]), True),
)
```

任一步失败都释放 reservation；审批 approve / deny 路由保持只记录决定，不自动恢复。

- [ ] **Step 5：验证 resume、审批与取消组合**

Run:

```powershell
python -m unittest tests.test_web_approvals tests.test_web_runs tests.test_web_app
```

Expected: PASS；审批 CAS 不回归，resume 后仍只应用批准动作一次。

- [ ] **Step 6：由用户提交 Task 8**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 将 HITL 恢复接入有界调度"
```

## Task 9：实现非终态启动恢复与旧 queued 补入

**Files:**

- Modify: `src/specgate/web_runtime.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runtime.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写每种状态的恢复失败测试**

在 `tests/test_web_runs.py` 预置状态并调用新恢复函数，断言：

```python
expected = {
    "queued": "queued",
    "running": "failed",
    "cancel_requested": "cancelled",
    "needs_approval": "needs_approval",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "timed_out": "timed_out",
}
```

`running` 的 `error_message` 必须是稳定的“进程重启中断”，并写 `finished_at`；`cancel_requested` 保留 `cancel_requested_at` 并写 `finished_at`。`initializing` 和 `publishing` 继续由既有专用恢复测试覆盖。

再创建一个带已决定审批候选的 `queued` run，断言 `queued_run_task()` 返回 `RunTask(run_id, user_id, True)`；空审批队列返回 `RunTask(run_id, user_id, False)`。

- [ ] **Step 2：运行测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs.WebRunsTests.test_recover_interrupted_runtime_states tests.test_web_runs.WebRunsTests.test_queued_task_mode_is_inferred_from_approval_queue
```

Expected: FAIL；当前只恢复 initializing 和 publishing。

- [ ] **Step 3：实现状态恢复和稳定 queued 查询**

在 `web_runs.py` 增加：

```python
def recover_interrupted_runtime_states(db_path: Path) -> None:
    now = utc_now().isoformat()
    with closing(connect_db(db_path)) as conn:
        conn.execute("begin immediate")
        interrupted = conn.execute(
            "select id, project_id from runs where status = 'running'"
        ).fetchall()
        cancelled = conn.execute(
            "select id, project_id from runs where status = 'cancel_requested'"
        ).fetchall()
        conn.execute(
            """
            update runs set status = 'failed', trust_level = 'failed',
                error_message = '进程重启中断', finished_at = ?,
                index_artifact_path = null, zip_artifact_path = null
            where status = 'running'
            """,
            (now,),
        )
        conn.execute(
            """
            update runs set status = 'cancelled', trust_level = 'failed',
                error_message = '运行已取消', finished_at = ?,
                index_artifact_path = null, zip_artifact_path = null
            where status = 'cancel_requested'
            """,
            (now,),
        )
        for row in interrupted:
            conn.execute("delete from artifacts where run_id = ?", (row["id"],))
            conn.execute(
                "update projects set last_run_status = 'failed', updated_at = ? where id = ?",
                (now, row["project_id"]),
            )
        for row in cancelled:
            conn.execute("delete from artifacts where run_id = ?", (row["id"],))
            conn.execute(
                "update projects set last_run_status = 'cancelled', updated_at = ? where id = ?",
                (now, row["project_id"]),
            )
        conn.commit()
```

增加 `list_queued_runs(db_path)`，按 `created_at asc, id asc` 返回；增加 `queued_run_task(data_root, row)`，读取该 run 独立审批队列并根据 `next_resume_candidate()` 决定 `resume`。

- [ ] **Step 4：为协调器增加串行 refill provider**

协调器增加：

```python
def set_refill_provider(self, provider: Callable[[set[int]], RunTask | None]) -> None:
    self._refill_provider = provider

def refill(self) -> None:
    self._refill()

def scheduled_run_ids(self) -> set[int]:
    with self._condition:
        pending = {item.task.run_id for item in self._pending}
        return pending | set(self._controls) | set(self._reserved_run_ids)

def _refill(self) -> None:
    provider = self._refill_provider
    if provider is None or self._stopping:
        return
    if not self._refill_lock.acquire(blocking=False):
        return
    try:
        while True:
            try:
                reservation = self.reserve()
            except RuntimeCapacityExceeded:
                return
            task = provider(self.scheduled_run_ids())
            if task is None:
                reservation.release()
                return
            try:
                reservation.bind(task.run_id)
                self.submit(reservation, task)
            except Exception:
                reservation.release()
                raise
    finally:
        self._refill_lock.release()
```

在 `__init__()` 中初始化：

```python
self._refill_provider: Callable[[set[int]], RunTask | None] | None = None
self._refill_lock = Lock()
```

worker 每次释放运行容量后在条件变量锁外调用 `_refill()`。多个 worker 同时完成时只能有一个 refill 查询数据库。

在 `tests/test_web_runtime.py` 用 provider 依次返回 5 个 task，配置为 1 worker + 1 queue，断言任一时刻 pending 不超过 1，最终 5 个全部按顺序执行。

- [ ] **Step 5：在应用启动前执行恢复并安装 provider**

`create_app()` 初始化数据库后的顺序固定为：

```python
recover_interrupted_run_initializations(resolved_db_path, resolved_data_root)
recover_interrupted_runtime_states(resolved_db_path)
recover_interrupted_run_publications(resolved_db_path, resolved_data_root)
```

provider 实现为：

```python
def refill_provider(scheduled_run_ids: set[int]) -> RunTask | None:
    for row in list_queued_runs(resolved_db_path):
        if int(row["id"]) not in scheduled_run_ids:
            return queued_run_task(resolved_data_root, row)
    return None

app.state.runtime.set_refill_provider(refill_provider)
```

lifespan 启动 runtime 后立即调用一次 `runtime.refill()`，再 `yield` 接收请求。

- [ ] **Step 6：写超过队列容量的启动恢复集成测试**

配置 1 worker + 2 queue，预置 6 个不同项目的 `queued` run，执行回调用 Event 控制。断言开始时最多 1 running + 2 pending，释放后 6 个最终都被认领；不存在重复 run ID，数据库顺序与 `created_at, id` 一致。

- [ ] **Step 7：运行恢复回归**

Run:

```powershell
python -m unittest tests.test_web_runtime tests.test_web_runs tests.test_web_app
```

Expected: PASS；initializing 与 publishing 原有恢复仍通过。

- [ ] **Step 8：由用户提交 Task 9**

```powershell
git add src/specgate/web_runtime.py src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runtime.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 完善 Web 运行启动恢复"
```

## Task 10：实现主动停止与统一关闭 deadline

**Files:**

- Modify: `src/specgate/web_runtime.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_runtime.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写关闭快照和单 deadline 失败测试**

测试建立 2 个 running 和 2 个 pending，调用 shutdown 后断言：

- 不再接受 reserve；
- pending IDs 全部返回给调用方并被清空；
- running controls 全部收到 cancel event；
- 两个 worker 的 join timeout 共享同一个 5 秒预算，例如假时钟 `[100.0, 101.0, 104.5]` 对应 `[4.0, 0.5]`，而不是 `[5.0, 5.0]`。

- [ ] **Step 2：运行关闭测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runtime.WebRuntimeCoordinatorTests.test_begin_shutdown_clears_pending_and_signals_running tests.test_web_runtime.WebRuntimeCoordinatorTests.test_join_uses_one_absolute_deadline
```

Expected: FAIL；协调器尚无完整关闭接口。

- [ ] **Step 3：实现两阶段关闭接口**

在协调器增加：

```python
@dataclass(frozen=True)
class RuntimeShutdownSnapshot:
    pending_run_ids: tuple[int, ...]
    running_run_ids: tuple[int, ...]


def begin_shutdown(self) -> RuntimeShutdownSnapshot:
    with self._condition:
        self._accepting = False
        self._stopping = True
        pending = tuple(item.task.run_id for item in self._pending)
        for item in self._pending:
            self._release_kind(item.reservation_kind)
        self._pending.clear()
        running = tuple(self._controls)
        for control in self._controls.values():
            control.cancel_event.set()
        self._condition.notify_all()
        return RuntimeShutdownSnapshot(pending, running)


def join(self, timeout_seconds: float = 5.0) -> None:
    deadline = self._monotonic() + timeout_seconds
    for thread in tuple(self._threads):
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)


def shutdown(self, timeout_seconds: float = 5.0) -> None:
    self.begin_shutdown()
    self.join(timeout_seconds)
```

`begin_shutdown()` 可重复调用但只返回尚未处理的 pending；不得重复减少计数。

- [ ] **Step 4：实现系统关闭状态写入**

在 `web_runs.py` 增加按 run ID 的系统关闭函数，不做用户所有权查询：

- pending `queued` 使用条件更新转为 `cancelled`，写 `finished_at` 和项目状态；
- running 使用条件更新转为 `cancel_requested`，写 `cancel_requested_at`；
- CAS 未命中只读取当前状态，不覆盖 `publishing` 或终态。

lifespan 退出顺序：

```python
snapshot = app.state.runtime.begin_shutdown()
for run_id in snapshot.pending_run_ids:
    cancel_queued_run_for_shutdown(app.state.db_path, run_id)
for run_id in snapshot.running_run_ids:
    request_running_cancel_for_shutdown(app.state.db_path, run_id)
app.state.runtime.join(5.0)
```

- [ ] **Step 5：替换旧线程关闭集成测试**

删除针对 `app.state.run_threads` 的旧断言，改为 patch runtime worker/thread，验证数据库 pending 最终 `cancelled`、running 先为 `cancel_requested`，以及 join 总预算不超过 5 秒。

- [ ] **Step 6：运行关闭与应用回归**

Run:

```powershell
python -m unittest tests.test_web_runtime tests.test_web_app
```

Expected: PASS；关闭不创建非 daemon 线程，不留下新的 queued 任务。

- [ ] **Step 7：由用户提交 Task 10**

```powershell
git add src/specgate/web_runtime.py src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runtime.py tests/test_web_app.py
git commit -m "feat: 加固 Web 运行安全关闭"
```

## Task 11：增加 Web 取消按钮和中文状态

**Files:**

- Modify: `src/specgate/web_static/app.js`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1：写静态页面契约失败测试**

在 `tests/test_web_static.py` 增加：

```python
def test_app_contains_run_cancel_action_and_runtime_status_labels(self):
    app_js = self.app_js()
    self.assertIn('`/api/runs/${run.id}/cancel`', app_js)
    self.assertIn('className: "cancel-run-button"', app_js)
    self.assertIn('cancel_requested: "正在取消"', app_js)
    self.assertIn('cancelled: "已取消"', app_js)
    self.assertIn('timed_out: "已超时"', app_js)
    self.assertIn('publishing: "发布中"', app_js)
    self.assertIn('["queued", "running", "cancel_requested"]', app_js)
```

- [ ] **Step 2：运行静态测试，确认 RED**

Run:

```powershell
python -m unittest tests.test_web_static.WebStaticTests.test_app_contains_run_cancel_action_and_runtime_status_labels
```

Expected: FAIL；当前没有取消动作和新增状态。

- [ ] **Step 3：实现取消按钮与请求函数**

在 `renderStatusDetail()` 中，当状态为 `queued`、`running` 或 `needs_approval` 时追加：

```javascript
const cancelButton = el(
  "button",
  { type: "button", className: "secondary cancel-run-button" },
  ["取消运行"],
);
cancelButton.addEventListener("click", () => cancelRun(run, cancelButton));
card.append(cancelButton);
```

增加：

```javascript
async function cancelRun(run, button) {
  button.disabled = true;
  try {
    const payload = await apiJson(`/api/runs/${run.id}/cancel`, { method: "POST" });
    state.currentRun = payload.run;
    setRunPill(state.currentRun.status);
    renderDetail();
    if (["queued", "running", "cancel_requested"].includes(state.currentRun.status)) {
      pollRun(state.currentRun.id);
    } else {
      clearPolling();
    }
    setMessage(state.currentRun.status === "cancel_requested" ? "正在取消运行。" : "运行已取消。");
  } catch (error) {
    button.disabled = false;
    setMessage(error.message, true);
  }
}
```

`refreshRun()` 的持续轮询集合改为 `queued`、`running`、`cancel_requested`；`needs_approval` 仍停止自动轮询并加载审批。

- [ ] **Step 4：补齐状态和危险样式映射**

`translateRunStatus()` 增加：

```javascript
cancel_requested: "正在取消",
cancelled: "已取消",
timed_out: "已超时",
publishing: "发布中",
initializing: "初始化中",
```

`setRunPill()` 对 `failed`、`cancelled`、`timed_out` 使用 danger，对 `needs_approval`、`cancel_requested` 使用 warning。

- [ ] **Step 5：运行静态测试**

Run:

```powershell
python -m unittest tests.test_web_static
```

Expected: PASS。

- [ ] **Step 6：由用户提交 Task 11**

```powershell
git add src/specgate/web_static/app.js tests/test_web_static.py
git commit -m "feat: 增加 Web 运行取消交互"
```

## Task 12：同步功能文档并完成全量验证

**Files:**

- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/superpowers/plans/2026-07-14-web-runtime-hardening.md`

- [ ] **Step 1：更新 README 的 Web 行为说明**

在 WebUI 章节明确写入：

- 默认 4 worker、32 排队、每用户 4 活动 run、每项目 1 活动 run；
- 运行超时默认 60 秒，排队和人工审批等待不计时；
- 取消是协作式的，阻塞步骤返回后才确认；
- WebUI 与自动验收仍只使用 MockLLM。

- [ ] **Step 2：更新部署文档**

在 `docs/DEPLOYMENT.md` 增加完整环境变量表：

```text
SPECGATE_WEB_WORKERS=4
SPECGATE_WEB_QUEUE_CAPACITY=32
SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER=4
SPECGATE_WEB_RUN_TIMEOUT_SECONDS=60
```

写清合法范围、非法值启动失败、单 Web 进程约束、SQLite WAL 和 5 秒 busy timeout。Docker 示例不增加多个 Uvicorn worker。

- [ ] **Step 3：更新计划与开发日志**

在 `PLAN.md` 标记本阶段完成项和验证命令；在 `AGENT_LOG.md` 记录：

- 设计选择与非目标；
- 每个 Task 的 RED 失败原因和 GREEN 测试结果；
- schema v3 迁移证据；
- 并发、取消、超时、恢复、关闭测试证据；
- 未派发 subagent，Git/PR 由用户执行；
- 真实 LLM 未启用。

- [ ] **Step 4：运行定向高风险测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runtime tests.test_web_db tests.test_runner tests.test_web_runs tests.test_web_approvals tests.test_web_app tests.test_web_static
```

Expected: PASS，无 failure/error。

- [ ] **Step 5：运行全量测试**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: `OK (skipped=20)`；测试数量大于基线 754。

- [ ] **Step 6：运行编译和差异检查**

Run:

```powershell
python -m compileall -q src tests
git diff --check
git status --short
```

Expected:

- compileall 无输出且退出码为 0；
- `git diff --check` 无错误；
- 只包含本计划列出的源码、测试和功能文档。

- [ ] **Step 7：核对设计验收矩阵**

逐项确认：

```text
有界 worker/queue -> tests/test_web_runtime.py
全局/用户/项目准入 -> tests/test_web_app.py + tests/test_web_runs.py
429 无副作用 -> tests/test_web_app.py
取消/超时不发布 -> tests/test_web_runs.py
queued/running/needs_approval/publishing 恢复 -> tests/test_web_runs.py + tests/test_web_app.py
schema v3/WAL/busy timeout -> tests/test_web_db.py
统一 5 秒关闭 deadline -> tests/test_web_runtime.py + tests/test_web_app.py
Web 取消按钮/中文状态 -> tests/test_web_static.py
```

- [ ] **Step 8：由用户提交最终文档与验证记录**

```powershell
git add README.md docs/DEPLOYMENT.md PLAN.md AGENT_LOG.md docs/superpowers/specs/2026-07-14-web-runtime-hardening-design.md docs/superpowers/plans/2026-07-14-web-runtime-hardening.md
git commit -m "docs: 记录 Web 运行时加固与验证证据"
```

## 最终 PR 建议

用户完成所有提交并再次确认全量测试后，可使用：

```text
feat: 加固 Web 运行时并发与恢复
```

PR 正文应覆盖：有界执行器、三级准入、取消/超时、启动恢复、SQLite WAL、Web 取消入口、MockLLM 边界及完整测试结果。具体 Markdown 在实现和最终验证完成后根据实际文件与测试数量生成，不预填未经验证的数据。
