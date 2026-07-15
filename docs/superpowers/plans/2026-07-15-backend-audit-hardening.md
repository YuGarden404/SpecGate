# SpecGate 后端审计加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Harness 自有产物路径逃逸、Provider 错误正文泄密、非法 UTF-8 崩溃和 Web 遗留无界线程入口，并同步最终交付证据。

**Architecture:** 复用并最小扩展 `workspace_fs`，把 Trace、Memory、Report 和 Runner evidence 重新接入统一的安全文件句柄边界；用户输入错误由 Tool/Gate 转换成结构化结果，基础设施路径错误继续 fail closed。Provider 异常只暴露 HTTP 状态，Web run 继续只由 `WebRuntimeCoordinator` 调度。

**Tech Stack:** Python 3.11、标准库 `unittest`、`urllib`、跨平台安全文件句柄、FastAPI Web runtime、原生 JavaScript。

**Git 约束:** Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作；全部实现与验证完成后，由用户按最终文件清单统一提交。

---

## 文件结构

- Modify: `src/specgate/workspace_fs.py` — 增加安全追加文本能力。
- Modify: `src/specgate/trace.py` — Trace reset/append 走安全文件层。
- Modify: `src/specgate/memory.py` — Memory 读写走安全文件层。
- Modify: `src/specgate/report.py` — 报告 evidence 读取、目录创建和 HTML 写入走安全文件层。
- Modify: `src/specgate/runner.py` — 安全创建 audit 目录并安全重置/写入 evidence。
- Modify: `src/specgate/tools.py` — 非法 UTF-8 转为结构化 ToolResult。
- Modify: `src/specgate/gate.py` — 非法 UTF-8 转为结构化 GateResult。
- Modify: `src/specgate/context.py` — artifact summary 使用安全读取并容忍非法编码。
- Modify: `src/specgate/llm.py` — HTTP 错误不读取响应正文。
- Modify: `src/specgate/cli.py` — Provider 错误展示边界统一脱敏。
- Modify: `src/specgate/web_runs.py` — 删除遗留逐任务线程入口。
- Modify: `src/specgate/web_debug.py` — 空 evidence 哨兵保持对外 `null` 语义。
- Modify: `tests/test_workspace_fs.py` — 安全追加的正常与攻击测试。
- Modify: `tests/test_context.py` — Trace 链接拒绝测试。
- Modify: `tests/test_memory.py` — Memory 链接拒绝测试。
- Modify: `tests/test_report.py` — 报告读写链接拒绝测试。
- Modify: `tests/test_runner.py` — Runner audit/evidence 与非法编码集成测试。
- Modify: `tests/test_tools.py` — 工具非法编码测试。
- Modify: `tests/test_gate.py` — Gate artifact/checklist 非法编码测试。
- Modify: `tests/test_llm.py` — 任意响应正文秘密哨兵测试。
- Modify: `tests/test_cli.py` — CLI Provider 异常脱敏测试。
- Modify: `tests/test_web_runtime.py` — Web 运行入口架构回归测试。
- Modify: `tests/test_web_debug.py` — 空 evidence 兼容性回归。
- Modify: `PLAN.md`、`AGENT_LOG.md`、`README.md`、`docs/DEPLOYMENT.md` — 中文状态与安全边界。
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md` — 最终材料事实同步。

### Task 1: 增加安全追加写入并迁移 Trace

**Files:**
- Modify: `src/specgate/workspace_fs.py`
- Modify: `src/specgate/trace.py`
- Test: `tests/test_workspace_fs.py`
- Test: `tests/test_context.py`

- [ ] **Step 1: 为安全追加写入增加失败测试**

在 `tests/test_workspace_fs.py` 的 import 列表加入 `append_workspace_text`，并在 `WorkspaceFileIOTests` 增加：

```python
def test_append_workspace_text_creates_and_extends_regular_file(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        append_workspace_text(root, "runs/latest/trace.jsonl", "first\n")
        append_workspace_text(root, "runs/latest/trace.jsonl", "second\n")

        self.assertEqual(
            read_workspace_text(root, "runs/latest/trace.jsonl"),
            "first\nsecond\n",
        )

def test_append_workspace_text_rejects_link_without_changing_external_file(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        external = Path(outside) / "sentinel.txt"
        external.write_text("EXTERNAL_APPEND_SENTINEL", encoding="utf-8")
        link = root / "trace.jsonl"
        try:
            link.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        with self.assertRaises(WorkspacePathError) as raised:
            append_workspace_text(root, "trace.jsonl", "attacker-controlled\n")

        self.assertIn(raised.exception.rule_family, {"linked_path", "reparse_point"})
        self.assertEqual(external.read_text(encoding="utf-8"), "EXTERNAL_APPEND_SENTINEL")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_workspace_fs.WorkspaceFileIOTests.test_append_workspace_text_creates_and_extends_regular_file tests.test_workspace_fs.WorkspaceFileIOTests.test_append_workspace_text_rejects_link_without_changing_external_file -v
```

Expected: FAIL/ImportError，原因是 `append_workspace_text` 尚不存在。

- [ ] **Step 3: 实现最小安全追加接口**

在 `src/specgate/workspace_fs.py` 的文本写入函数附近增加：

```python
def append_workspace_text(
    root: str | os.PathLike[str],
    relative: str,
    content: str,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> None:
    data = content.encode(encoding, errors)
    try:
        with open_workspace_file(root, relative, "update", create=True) as handle:
            handle.seek(0, os.SEEK_END)
            remaining = memoryview(data)
            while remaining:
                written = handle.write(remaining)
                if written is None or written <= 0 or written > len(remaining):
                    raise OSError("workspace append made no progress")
                remaining = remaining[written:]
    except WorkspacePathError:
        raise
    except OSError as exc:
        raise WorkspacePathError(
            f"workspace file could not be appended: {relative}",
            "path_race",
        ) from exc
```

- [ ] **Step 4: 运行安全追加测试并确认 GREEN**

Run:

```powershell
python -m unittest tests.test_workspace_fs.WorkspaceFileIOTests.test_append_workspace_text_creates_and_extends_regular_file tests.test_workspace_fs.WorkspaceFileIOTests.test_append_workspace_text_rejects_link_without_changing_external_file -v
```

Expected: PASS；无权限创建 symlink 的 Windows 环境只跳过真实 symlink 用例。

- [ ] **Step 5: 为 Trace 链接逃逸增加失败测试**

在 `tests/test_context.py` 增加 `WorkspacePathError` import，并加入：

```python
def test_trace_store_rejects_link_without_overwriting_external_file(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        external = Path(outside) / "trace.jsonl"
        external.write_text("EXTERNAL_TRACE_SENTINEL", encoding="utf-8")
        link = root / "trace.jsonl"
        try:
            link.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        with self.assertRaises(WorkspacePathError):
            TraceStore(link, reset=True)

        self.assertEqual(external.read_text(encoding="utf-8"), "EXTERNAL_TRACE_SENTINEL")
```

- [ ] **Step 6: 运行 Trace 测试并确认 RED**

Run:

```powershell
python -m unittest tests.test_context.ContextTests.test_trace_store_rejects_link_without_overwriting_external_file -v
```

Expected: FAIL；当前 `Path.write_text()` 会跟随链接并覆盖 sentinel。

- [ ] **Step 7: 迁移 TraceStore 到安全文件层**

在 `src/specgate/trace.py` 导入 `append_workspace_text`、`write_workspace_text`，并将实现改为：

```python
class TraceStore:
    def __init__(self, path: Path, reset: bool = False):
        self.path = path
        self.root = path.parent
        self.relative = path.name
        if reset:
            write_workspace_text(self.root, self.relative, "", encoding="utf-8")

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": redact(payload),
        }
        append_workspace_text(
            self.root,
            self.relative,
            json.dumps(event, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
```

不得保留 `mkdir()`、`Path.write_text()` 或 `Path.open("a")` 回退。

- [ ] **Step 8: 运行 Task 1 局部回归**

Run:

```powershell
python -m unittest tests.test_workspace_fs tests.test_context -v
```

Expected: PASS。

### Task 2: 迁移 Memory、Report 和 Runner 自有产物

**Files:**
- Modify: `src/specgate/memory.py`
- Modify: `src/specgate/report.py`
- Modify: `src/specgate/runner.py`
- Test: `tests/test_memory.py`
- Test: `tests/test_report.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 为 Memory 预置链接增加失败测试**

在 `tests/test_memory.py` 导入 `WorkspacePathError`，增加：

```python
def test_memory_rejects_link_without_overwriting_external_file(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        external = Path(outside) / "memory.json"
        external.write_text('{"runs": []}', encoding="utf-8")
        link = root / "memory.json"
        try:
            link.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        with self.assertRaises(WorkspacePathError):
            append_memory(root, True, 1, "done")

        self.assertEqual(external.read_text(encoding="utf-8"), '{"runs": []}')
```

- [ ] **Step 2: 为 Report 输出链接增加失败测试**

在 `tests/test_report.py` 使用既有 `WorkspacePathError`，增加：

```python
def test_generate_report_rejects_linked_reports_directory_without_external_write(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        external = Path(outside)
        sentinel = external / "index.html"
        sentinel.write_text("EXTERNAL_REPORT_SENTINEL", encoding="utf-8")
        try:
            (root / "reports").symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")

        with self.assertRaises(WorkspacePathError):
            generate_report(root, gate, 1)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "EXTERNAL_REPORT_SENTINEL")
```

同时增加 evidence 读取链接测试：

```python
def test_generate_report_rejects_linked_evidence_without_rendering_external_content(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        evidence_dir = root / "runs" / "latest"
        evidence_dir.mkdir(parents=True)
        external = Path(outside) / "retrieval.json"
        external.write_text(
            json.dumps(
                {
                    "query_terms": ["EXTERNAL_EVIDENCE_SENTINEL"],
                    "candidate_count": 0,
                    "selected_chunks": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            (evidence_dir / "retrieval.json").symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")

        with self.assertRaises(WorkspacePathError):
            generate_report(root, gate, 1)

        self.assertIn(
            "EXTERNAL_EVIDENCE_SENTINEL",
            external.read_text(encoding="utf-8"),
        )
```

- [ ] **Step 3: 为 Runner audit/evidence 链接增加失败测试**

在 `tests/test_runner.py` 增加两个最小用例：

```python
def test_runner_rejects_linked_default_runs_directory_without_external_write(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
        try:
            (root / "runs").symlink_to(Path(outside), target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        policy = WorkspacePolicy(root, {"finish"}, {"TASK_SPEC.md"}, set())

        with self.assertRaises(WorkspacePathError):
            AgentRunner(root, MockLLM([]), policy)

        self.assertFalse((Path(outside) / "latest" / "trace.jsonl").exists())

def test_runner_rejects_linked_evidence_without_overwriting_external_file(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        root = Path(tmp) / "workspace"
        audit = Path(tmp) / "audit"
        root.mkdir()
        audit.mkdir()
        (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
        external = Path(outside) / "retrieval.json"
        external.write_text("EXTERNAL_RUNNER_SENTINEL", encoding="utf-8")
        try:
            (audit / "retrieval.json").symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        policy = WorkspacePolicy(root, {"finish"}, {"TASK_SPEC.md"}, set())

        with self.assertRaises(WorkspacePathError):
            AgentRunner(root, MockLLM([]), policy, audit_dir=audit)

        self.assertEqual(external.read_text(encoding="utf-8"), "EXTERNAL_RUNNER_SENTINEL")
```

- [ ] **Step 4: 运行三个失败测试组并确认 RED**

Run:

```powershell
python -m unittest tests.test_memory tests.test_report.ReportTests.test_generate_report_rejects_linked_reports_directory_without_external_write tests.test_runner.RunnerTests.test_runner_rejects_linked_default_runs_directory_without_external_write tests.test_runner.RunnerTests.test_runner_rejects_linked_evidence_without_overwriting_external_file -v
```

Expected: 至少链接攻击用例 FAIL，且外部 sentinel 暴露当前直接 Path I/O 缺陷。

- [ ] **Step 5: 迁移 Memory**

在 `src/specgate/memory.py` 导入 `specgate.workspace_fs as workspace_fs`，用以下边界替换直接 Path I/O：

```python
def _load_memory(root: Path) -> dict[str, Any]:
    text = workspace_fs.read_optional_workspace_text(
        root,
        MEMORY_FILE,
        encoding="utf-8",
    )
    if text is None:
        return {"runs": []}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"runs": []}
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return {"runs": []}
    return data
```

`append_memory()` 使用：

```python
workspace_fs.write_workspace_text(
    root,
    MEMORY_FILE,
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

- [ ] **Step 6: 迁移 Report 的安全读取与写入**

在 `src/specgate/report.py` 改为 `import specgate.workspace_fs as workspace_fs`。新增安全可选读取辅助函数，逐级使用 `workspace_fs.bind_workspace_tree(current, missing_ok=True)` 判断父目录是否缺失或不安全，最终用 `read_optional_workspace_text()` 读取普通文件：

```python
def _read_optional_report_text(root: Path, relative: str) -> str | None:
    relative_path = Path(relative)
    current = root
    for part in relative_path.parent.parts:
        current = current / part
        if workspace_fs.bind_workspace_tree(current, missing_ok=True) is None:
            return None
    return workspace_fs.read_optional_workspace_text(root, relative, encoding="utf-8")
```

将 retrieval、compression、isolation、security、benchmark 和 trace 的 `.exists()`/`.read_text()` 替换为该辅助函数。缺失时保持各区域现有的“无证据记录”文案；`WorkspacePathError` 只显示脱敏后的稳定 `rule_family`，不得把绝对路径或 sentinel 渲染到报告。

最终写入改为：

```python
workspace_fs.ensure_workspace_directory(root, "reports/latest")
workspace_fs.write_workspace_text(
    root,
    "reports/latest/index.html",
    html,
    encoding="utf-8",
)
return root / "reports" / "latest" / "index.html"
```

- [ ] **Step 7: 迁移 Runner audit/evidence**

在 `src/specgate/runner.py` 导入 `specgate.workspace_fs as workspace_fs`。构造阶段安全创建 audit 目录：

```python
if audit_dir is None:
    workspace_fs.ensure_workspace_directory(root, "runs/latest")
    self.run_dir = root / "runs" / "latest"
else:
    audit_path = Path(audit_dir)
    workspace_fs.ensure_workspace_directory(audit_path.parent, audit_path.name)
    self.run_dir = audit_path
```

`_reset_run_artifacts()` 对三个文件调用：

```python
workspace_fs.write_workspace_text(self.run_dir, name, "{}", encoding="utf-8")
```

三个 `_record_*()` 方法分别改用：

```python
workspace_fs.write_workspace_text(
    self.run_dir,
    "retrieval.json",
    json.dumps(retrieval, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

compression/isolation 使用对应文件名和对象；不得保留直接 `.write_text()` 或 `.unlink()`。

- [ ] **Step 8: 运行 Task 2 局部回归**

Run:

```powershell
python -m unittest tests.test_memory tests.test_report tests.test_runner -v
```

Expected: PASS；`reset_audit=False` 仍原样保留已有 Trace/evidence，显式 Web audit 路径仍可正常创建。

### Task 3: 把非法 UTF-8 转换成结构化 Tool/Gate 失败

**Files:**
- Modify: `src/specgate/tools.py`
- Modify: `src/specgate/gate.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_gate.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 增加 Tool RED 测试**

在 `tests/test_tools.py` 增加：

```python
def test_read_file_returns_invalid_encoding_result_for_non_utf8_bytes(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "index.html").write_bytes(b"\xff\xfe\x00")
        policy = WorkspacePolicy(root, {"read_file"}, {"index.html"}, set())

        result = ToolDispatcher(policy).dispatch(
            Action("1", "read_file", {"path": "index.html"})
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(result.rule_family, "invalid_encoding")
        self.assertEqual(result.data["rule_family"], "invalid_encoding")
        self.assertEqual(result.data["path"], "index.html")
        self.assertNotIn("\\xff", result.message)
```

- [ ] **Step 2: 增加 Gate RED 测试**

在 `tests/test_gate.py` 增加 artifact 和 checklist 两个用例：

```python
def test_invalid_utf8_artifact_returns_structured_gate_failure(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "index.html").write_bytes(b"\xff\xfe")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")

        result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

        self.assertFalse(result.passed)
        self.assertEqual(result.issues[0].code, "invalid_artifact_encoding")
        self.assertEqual(result.issues[0].evidence, "invalid_encoding")

def test_invalid_utf8_checklist_returns_structured_gate_failure(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "index.html").write_text(VALID_HTML, encoding="utf-8")
        (root / "CHECKLIST.md").write_bytes(b"\xff\xfe")

        result = run_html_gate(root / "index.html", root / "CHECKLIST.md")

        self.assertFalse(result.passed)
        self.assertEqual(result.issues[0].code, "invalid_checklist_encoding")
        self.assertEqual(result.issues[0].evidence, "invalid_encoding")
```

- [ ] **Step 3: 增加 Runner 集成 RED 测试**

在 `tests/test_runner.py` 增加完整的 finish-only run：

```python
def test_invalid_utf8_artifact_returns_failed_result_without_runner_crash(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        (root / "index.html").write_bytes(b"\xff\xfe")
        policy = WorkspacePolicy(
            root,
            {"finish"},
            {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
            set(),
        )

        result = AgentRunner(
            root,
            MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "finish",
                        "args": {"summary": "done"},
                    }
                ]
            ),
            policy,
            max_steps=1,
        ).run()

        self.assertFalse(result.passed)
        self.assertIsNotNone(result.final_gate)
        self.assertIn(
            "invalid_artifact_encoding",
            {issue.code for issue in result.final_gate.issues},
        )
```

- [ ] **Step 4: 运行编码测试并确认 RED**

Run:

```powershell
python -m unittest tests.test_tools.ToolDispatcherTests.test_read_file_returns_invalid_encoding_result_for_non_utf8_bytes tests.test_gate.HtmlGateTests.test_invalid_utf8_artifact_returns_structured_gate_failure tests.test_gate.HtmlGateTests.test_invalid_utf8_checklist_returns_structured_gate_failure -v
```

Expected: ERROR，当前传播 `UnicodeDecodeError`。

- [ ] **Step 5: 实现 Tool 结构化结果**

在 `src/specgate/tools.py::_read_file()` 的 `WorkspacePathError` 分支之前捕获：

```python
except UnicodeDecodeError:
    return ToolResult(
        False,
        action.action,
        f"invalid UTF-8 encoding: {relative_path}",
        {"path": relative_path, "rule_family": "invalid_encoding"},
        blocked=True,
        rule_family="invalid_encoding",
    )
```

- [ ] **Step 6: 实现 Gate 结构化结果**

在 `src/specgate/gate.py` 新增：

```python
def _invalid_encoding_result(kind: str) -> GateResult:
    if kind == "artifact":
        code = "invalid_artifact_encoding"
        message = "index.html is not valid UTF-8"
        hint = "Replace index.html with a valid UTF-8 regular file"
    else:
        code = "invalid_checklist_encoding"
        message = "checklist is not valid UTF-8"
        hint = "Replace the checklist with a valid UTF-8 regular file"
    issue = _issue(code, message, "invalid_encoding", hint)
    return GateResult(False, [_check(code, False, message)], [issue], f"Gate failed: {hint}")
```

在 artifact/checklist 两个 `_read_gate_file()` 调用边界分别捕获 `UnicodeDecodeError` 并返回相应结果，不在 `_read_gate_file()` 中使用 `errors="replace"`。

- [ ] **Step 7: 运行 Task 3 局部回归**

Run:

```powershell
python -m unittest tests.test_tools tests.test_gate tests.test_runner -v
```

Expected: PASS，Runner 不出现 traceback。

### Task 4: 消除 Provider 错误正文泄密

**Files:**
- Modify: `src/specgate/llm.py`
- Modify: `src/specgate/cli.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 把现有 HTTP 错误测试改为任意秘密哨兵**

更新 `tests/test_llm.py::test_http_error_is_wrapped_without_leaking_api_key`：响应正文改为不匹配常见 Key 正则的 `REFLECTED_BODY_SECRET_7b21`，并断言：

```python
self.assertEqual(message, "HTTP 403 Forbidden")
self.assertNotIn("REFLECTED_BODY_SECRET_7b21", message)
self.assertNotIn("model not allowed", message)
```

可保存 `BytesIO` 引用并断言异常后已经关闭，证明正文未读取但资源被释放。

- [ ] **Step 2: 运行 Provider 测试并确认 RED**

Run:

```powershell
python -m unittest tests.test_llm.OpenAICompatibleLLMTests.test_http_error_is_wrapped_without_leaking_api_key -v
```

Expected: FAIL；当前异常包含 HTTP 响应正文。

- [ ] **Step 3: 实现 Provider 最小保密异常**

将 `src/specgate/llm.py` 的 `HTTPError` 分支替换为：

```python
except error.HTTPError as exc:
    try:
        reason = f" {exc.reason}" if exc.reason else ""
        raise LLMProviderError(f"HTTP {exc.code}{reason}") from exc
    finally:
        exc.close()
```

不得调用 `exc.read()`，不得保留 body 截断逻辑。

- [ ] **Step 4: 增加 CLI 脱敏 RED 测试**

扩展现有 `test_eval_cli_reports_provider_error_without_traceback` 和 `test_real_run_reports_provider_error_without_traceback`，让假的 Provider 抛出：

```python
LLMProviderError("HTTP 403 Forbidden: sk-cli-error-secret123456")
```

继续断言输出包含 `provider request failed` 和 `HTTP 403`，但不包含完整 secret 或 traceback。

- [ ] **Step 5: 在 CLI 错误展示边界统一脱敏**

把 `src/specgate/cli.py` 两处：

```python
print(f"provider request failed: {exc}")
```

改为：

```python
print(f"provider request failed: {redact(str(exc))}")
```

- [ ] **Step 6: 运行 Task 4 局部回归**

Run:

```powershell
python -m unittest tests.test_llm tests.test_cli -v
```

Expected: PASS；测试不访问真实网络。

### Task 5: 删除 Web 遗留逐任务线程入口

**Files:**
- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_runtime.py`

- [ ] **Step 1: 增加架构 RED 测试**

在 `tests/test_web_runtime.py` 增加 `inspect`、`specgate.web_runs as web_runs` import，并加入：

```python
class WebRuntimeArchitectureTests(unittest.TestCase):
    def test_web_runs_has_no_per_run_thread_entrypoint(self):
        source = inspect.getsource(web_runs)

        self.assertFalse(hasattr(web_runs, "start_run_background"))
        self.assertNotIn("threading.Thread(", source)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runtime.WebRuntimeArchitectureTests.test_web_runs_has_no_per_run_thread_entrypoint -v
```

Expected: FAIL；模块仍导出 `start_run_background`。

- [ ] **Step 3: 删除遗留入口**

从 `src/specgate/web_runs.py` 删除顶部 `import threading`，并完整删除第 528 行附近从 `def start_run_background` 到 `return thread` 的函数块。删除后 `get_run()` 的 `finally: conn.close()` 应直接衔接 `execute_run_once()`，中间不保留替代线程包装器。

保留 `execute_run_once()`，不得把线程创建移动到其他业务模块。

- [ ] **Step 4: 运行 Web runtime/run 回归**

Run:

```powershell
python -m unittest tests.test_web_runtime tests.test_web_runs tests.test_web_app tests.test_web_approvals -v
```

Expected: PASS；固定 worker、有界队列、恢复、取消、超时和审批续跑均保持正常。

### Task 6: 同步文档与最终验证

**Files:**
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/superpowers/plans/2026-07-15-backend-audit-hardening.md`

- [ ] **Step 1: 运行定向安全回归**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_workspace_fs tests.test_context tests.test_memory tests.test_report tests.test_tools tests.test_gate tests.test_llm tests.test_runner tests.test_cli tests.test_web_runtime tests.test_web_runs tests.test_web_app tests.test_web_approvals -v
```

Expected: PASS；记录真实测试数量和 skipped 数量，不预填计划值。

- [ ] **Step 2: 运行全量测试**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: `OK`；CLI 对非法 governance profile 输出 usage 属于既有负向测试，不是失败。把命令输出中的精确测试总数和跳过数记录到材料中。

- [ ] **Step 3: 运行静态与格式验证**

Run:

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
git status --short --branch
```

Expected: 前三项退出码均为 0；status 只包含本计划列出的文件。

- [ ] **Step 4: 扫描直接写入与线程遗留**

Run:

```powershell
rg -n "\.write_text\(|\.open\(\"a\"|start_run_background|threading\.Thread\(" src/specgate/trace.py src/specgate/memory.py src/specgate/report.py src/specgate/runner.py src/specgate/web_runs.py
```

Expected: 上述 Harness 产物不再直接写入；`web_runs.py` 不再含逐任务线程入口。若存在与本任务无关的合法读写，逐项核对后在 `AGENT_LOG.md` 记录，不用宽泛正则掩盖。

- [ ] **Step 5: 同步中文材料**

按真实验证结果更新：

- `PLAN.md`：后端审计加固阶段、四项修复和状态。
- `AGENT_LOG.md`：Red/Green 证据、定向/全量测试统计、非目标和真实 LLM 后续分支。
- `README.md`、`docs/DEPLOYMENT.md`：安全产物路径、非法 UTF-8、Provider 错误正文保密、Web 单协调器约束。
- `docs/FINAL_EVIDENCE_MATRIX.md`：补 PR #16/#17、CI #47、Pages #28 的已知事实；本 PR 编号和 CI 只有用户创建后再填。
- `docs/FINAL_SUBMISSION_CHECKLIST.md`：反思已确认，安全审计已完成；公开 registry/Open Design/公网交互式 Web 若尚无证据则继续诚实标记。

- [ ] **Step 6: 最终事实复核**

再次运行：

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
```

Expected: 全部通过。只有此时才能对用户声明实现完成，并提供精确文件清单、Git 指令和中文 PR 内容。

- [ ] **Step 7: 用户执行 Git/PR**

Agent 根据最终 `git status --short` 给出逐文件 `git add` 命令。建议提交标题：

```text
fix: 加固后端审计安全边界
```

建议 PR 标题：

```text
fix: 加固后端审计安全边界
```

PR 正文必须使用最终实际测试数字和 CI 状态，不复制计划中的 Expected 文案冒充证据。

## 实施状态（2026-07-15）

- [x] Task 1：安全追加写入与 Trace 迁移。
- [x] Task 2：Memory、Report、Runner 自有产物迁移；空 evidence 在 Web debug 边界保持 `null`。
- [x] Task 3：Tool/Gate 非法 UTF-8 结构化失败；补充 Context artifact summary 安全读取。
- [x] Task 4：Provider 丢弃 HTTP 错误正文，CLI 纵深脱敏。
- [x] Task 5：删除 `start_run_background()` 和 `web_runs.py` 逐任务线程创建。
- [x] Task 6：中文材料、全量回归、编译、JavaScript 与差异验证完成。
