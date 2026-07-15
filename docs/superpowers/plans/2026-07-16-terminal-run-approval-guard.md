# 终态运行审批保护实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留终态运行的历史审批记录，但禁止继续批准、拒绝或恢复，并在 Web UI 中禁用无效入口。

**Architecture:** 审批查询通过现有 `approvals -> runs` 关联公开 `run_status`，后端在写入审批队列前要求运行仍为 `needs_approval`。前端使用同一字段派生按钮可用性，不修改审批状态机，也不新增 SQLite 与审批文件之间的双写流程。

**Tech Stack:** Python 3.11、SQLite、FastAPI、原生 JavaScript、`unittest`

**Git 约束:** 暂存、提交、推送和 PR 均由用户执行，本计划不运行 Git 写操作。

---

### Task 1：用回归测试锁定终态审批行为

**Files:**

- Modify: `tests/test_web_approvals.py`
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1：为审批服务添加终态拒绝测试**

在 `tests/test_web_approvals.py` 中增加两个测试。它们使用现有 `add_web_approval(..., run_status="cancelled")`，分别调用批准与拒绝入口，并断言抛出 `ValueError("run is not waiting for approval")`。每个测试随后重新读取审批队列和 SQLite 行，断言 queue revision 仍为 `0`、queue status 仍为 `pending`、数据库 status 仍为 `pending`、`decided_at` 仍为 `None`。

同时把现有 `test_same_approval_id_is_isolated_from_terminal_run_in_same_project` 改为断言 completed run 的审批决定被拒绝，并确认同项目的新运行审批保持 `pending`。

- [ ] **Step 2：为公开 API 字段添加测试**

在 `test_list_web_approvals_only_lists_current_user` 中加入：

```python
self.assertEqual([row["run_status"] for row in approvals], ["needs_approval"])
```

在 `tests/test_web_app.py::test_stale_approval_revision_returns_409` 获取审批后加入：

```python
self.assertEqual(approvals[0]["run_status"], "needs_approval")
```

- [ ] **Step 3：为前端按钮保护添加静态测试**

在 `tests/test_web_static.py` 增加测试，要求 `app.js` 包含：

```javascript
const runIsWaitingForApproval = approval.run_status === "needs_approval";
approve.disabled = approval.status !== "pending" || !runIsWaitingForApproval;
deny.disabled = approval.status !== "pending" || !runIsWaitingForApproval;
resume.disabled = !runIsWaitingForApproval;
```

- [ ] **Step 4：运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_approvals tests.test_web_app tests.test_web_static -v
```

Expected: 新测试因缺少 `run_status`、终态审批仍可决定、前端没有运行状态保护而失败；失败原因不得是语法错误或测试夹具错误。

---

### Task 2：实现后端 fail-closed 校验

**Files:**

- Modify: `src/specgate/web_approvals.py`
- Modify: `src/specgate/web_app.py`

- [ ] **Step 1：在审批查询中携带运行状态**

将 `list_web_approvals()` 和 `_load_web_approval()` 的 SQL 投影改为：

```sql
select approvals.*, runs.status as run_status
```

保持现有用户、项目与 run 归属校验不变。

- [ ] **Step 2：在写审批队列前拒绝终态运行**

在 `_decide_web_approval()` 读取审批行之后、检查和写入审批队列之前加入：

```python
if row["run_status"] != "needs_approval":
    raise ValueError("run is not waiting for approval")
```

更新成功后的返回字典保留初次查询得到的公开字段：

```python
return {
    **dict(updated),
    "run_status": row["run_status"],
    "queue_revision": updated_queue.revision,
}
```

- [ ] **Step 3：通过 API 序列化公开运行状态**

在 `src/specgate/web_app.py::_approval_dict()` 返回值中加入：

```python
"run_status": data["run_status"],
```

不加入运行配置、凭据或内部路径字段。

- [ ] **Step 4：运行后端测试并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_approvals tests.test_web_app -v
```

Expected: 全部通过；Windows 符号链接权限相关 skip 可接受。

---

### Task 3：实现前端按钮保护并完成回归

**Files:**

- Modify: `src/specgate/web_static/app.js`
- Test: `tests/test_web_static.py`
- Test: `tests/test_web_approvals.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1：从 run_status 派生按钮可用性**

在 `renderApprovalsDetail()` 的每个审批项中创建：

```javascript
const runIsWaitingForApproval = approval.run_status === "needs_approval";
```

并设置：

```javascript
approve.disabled = approval.status !== "pending" || !runIsWaitingForApproval;
deny.disabled = approval.status !== "pending" || !runIsWaitingForApproval;
resume.disabled = !runIsWaitingForApproval;
```

事件处理器保留不变，后端仍是最终安全边界。

- [ ] **Step 2：运行针对性测试并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_approvals tests.test_web_app tests.test_web_static -v
node --check src/specgate/web_static/app.js
```

Expected: 所有测试通过，JavaScript 语法检查退出码为 0。

- [ ] **Step 3：运行相关完整回归与静态检查**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs tests.test_web_approvals tests.test_web_app tests.test_web_debug tests.test_web_static -v
python -m compileall -q src tests
git diff --check
git status --short --branch
```

Expected: 测试通过；Windows 符号链接权限相关 skip 可接受；编译和 diff 检查通过；Git 状态只包含用户已有改动、本补丁代码和审计文档。
