# Run 隔离与不可变审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个 Web run 使用独立 workspace、审计、审批与产物目录，并只在成功后更新项目当前版本。

**Architecture:** 新增 `RunPaths` 作为唯一目录边界；Web 创建 run 时快照项目 workspace，AgentRunner 接受显式 audit/approval 路径，执行完成后发布 run 专属 artifact，并通过可恢复的两阶段目录切换提升项目 workspace。

**Tech Stack:** Python 3.11+、SQLite、pathlib、shutil、unittest、FastAPI 现有服务层。

---

### Task 1: 建立 RunPaths 与 run workspace 生命周期

**Files:**
- Create: `src/specgate/run_storage.py`
- Modify: `src/specgate/web_projects.py`
- Test: `tests/test_run_storage.py`

- [ ] **Step 1: 写失败测试**

```python
def test_web_run_paths_are_scoped_by_run_id(self):
    project = project_paths(Path("data"), 2, 7)
    run = web_run_paths(project, 11)
    self.assertEqual(run.workspace, project.runs / "11" / "workspace")
    self.assertEqual(run.audit, project.runs / "11" / "audit")
    self.assertEqual(run.approval_queue, project.runs / "11" / "approvals" / "pending_approvals.json")

def test_initialize_run_storage_copies_project_workspace(self):
    (project.workspace / "index.html").write_text("v1", encoding="utf-8")
    run = initialize_run_storage(project, 11)
    self.assertEqual((run.workspace / "index.html").read_text(encoding="utf-8"), "v1")
```

- [ ] **Step 2: 运行测试并确认因模块/函数不存在而失败**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_run_storage -v`

- [ ] **Step 3: 最小实现 RunPaths 与初始化**

实现不可变 `RunPaths` 数据类、`web_run_paths()`、`initialize_run_storage()`、
`remove_run_storage()`。初始化使用临时目录，成功后改名为 `<run_id>`，目标已存在时拒绝。

- [ ] **Step 4: 增加提升成功与失败恢复测试并实现**

测试 `promote_run_workspace()` 更新项目 workspace、第二次 rename 失败时恢复旧内容、发布后备份部分
清理失败时保留完整新版本，以及下次调用能够恢复/清理上次中断状态。

- [ ] **Step 5: 运行测试**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_run_storage -v`
Expected: PASS

- [ ] **Step 6: 提交**

```powershell
git add src/specgate/run_storage.py src/specgate/web_projects.py tests/test_run_storage.py
git commit -m "Add run-scoped storage lifecycle"
```

### Task 2: 在事务中创建独立 run 并阻止同项目并发

**Files:**
- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_app.py`
- Test: `tests/test_web_runs.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: 写活动 run 冲突失败测试**

```python
first = create_run(db_path, project["id"], user["id"], "first", data_root=data_root)
with self.assertRaises(ActiveRunConflict):
    create_run(db_path, project["id"], user["id"], "second", data_root=data_root)
self.assertTrue(web_run_paths(paths, first["id"]).workspace.is_dir())
self.assertEqual(message_count(db_path, project["id"]), 1)
```

- [ ] **Step 2: 运行并确认 RED**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_web_runs -v`

- [ ] **Step 3: 实现事务与初始化**

为 `create_run` 增加 `data_root` 参数；使用 `BEGIN IMMEDIATE`，检查
`queued/running/needs_approval`，插入 run 后调用 `initialize_run_storage`，最后插入 message 并提交。
定义 `ActiveRunConflict(ValueError)`，Web API 将其映射为 HTTP 409。

- [ ] **Step 4: 增加不同项目可创建、初始化失败回滚测试**

通过 patch `initialize_run_storage` 抛错，断言 runs/messages 均无残留。

- [ ] **Step 5: 运行相关测试**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_web_runs tests.test_web_app -v`
Expected: PASS

- [ ] **Step 6: 提交**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "Create isolated web runs transactionally"
```

### Task 3: 让执行、artifact 与恢复使用 run 专属路径

**Files:**
- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `src/specgate/web_projects.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_web_runs.py`
- Test: `tests/test_web_approvals.py`

- [ ] **Step 1: 写 AgentRunner 显式路径失败测试**

构造 `audit_dir=root/'audit'` 和 `approval_queue_file=root/'approvals/queue.json'`，运行后断言
trace 与 queue 只出现在显式位置，`root/runs/latest` 不存在。

- [ ] **Step 2: 运行并确认 RED**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_runner -v`

- [ ] **Step 3: 最小扩展 AgentRunner**

构造函数增加可选 `audit_dir`、`approval_queue_file`；所有 trace/evidence/queue 读写改用实例字段；
未传入时保持原默认值。

- [ ] **Step 4: 改造 Web 执行与发布**

`execute_run_once` 与 `resume_run_once` 构造 `RunPaths`，Agent 在 `run_paths.workspace` 执行；
artifact 输出为 `run_paths.artifacts/index.html` 与 `result.zip`；completed 后调用
`promote_run_workspace`，其他状态不提升。

- [ ] **Step 5: 写不可变回归测试**

完成 run 1 后保存 artifact/trace 字节，创建并完成 run 2，断言 run 1 字节不变、数据库路径不同、
run 2 初始 workspace 包含 run 1 成功内容。

- [ ] **Step 6: 改造审批测试夹具与恢复**

所有 Web approval 测试通过 `web_run_paths(..., run_id).approval_queue` 写队列，验证两个 run 的
同名 approval 不串联。

- [ ] **Step 7: 运行相关测试**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_runner tests.test_web_runs tests.test_web_approvals -v`
Expected: PASS

- [ ] **Step 8: 提交**

```powershell
git add src/specgate/runner.py src/specgate/web_runs.py src/specgate/web_projects.py tests/test_runner.py tests/test_web_runs.py tests/test_web_approvals.py
git commit -m "Execute and resume runs in isolated storage"
```

### Task 4: 将 debug 和下载绑定到指定 run

**Files:**
- Modify: `src/specgate/web_debug.py`
- Modify: `src/specgate/web_app.py`
- Test: `tests/test_web_debug.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: 写两个 run 的 debug 隔离失败测试**

为两个 run 的 audit 写入不同 retrieval evidence，分别调用 `build_run_debug`，断言各自读取自己的
值且旧 run 不读取新 run 文件。

- [ ] **Step 2: 运行并确认 RED**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_web_debug -v`

- [ ] **Step 3: 实现 run 定位**

`build_run_debug` 通过 project/user/run 构造 `RunPaths`，从 `audit` 读取 trace/evidence；artifact
仍由数据库行确定。下载端点拒绝缺失或不属于 run 的路径。

- [ ] **Step 4: 运行专项与完整测试**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_web_debug tests.test_web_app -v`

Run: `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/web_debug.py src/specgate/web_app.py tests/test_web_debug.py tests/test_web_app.py
git commit -m "Read immutable audit data by run"
```
