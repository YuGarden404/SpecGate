# AgentOS / Superpowers 对齐层实施计划

> **给执行智能体：** 使用 `superpowers:executing-plans` 按任务执行。该计划只做课程对齐文档和 Skill，不扩张核心 harness 能力。

**目标：** 为 SpecGate 增加 Lab 10 Skill 交付物和 Lab 9-12 对齐说明。

**架构：** 新增仓库内 `skills/specgate-static-html-harness/SKILL.md`，描述静态 HTML harness 的受控执行流程；新增 `docs/AI4SE_Lab_9_12_Alignment.md`，说明 Lab 9-12 的取舍；更新 README 和 AGENT_LOG 串联课程证据。

**技术栈：** Markdown、Superpowers Skill frontmatter、现有 unittest 和 mock demo。

---

## 文件结构

- 创建：`skills/specgate-static-html-harness/SKILL.md`
  - 记录 SpecGate 静态 HTML 任务的执行流程、工具边界、安全边界和验证方式。
- 创建：`docs/AI4SE_Lab_9_12_Alignment.md`
  - 对齐 Lab 9 MCP、Lab 10 Skill、Lab 11 Hook、Lab 12 AgentPack。
- 修改：`README.md`
  - 增加 AgentOS / Superpowers 对齐说明。
- 修改：`AGENT_LOG.md`
  - 记录本阶段人工决策和验证结果。

---

## Task 1：新增 SpecGate Skill

- [x] **步骤 1：用 skill-creator 初始化目录**

运行：

```powershell
python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\init_skill.py specgate-static-html-harness --path skills
```

- [x] **步骤 2：写入 Skill 主体**

写入 `skills/specgate-static-html-harness/SKILL.md`，内容包含：

- runtime 输入文件；
- context 选择规则；
- Tool Registry 允许工具；
- 安全边界；
- Gate 闭环；
- 验证命令。

- [x] **步骤 3：校验 Skill frontmatter**

运行：

```powershell
python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/specgate-static-html-harness
```

预期：校验通过。

---

## Task 2：新增 Lab 9-12 对齐文档

- [x] **步骤 1：写 Lab 取舍说明**

创建 `docs/AI4SE_Lab_9_12_Alignment.md`，说明：

- Lab 10 是本阶段实际接入方向；
- Lab 9 暂不做；
- Lab 11 和 Lab 12 放入后续方向；
- 当前 Mock LLM 为什么仍然有力支撑项目。

---

## Task 3：更新项目说明与日志

- [x] **步骤 1：更新 README**

在 README 中增加 AgentOS / Superpowers 对齐小节，链接 Skill 和 Lab 对齐文档。

- [x] **步骤 2：更新 AGENT_LOG**

追加本阶段记录，说明用户确认先不接入真实 LLM，先完成 Lab 10 Skill 和 Lab 对齐文档。

---

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

- [x] **步骤 3：检查状态并提交**

```powershell
git status --short
git add skills/specgate-static-html-harness/SKILL.md docs/AI4SE_Lab_9_12_Alignment.md docs/superpowers/specs/2026-07-09-agentos-alignment-design.md docs/superpowers/plans/2026-07-09-agentos-alignment.md README.md AGENT_LOG.md
git commit -m "docs: 增加Lab对齐与SpecGate技能文档"
```
