# Workspace 真实路径边界加固实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用统一、跨平台、句柄绑定的安全文件系统 API 阻止 workspace 链接逃逸与校验后替换。

**Architecture:** `workspace_fs.py` 负责路径规范化、链接/reparse 检测、安全打开、扫描与复制；policy、tool、snapshot、RAG、Gate 和 Web 层只通过该模块访问受信任目录。

**Tech Stack:** Python 标准库 pathlib/os/stat/contextlib/ctypes、unittest、现有 FastAPI/SQLite。

---

### Task 1: 实现跨平台安全路径与安全 I/O 原语

**Files:**
- Create: `src/specgate/workspace_fs.py`
- Create: `tests/test_workspace_fs.py`

- [ ] **Step 1: 写路径规范化和链接拒绝失败测试**

```python
self.assertEqual(normalize_workspace_relative("docs/a.txt"), "docs/a.txt")
for value in ("", "../x", "/tmp/x", "C:/x", r"..\x"):
    with self.assertRaises(WorkspacePathError):
        normalize_workspace_relative(value)
```

创建文件/目录 symlink（平台不允许时 skip 真实创建并用 reparse mock 补充），断言
`read_workspace_text`、`write_workspace_text`、`iter_workspace_files` 拒绝。

- [ ] **Step 2: 运行并确认 RED**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_workspace_fs -v`

- [ ] **Step 3: 实现规范化、link-like 检测和同句柄读取**

POSIX 使用目录 fd 与 `O_NOFOLLOW`；Windows 使用逐级 reparse 检查、打开后最终句柄路径确认。
所有异常转换为带稳定 `rule_family` 的 `WorkspacePathError`。

- [ ] **Step 4: 实现安全写、扫描和复制**

写入在句柄验证后执行；扫描使用 `os.scandir(..., follow_symlinks=False)`；复制只处理普通文件/目录。

- [ ] **Step 5: 写祖先目录替换测试**

在打开路径的竞争窗口替换祖先目录，断言操作拒绝或仍读取原已打开对象，绝不读取外部 sentinel。

- [ ] **Step 6: 运行测试并提交**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_workspace_fs -v
git add src/specgate/workspace_fs.py tests/test_workspace_fs.py
git commit -m "Add safe workspace filesystem primitives"
```

### Task 2: 接入 Harness 工具、快照、审批与上下文

**Files:**
- Modify: `src/specgate/policy.py`
- Modify: `src/specgate/tools.py`
- Modify: `src/specgate/snapshot.py`
- Modify: `src/specgate/approvals.py`
- Modify: `src/specgate/context_selector.py`
- Modify: `src/specgate/retrieval.py`
- Test: `tests/test_policy.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_snapshot.py`
- Test: `tests/test_approvals.py`
- Test: `tests/test_context_strategy.py`
- Test: `tests/test_retrieval.py`

- [ ] **Step 1: 为每个调用点写链接逃逸失败测试并确认 RED**

分别证明 ToolDispatcher、FileSnapshot、approval target state、context selection 和 retrieval 当前会
读取外部 sentinel，然后把断言改为 blocked/skipped。

- [ ] **Step 2: 接入安全 API**

policy 复用规范化；tool 使用安全 read/write/list；snapshot/approval 使用安全状态摘要；context/RAG
使用安全扫描并在 evidence 中记录 `linked_path`/`reparse_point`。

- [ ] **Step 3: 验证 action 语义**

普通文件读写、snapshot write-after-update、RAG 排序与预算保持现有行为；路径安全拒绝进入 trace 的
permission decision，不能退化为普通工具失败。

- [ ] **Step 4: 运行并提交**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_policy tests.test_tools tests.test_snapshot tests.test_approvals tests.test_context_strategy tests.test_retrieval -v
git add src/specgate/policy.py src/specgate/tools.py src/specgate/snapshot.py src/specgate/approvals.py src/specgate/context_selector.py src/specgate/retrieval.py tests/test_policy.py tests/test_tools.py tests/test_snapshot.py tests/test_approvals.py tests/test_context_strategy.py tests/test_retrieval.py
git commit -m "Enforce safe paths across harness I/O"
```

### Task 3: 接入 Gate、Web audit/artifact、run 复制和 ZIP

**Files:**
- Modify: `src/specgate/gate.py`
- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/web_app.py`
- Modify: `src/specgate/web_debug.py`
- Modify: `src/specgate/run_storage.py`
- Modify: `src/specgate/web_projects.py`
- Test: `tests/test_gate.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_web_app.py`
- Test: `tests/test_web_debug.py`
- Test: `tests/test_run_storage.py`
- Test: `tests/test_web_projects.py`

- [ ] **Step 1: 写 Web audit/Gate/run copy/ZIP 链接失败测试并确认 RED**

覆盖 audit 目录链接、artifact 祖先交换、Gate index 链接、run 初始化/提升源链接和 Unix symlink ZIP
entry。外部 sentinel 内容不得出现在响应、trace 或目标 workspace。

- [ ] **Step 2: 删除 Web 局部路径校验并接入统一模块**

artifact 从安全打开的同一 fd/bytes 响应；debug evidence 安全读取；Gate 使用安全文本；run storage
使用安全复制；ZIP 在提取前检查外部属性中的链接模式。

- [ ] **Step 3: 运行专项与全量测试**

Run: `$env:PYTHONPATH='src'; python -m unittest tests.test_gate tests.test_runner tests.test_web_app tests.test_web_debug tests.test_run_storage tests.test_web_projects -v`

Run: `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`
Expected: 全部 PASS；仅平台无权限创建真实 symlink 的用例可有明确 skip，mock/reparse 测试仍必须通过。

- [ ] **Step 4: 提交**

```powershell
git add src/specgate/gate.py src/specgate/runner.py src/specgate/web_app.py src/specgate/web_debug.py src/specgate/run_storage.py src/specgate/web_projects.py tests/test_gate.py tests/test_runner.py tests/test_web_app.py tests/test_web_debug.py tests/test_run_storage.py tests/test_web_projects.py
git commit -m "Harden web and run storage path boundaries"
```
