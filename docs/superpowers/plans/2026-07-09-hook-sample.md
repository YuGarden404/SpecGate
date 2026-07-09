# Lab 11 Hook Sample 实施计划

> **给执行智能体：** 使用 `superpowers:executing-plans` 按任务执行。本计划只新增可选 Hook 示例，不改变 SpecGate runtime。

**目标：** 增加 Lab 11 / HE 对齐证据：一个可选 `pre-commit.sample`，用于密钥扫描、必要文件检查和测试提示。

**架构：** 新增 `hooks/pre-commit.sample` 作为可选 Git hook；新增 `tests/test_hook_sample.py` 只检查 sample 内容，不执行 shell；更新课程对齐和最终提交文档。

**技术栈：** POSIX shell sample、Python `unittest`、Markdown。

---

## 文件结构

- 创建：`hooks/pre-commit.sample`
  - 可选安装的 Git hook 示例。
- 创建：`tests/test_hook_sample.py`
  - 验证 Hook sample 包含密钥扫描、必要文件和测试提示。
- 创建：`docs/superpowers/specs/2026-07-09-hook-sample-design.md`
  - 记录设计与边界。
- 修改：`docs/AI4SE_Lab_9_12_Alignment.md`
  - 将 Lab 11 状态从后续候选更新为已提供 sample。
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
  - 增加 Hook sample 交付证据。
- 修改：`README.md`
  - 增加 Hook sample 说明。
- 修改：`AGENT_LOG.md`
  - 记录实现和验证结果。

---

## Task 1：新增 Hook sample

- [x] **步骤 1：创建 `hooks/pre-commit.sample`**

包含：

- staged 文件密钥扫描；
- demo 任务关键文件存在性检查；
- 单元测试命令提示；
- 明确说明它不是 SpecGate runtime 的一部分。

## Task 2：新增测试

- [x] **步骤 1：创建 `tests/test_hook_sample.py`**

测试内容：

- Hook sample 文件存在；
- 包含 `SECRET_PATTERNS`；
- 包含常见 API key 标识；
- 包含 demo 必要文件；
- 包含推荐测试命令；
- 包含 runtime 边界说明。

## Task 3：更新文档

- [x] **步骤 1：更新 Lab 对齐文档**

说明 Lab 11 已有 Hook sample，但仍不强制安装。

- [x] **步骤 2：更新最终提交清单和 README**

把 Hook sample 加入评审证据。

- [x] **步骤 3：更新 AGENT_LOG**

记录本阶段人工决策、文件变更和验证证据。

## Task 4：验证与提交

- [x] **步骤 1：运行全量测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

- [x] **步骤 2：运行 mock demo**

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

- [x] **步骤 3：运行 Skill 校验**

```powershell
$env:PYTHONUTF8="1"
python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness
```

- [x] **步骤 4：提交**

```powershell
git add hooks/pre-commit.sample tests/test_hook_sample.py docs/superpowers/specs/2026-07-09-hook-sample-design.md docs/superpowers/plans/2026-07-09-hook-sample.md docs/AI4SE_Lab_9_12_Alignment.md docs/FINAL_SUBMISSION_CHECKLIST.md README.md AGENT_LOG.md
git commit -m "docs: 增加Lab11 Hook示例"
```
