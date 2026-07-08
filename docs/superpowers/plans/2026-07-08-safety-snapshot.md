# Safety Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 SpecGate 增加运行级文件快照，让写入工具在覆盖文件前检测用户或外部进程是否已经修改目标文件。

**Architecture:** 新增 `snapshot.py` 负责捕获 allowed write paths 的文件状态、比较当前状态、在 harness 自己成功写入后更新可信基线；`ToolDispatcher` 在 `write_file` / `replace_file` 前调用 snapshot，拦截外部修改；`AgentRunner` 默认在 run 开始时创建 snapshot 并传给 dispatcher。

**Tech Stack:** Python 3.11 标准库、`hashlib`、`dataclasses`、`pathlib`、`unittest`、现有 SpecGate runner/tool/policy 模块。

---

## File Structure

- Create: `src/specgate/snapshot.py`
  - 定义 `FileState`、`SnapshotDecision`、`FileSnapshot`。
  - 实现 `capture()`、`check_unchanged()`、`update_after_write()`。
- Create: `tests/test_snapshot.py`
  - 独立测试快照状态判断。
- Modify: `src/specgate/tools.py`
  - `ToolDispatcher` 接收可选 `FileSnapshot`。
  - 写入前执行 snapshot 检查。
  - 写入成功后更新 snapshot。
- Modify: `tests/test_tools.py`
  - 增加外部修改时阻止写入的工具层测试。
  - 增加 harness 自己连续写入不被误拦的测试。
- Modify: `src/specgate/runner.py`
  - `AgentRunner` 初始化时捕获 `policy.allowed_write_paths`。
- Modify: `tests/test_runner.py`
  - 增加 trace 中记录 snapshot 拦截事件的测试。
- Modify: `README.md`
  - 简短说明运行期间用户修改检测。
- Modify: `AGENT_LOG.md`
  - 记录安全修改检测实现和验证结果。

---

## Task 1: 新增 FileSnapshot

**Files:**
- Create: `tests/test_snapshot.py`
- Create: `src/specgate/snapshot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_snapshot.py`:

```python
import tempfile
import unittest
from pathlib import Path

from specgate.snapshot import FileSnapshot


class FileSnapshotTests(unittest.TestCase):
    def test_allows_existing_file_when_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")

            snapshot = FileSnapshot.capture(root, {"index.html"})
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.reason, "unchanged")

    def test_blocks_existing_file_when_content_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("external edit", encoding="utf-8")
            decision = snapshot.check_unchanged("index.html")

            self.assertFalse(decision.allowed)
            self.assertIn("file changed since run started", decision.reason)

    def test_allows_missing_file_when_still_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            snapshot = FileSnapshot.capture(root, {"index.html"})
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.reason, "unchanged")

    def test_blocks_missing_file_when_it_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("created outside", encoding="utf-8")
            decision = snapshot.check_unchanged("index.html")

            self.assertFalse(decision.allowed)
            self.assertIn("file changed since run started", decision.reason)

    def test_blocks_path_not_in_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            decision = snapshot.check_unchanged("other.html")

            self.assertFalse(decision.allowed)
            self.assertIn("not in snapshot", decision.reason)

    def test_update_after_write_refreshes_trusted_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = FileSnapshot.capture(root, {"index.html"})

            (root / "index.html").write_text("written by harness", encoding="utf-8")
            snapshot.update_after_write("index.html")
            decision = snapshot.check_unchanged("index.html")

            self.assertTrue(decision.allowed)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_snapshot -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.snapshot'
```

- [ ] **Step 3: Implement snapshot module**

Create `src/specgate/snapshot.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class SnapshotDecision:
    allowed: bool
    reason: str


class FileSnapshot:
    def __init__(self, root: Path, states: dict[str, FileState]):
        self.root = root
        self._states = dict(states)

    @classmethod
    def capture(cls, root: Path, relative_paths: set[str]) -> "FileSnapshot":
        states = {path: _read_state(root / path) for path in sorted(relative_paths)}
        return cls(root, states)

    def check_unchanged(self, relative_path: str) -> SnapshotDecision:
        expected = self._states.get(relative_path)
        if expected is None:
            return SnapshotDecision(False, f"file not in snapshot: {relative_path}")

        try:
            current = _read_state(self.root / relative_path)
        except OSError:
            return SnapshotDecision(False, f"file changed since run started: {relative_path}")

        if current == expected:
            return SnapshotDecision(True, "unchanged")
        return SnapshotDecision(False, f"file changed since run started: {relative_path}")

    def update_after_write(self, relative_path: str) -> None:
        if relative_path not in self._states:
            raise KeyError(f"file not in snapshot: {relative_path}")
        self._states[relative_path] = _read_state(self.root / relative_path)


def _read_state(path: Path) -> FileState:
    if not path.exists():
        return FileState(False, None)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileState(True, digest)
```

- [ ] **Step 4: Run snapshot tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_snapshot -v
```

Expected:

```text
Ran 6 tests ... OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/snapshot.py tests/test_snapshot.py
git commit -m "feat: 新增运行级文件快照"
```

---

## Task 2: 接入 ToolDispatcher

**Files:**
- Modify: `src/specgate/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tool tests**

Modify `tests/test_tools.py`, add import:

```python
from specgate.snapshot import FileSnapshot
```

Add tests inside `ToolDispatcherTests`:

```python
    def test_snapshot_blocks_write_after_external_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("initial", encoding="utf-8")
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            snapshot = FileSnapshot.capture(root, {"index.html"})
            dispatcher = ToolDispatcher(policy, snapshot)

            (root / "index.html").write_text("external edit", encoding="utf-8")
            result = dispatcher.dispatch(
                Action("1", "write_file", {"path": "index.html", "content": "agent edit"})
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("file changed since run started", result.message)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "external edit")

    def test_snapshot_updates_after_successful_tool_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"write_file", "replace_file"},
                allowed_read_paths={"index.html"},
                allowed_write_paths={"index.html"},
            )
            snapshot = FileSnapshot.capture(root, {"index.html"})
            dispatcher = ToolDispatcher(policy, snapshot)

            first = dispatcher.dispatch(
                Action("1", "write_file", {"path": "index.html", "content": "first"})
            )
            second = dispatcher.dispatch(
                Action("1", "replace_file", {"path": "index.html", "content": "second"})
            )

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "second")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
TypeError: ToolDispatcher.__init__() takes 2 positional arguments but 3 were given
```

- [ ] **Step 3: Update ToolDispatcher**

Modify `src/specgate/tools.py`:

```python
from specgate.snapshot import FileSnapshot
```

Change initializer:

```python
class ToolDispatcher:
    def __init__(self, policy: WorkspacePolicy, snapshot: FileSnapshot | None = None):
        self.policy = policy
        self.snapshot = snapshot
```

Update `_write_file()`:

```python
    def _write_file(self, action: Action) -> ToolResult:
        relative_path = action.args["path"]
        if self.snapshot is not None:
            snapshot_decision = self.snapshot.check_unchanged(relative_path)
            if not snapshot_decision.allowed:
                return ToolResult(
                    False,
                    action.action,
                    snapshot_decision.reason,
                    {"path": relative_path},
                    blocked=True,
                )

        path = self._resolve(relative_path)
        content = action.args.get("content", "")
        if not isinstance(content, str):
            return ToolResult(False, action.action, "content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if self.snapshot is not None:
            self.snapshot.update_after_write(relative_path)
        return ToolResult(True, action.action, f"wrote {relative_path}", {"path": relative_path})
```

- [ ] **Step 4: Run tool tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_tools -v
```

Expected:

```text
Ran 4 tests ... OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/tools.py tests/test_tools.py
git commit -m "feat: 写入工具拦截外部文件修改"
```

---

## Task 3: AgentRunner 默认启用快照

**Files:**
- Modify: `src/specgate/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Write failing runner test**

Modify `tests/test_runner.py`, add this helper class after `FIXED_HTML`:

```python
class MutatingLLM:
    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    def complete(self, context: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return (
                '{"schema_version":"1","action":"write_file",'
                '"args":{"path":"index.html","content":"<!doctype html><html><body>draft</body></html>"}}'
            )
        if self.calls == 2:
            (self.root / "index.html").write_text("external edit", encoding="utf-8")
            return (
                '{"schema_version":"1","action":"replace_file",'
                '"args":{"path":"index.html","content":"agent overwrite"}}'
            )
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'
```

Add test inside `RunnerTests`:

```python
    def test_external_file_change_is_blocked_and_traced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MutatingLLM(root)
            policy = WorkspacePolicy(
                root,
                {"write_file", "replace_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=3).run()

            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("file changed since run started", trace_text)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "external edit")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected:

```text
FAIL: test_external_file_change_is_blocked_and_traced
AssertionError: 'file changed since run started' not found in ...
```

- [ ] **Step 3: Enable snapshot in AgentRunner**

Modify `src/specgate/runner.py`, add import:

```python
from specgate.snapshot import FileSnapshot
```

Change initializer:

```python
        snapshot = FileSnapshot.capture(root, policy.allowed_write_paths)
        self.dispatcher = ToolDispatcher(policy, snapshot)
```

- [ ] **Step 4: Run runner tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected:

```text
Ran 3 tests ... OK
```

- [ ] **Step 5: Run context/CLI regression**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli tests.test_tools tests.test_runner -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: 在agent运行中启用文件快照保护"
```

---

## Task 4: 文档、日志与全量验证

**Files:**
- Modify: `README.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Update README**

In `README.md`, after the `## 安全边界` paragraph, add:

```markdown
运行期间，SpecGate 会对允许写入的文件建立快照。`write_file` / `replace_file` 写入前会检查目标文件是否被外部修改；如果用户在 run 期间改过文件，harness 会阻止覆盖并在 trace 中记录 blocked tool result。
```

- [ ] **Step 2: Update AGENT_LOG**

Append to `AGENT_LOG.md`:

```markdown
## 2026-07-08

- Task：第二阶段安全修改检测。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/snapshot.py`，记录 allowed write paths 的文件快照。
  - 新增 `tests/test_snapshot.py`，覆盖已存在文件、missing 文件、外部修改和写入后基线更新。
  - 更新 `src/specgate/tools.py`，写入前检查 snapshot，写入成功后更新 snapshot。
  - 更新 `src/specgate/runner.py`，run 开始时默认启用文件快照保护。
  - 更新 `README.md`，说明运行期间用户修改检测。
- 代码作用：
  - 防止 agent 在运行期间覆盖用户或外部进程对 allowlist 文件的修改。
  - 安全拦截以 blocked `ToolResult` 写入 trace，便于报告和复盘。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认第二阶段采用“先让 Context / Safety / Tooling 都有可测试第一层”的路线。
```

- [ ] **Step 3: Run full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected:

```text
OK
```

- [ ] **Step 4: Run mock demo**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

Expected:

```text
exit code 0
```

The CLI may print no output. If so, verify `examples/knowledge_nav/reports/latest/index.html` exists.

- [ ] **Step 5: Check diff hygiene**

Run:

```powershell
git diff --check
git status --short
```

Expected:

```text
git diff --check
# no whitespace errors

git status --short
 M AGENT_LOG.md
 M README.md
```

Windows LF/CRLF warnings are acceptable if no whitespace errors are reported.

- [ ] **Step 6: Commit**

Run:

```powershell
git add README.md AGENT_LOG.md
git commit -m "docs: 记录安全修改检测验证结果"
```

---

## Final Verification

After all tasks:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m specgate.cli run-mock-demo examples/knowledge_nav
git log --oneline -8
git status
```

Expected:

- 全量测试通过。
- mock demo 通过。
- 最近提交包含：
  - `docs: 记录安全修改检测验证结果`
  - `feat: 在agent运行中启用文件快照保护`
  - `feat: 写入工具拦截外部文件修改`
  - `feat: 新增运行级文件快照`
- 工作区干净。
