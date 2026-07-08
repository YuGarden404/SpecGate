# Context Management Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 SpecGate 增加轻量 Context Manifest 机制，让 harness 能扫描任务目录、按优先级和字符预算选择上下文文件，并解释 selected / skipped / truncated 决策。

**Architecture:** 新增 `context_selector.py` 负责目录扫描、排除规则、优先级排序和预算裁剪；`context.py` 保持 `build_context_pack(root, latest_gate)` 对外接口不变，但内部改用 selector 渲染 Context Manifest 和选中文件内容。现有 runner、LLM、Gate、工具分发和 CLI 不改接口。

**Tech Stack:** Python 3.11 标准库、`dataclasses`、`pathlib`、`unittest`、现有 SpecGate 模块。

---

## File Structure

- Create: `src/specgate/context_selector.py`
  - 定义 `ContextFile`、`ContextSelection`。
  - 实现 `select_context_files(root: Path, budget_chars: int = 12000) -> ContextSelection`。
  - 负责文本后缀判断、目录排除、优先级、预算、截断。
- Create: `tests/test_context_selector.py`
  - 独立测试 selector 行为。
- Modify: `src/specgate/context.py`
  - 保留 `_artifact_summary()`。
  - 用 selector 替代固定读取 `TASK_SPEC.md` / `CHECKLIST.md`。
  - 输出 `## Context Manifest` 和 `## Selected Files`。
- Modify: `tests/test_context.py`
  - 增加 Context Manifest 断言。
  - 保留已有 Gate summary、任务文档、Checklist 和 artifact summary 断言。
- Modify: `README.md`
  - 简短补充 Context Pack 已支持 manifest 和预算选择。
- Modify: `AGENT_LOG.md`
  - 记录第二阶段上下文管理增强、测试命令和验证结果。

---

## Task 1: 新增 Context Selector

**Files:**
- Create: `tests/test_context_selector.py`
- Create: `src/specgate/context_selector.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_context_selector.py`:

```python
import tempfile
import unittest
from pathlib import Path

from specgate.context_selector import select_context_files


def _statuses(selection):
    return {item.path: item.status for item in selection.files}


class ContextSelectorTests(unittest.TestCase):
    def test_selects_priority_task_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("checklist", encoding="utf-8")
            (root / "README.md").write_text("readme", encoding="utf-8")
            (root / "index.html").write_text("<html></html>", encoding="utf-8")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["CHECKLIST.md"], "selected")
            self.assertEqual(statuses["README.md"], "selected")
            self.assertEqual(statuses["index.html"], "selected")
            self.assertLessEqual(selection.used_chars, selection.budget_chars)

    def test_skips_runtime_outputs_and_cache_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "runs" / "latest").mkdir(parents=True)
            (root / "runs" / "latest" / "trace.jsonl").write_text("trace", encoding="utf-8")
            (root / "reports" / "latest").mkdir(parents=True)
            (root / "reports" / "latest" / "index.html").write_text("report", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_bytes(b"cache")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["runs/latest/trace.jsonl"], "skipped")
            self.assertEqual(statuses["reports/latest/index.html"], "skipped")
            self.assertEqual(statuses["__pycache__/x.pyc"], "skipped")

    def test_applies_budget_to_low_priority_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("A" * 40, encoding="utf-8")
            (root / "notes.txt").write_text("B" * 200, encoding="utf-8")

            selection = select_context_files(root, budget_chars=80)
            by_path = {item.path: item for item in selection.files}

            self.assertEqual(by_path["TASK_SPEC.md"].status, "selected")
            self.assertIn(by_path["notes.txt"].status, {"truncated", "skipped"})
            self.assertLessEqual(selection.used_chars, 80)

    def test_skips_non_text_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["image.png"], "skipped")

    def test_rejects_invalid_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                select_context_files(Path(tmp), budget_chars=0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context_selector -v
```

Expected:

```text
ModuleNotFoundError: No module named 'specgate.context_selector'
```

- [ ] **Step 3: Implement minimal selector**

Create `src/specgate/context_selector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {".md", ".html", ".css", ".js", ".txt", ".toml", ".json", ".jsonl"}
EXCLUDED_DIRS = {".git", "__pycache__", "runs", "reports"}
DEFAULT_BUDGET_CHARS = 12000
TRUNCATION_SUFFIX = "\n...[truncated by SpecGate context budget]\n"


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


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _is_under_excluded_dir(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts[:-1])


def _priority(relative_path: str) -> int:
    names = {
        "TASK_SPEC.md": 0,
        "CHECKLIST.md": 1,
        "README.md": 2,
        "index.html": 3,
    }
    if relative_path in names:
        return names[relative_path]
    if relative_path.endswith(".md"):
        return 10
    if relative_path.endswith(".html"):
        return 20
    if relative_path.endswith((".css", ".js")):
        return 30
    return 40


def _scan_files(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda item: _relative(item, root))


def select_context_files(root: Path, budget_chars: int = DEFAULT_BUDGET_CHARS) -> ContextSelection:
    if budget_chars <= 0:
        raise ValueError("budget_chars must be positive")

    candidates: list[tuple[int, str, Path]] = []
    skipped: list[ContextFile] = []

    for path in _scan_files(root):
        rel = _relative(path, root)
        priority = _priority(rel)
        if _is_under_excluded_dir(path, root):
            skipped.append(ContextFile(rel, "skipped", "excluded runtime or hidden directory", 0, priority))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(ContextFile(rel, "skipped", "unsupported file suffix", 0, priority))
            continue
        candidates.append((priority, rel, path))

    selected: list[ContextFile] = []
    used_chars = 0

    for priority, rel, path in sorted(candidates):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            selected.append(ContextFile(rel, "skipped", "file is not utf-8 text", 0, priority))
            continue
        except OSError as exc:
            selected.append(ContextFile(rel, "skipped", f"read failed: {exc}", 0, priority))
            continue

        remaining = budget_chars - used_chars
        if remaining <= 0:
            selected.append(ContextFile(rel, "skipped", "context budget exhausted", len(content), priority))
            continue
        if len(content) <= remaining:
            selected.append(ContextFile(rel, "selected", "selected within context budget", len(content), priority, content))
            used_chars += len(content)
            continue

        if remaining > len(TRUNCATION_SUFFIX):
            truncated = content[: remaining - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
            selected.append(ContextFile(rel, "truncated", "truncated to fit context budget", len(content), priority, truncated))
            used_chars += len(truncated)
        else:
            selected.append(ContextFile(rel, "skipped", "context budget exhausted", len(content), priority))

    return ContextSelection(sorted(selected + skipped, key=lambda item: (item.priority, item.path)), budget_chars, used_chars)
```

- [ ] **Step 4: Run selector tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context_selector -v
```

Expected:

```text
Ran 5 tests ... OK
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/context_selector.py tests/test_context_selector.py
git commit -m "feat: 新增上下文文件选择器"
```

---

## Task 2: 接入 Context Pack

**Files:**
- Modify: `src/specgate/context.py`
- Modify: `tests/test_context.py`

- [ ] **Step 1: Write failing context pack assertion**

Modify `tests/test_context.py`, in `test_context_pack_contains_task_docs_and_gate_summary`, add these assertions after `pack = build_context_pack(root, gate)`:

```python
self.assertIn("Context Manifest", pack)
self.assertIn("Selected Files", pack)
self.assertIn("TASK_SPEC.md", pack)
self.assertIn("selected", pack)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context -v
```

Expected:

```text
FAIL: test_context_pack_contains_task_docs_and_gate_summary
AssertionError: 'Context Manifest' not found in ...
```

- [ ] **Step 3: Update context rendering**

Replace `src/specgate/context.py` with:

```python
from __future__ import annotations

from pathlib import Path

from specgate.context_selector import ContextSelection, select_context_files
from specgate.gate import GateResult


def _artifact_summary(path: Path) -> str:
    if not path.exists():
        return "index.html 摘要：文件不存在"
    content = path.read_text(encoding="utf-8")
    node_count = content.count('class="node"') + content.count("class='node'")
    return f"index.html 摘要：{len(content)} 字符，node 出现 {node_count} 次"


def _render_manifest(selection: ContextSelection) -> str:
    lines = [
        f"budget_chars: {selection.budget_chars}",
        f"used_chars: {selection.used_chars}",
    ]
    for item in selection.files:
        lines.append(f"- {item.status}: {item.path} ({item.reason}, chars={item.chars})")
    return "\n".join(lines)


def _render_selected_files(selection: ContextSelection) -> str:
    blocks: list[str] = []
    for item in selection.files:
        if item.status not in {"selected", "truncated"}:
            continue
        blocks.append(f"### {item.path}\n```text\n{item.content}\n```")
    if not blocks:
        return "没有文件进入上下文。"
    return "\n\n".join(blocks)


def build_context_pack(root: Path, latest_gate: GateResult | None) -> str:
    selection = select_context_files(root)
    gate_summary = latest_gate.summary if latest_gate else "尚未运行 Gate"

    return "\n\n".join(
        [
            "你是 SpecGate harness 中的 coding agent。只输出严格 JSON action。",
            "## Context Manifest\n" + _render_manifest(selection),
            "## Selected Files\n" + _render_selected_files(selection),
            "## " + _artifact_summary(root / "index.html"),
            "## 最近 Gate 结果\n" + gate_summary,
        ]
    )
```

- [ ] **Step 4: Run context tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context tests.test_context_selector -v
```

Expected:

```text
Ran 7 tests ... OK
```

- [ ] **Step 5: Run runner regression**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected:

```text
Ran 2 tests ... OK
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/specgate/context.py tests/test_context.py
git commit -m "feat: 将上下文选择器接入context pack"
```

---

## Task 3: 文档、日志与全量验证

**Files:**
- Modify: `README.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Update README**

In `README.md`, after the `Mock Demo` section's example directory explanation, add:

```markdown
## 上下文管理

SpecGate 的 context pack 会扫描任务目录，并生成 `Context Manifest`。默认优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`，跳过 `runs/`、`reports/`、`.git/`、`__pycache__/` 等运行产物或缓存目录，并使用字符预算控制进入 LLM 的内容规模。
```

- [ ] **Step 2: Update AGENT_LOG**

Append to `AGENT_LOG.md`:

```markdown
## 2026-07-08

- Task：第二阶段上下文管理增强。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/context_selector.py`，实现 Context Manifest 文件选择。
  - 新增 `tests/test_context_selector.py`，覆盖优先级、跳过规则、预算和非法预算。
  - 更新 `src/specgate/context.py`，让 context pack 输出 Context Manifest 和 Selected Files。
  - 更新 `README.md`，说明上下文管理行为。
- 代码作用：
  - 将固定拼接上下文升级为按目录扫描、优先级和预算选择上下文。
  - 默认跳过运行报告、trace 和缓存目录，避免污染后续 LLM 输入。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认默认上下文选择规则和 12000 字符预算可以接受。
```

- [ ] **Step 3: Run full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 26 tests ... OK
```

The exact test count may be higher if more tests were added, but the result must be `OK`.

- [ ] **Step 4: Run mock demo**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

Expected:

```text
Report written to examples/knowledge_nav/reports/latest/index.html
```

If the CLI prints no output but exits with code 0, verify the report file timestamp changed.

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
git commit -m "docs: 记录上下文管理增强验证结果"
```

---

## Final Verification

After all tasks:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m specgate.cli run-mock-demo examples/knowledge_nav
git log --oneline -5
git status
```

Expected:

- 全量测试通过。
- mock demo 通过。
- 最近提交包含：
  - `docs: 记录上下文管理增强验证结果`
  - `feat: 将上下文选择器接入context pack`
  - `feat: 新增上下文文件选择器`
- 工作区干净。
