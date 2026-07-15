# 最终交付材料与验证证据同步设计

日期：2026-07-15

## 1. 背景

SpecGate 已依次完成并合并 Gate/HITL 正确性、安全凭据、Web 运行时加固和 Runner 配置接线。当前 `main@f45e73a` 已包含上述实现，GitHub PR #15 合并后的 CI 与 Pages 均通过。

最后一个阶段 `docs-final-evidence-sync` 不再开发新功能，而是把课程要求、当前代码、确定性测试、机制演示、Git/PR 历史和 CI/Pages 证据整理为可复核、可追溯、可复现的最终材料。

现有材料存在以下需要同步的问题：

- `SPEC.md`、最终提交清单和讲解稿仍包含 `.env fallback` 等旧凭据描述。
- 部分材料仍把 WebUI 描述为仅静态报告，没有覆盖当前交互式 Web 产品壳。
- `PLAN.md` 和 `AGENT_LOG.md` 中最近阶段仍保留“等待用户回填”的 commit、PR 和 CI 状态。
- Web 固定 worker、有界队列、取消/超时/恢复和 schema v4 配置快照尚未形成统一的课程证据映射。
- `REFLECTION.md` 含有与当前实现不一致的早期事实，但课程要求反思必须由学生本人完成，Agent 不得代写观点。

## 2. 目标

- 建立一份课程要求到实现、测试、演示、Git/PR 和 CI 的权威证据矩阵。
- 同步所有最终评审入口，使其描述与当前 `main` 一致。
- 保存关键 GitHub Actions 截图，同时提供可点击的 PR/Actions 链接。
- 如实记录安全凭据阶段的 Pages 失败和后续热修复，不改写失败历史。
- 为文档一致性建立确定性自动检查，防止旧描述再次出现。
- 为学生提供 `REFLECTION.md` 事实核对清单，但不替学生改写反思正文。

## 3. 非目标

- 不修改任何生产代码行为。
- 不在材料阶段补做安全、运行时、Gate、HITL 或配置功能。
- 不接入或调用真实 LLM；最终验证继续使用 MockLLM/StubLLM。
- 不伪造无法由仓库、Git 历史、PR 页面、CI 页面或截图验证的结果。
- 不机械勾选根计划中所有历史步骤；完成状态使用阶段摘要、commit 和验证证据表达。
- 不实质改写 `REFLECTION.md` 的观点、案例或批判结论。

## 4. 事实来源与优先级

发生冲突时按以下顺序确定事实：

1. 当前 `main` 的生产代码和测试。
2. Git commit、merge commit 和分支历史。
3. GitHub PR、Actions、Pages 页面和保存的截图。
4. `AGENT_LOG.md` 中当时记录的本地验证输出。
5. 旧版说明文档。

旧文档不是当前行为的权威来源。发现冲突时必须修正文档，并在本阶段日志中记录修正内容和依据。

## 5. 权威证据矩阵

新增 `docs/FINAL_EVIDENCE_MATRIX.md`，作为最终证据账本。矩阵按课程要求组织，每项至少包含：

- 课程要求或核心机制。
- 当前状态。
- 实现文件。
- 确定性测试。
- 可复现命令或演示入口。
- 功能 commit。
- merge commit 和 PR。
- CI/Pages 或截图证据。
- 必要的边界说明。

证据链为：

```text
课程要求
→ 当前实现文件
→ 确定性测试
→ 可复现实验命令
→ 功能 commit
→ merge commit / PR
→ CI / Pages 截图或链接
```

矩阵覆盖至少以下类别：

- 自实现 Agent loop 和 MockLLM 抽象。
- Action/Tool Dispatcher。
- WorkspacePolicy、路径安全与快照保护。
- Checklist/Gate 反馈闭环。
- HITL 审批、revision/CAS、恢复和发布摘要绑定。
- Context Select/Compress/Isolate 与 benchmark。
- 安全凭据存储和旧 HMAC 迁移。
- Web 固定 worker、有界队列、取消、超时和重启恢复。
- schema v4 不可变运行配置快照。
- Trace、Debug、Audit 与静态报告。
- Docker、GitLab CI、GitHub CI/Pages 和公开 URL。
- Superpowers 过程证据、冷启动验证和人工评审边界。

## 6. Git、PR 和 CI 证据

最近四个阶段记录以下已验证映射：

| 阶段 | 功能 commit | Merge commit | PR |
| --- | --- | --- | --- |
| Gate/HITL 正确性 | `e17b8e5` | `f2b4e88` | #11 |
| 安全凭据 | `fecc5e3` | `80be31b` | #12 |
| Pages 依赖热修复 | `20c0102` | `73fbb34` | #13 |
| Web 运行时加固 | `e5fc981` | `49f66a2` | #14 |
| Runner 配置接线 | `a523137` | `f45e73a` | #15 |

保存两张无凭据内容的 Actions 截图：

```text
docs/evidence/github-actions-web-runtime-and-credentials.png
docs/evidence/github-actions-runtime-config.png
```

第一张截图保留安全凭据合并后 Pages 失败、PR #13 热修复成功，以及 PR #14 成功的历史；第二张截图记录 PR #15、合并后 CI 和 Pages 成功。没有独立截图的阶段使用 Git/PR 链接和最终 main CI 作为证据，不声称存在未保存的截图。

## 7. 文档同步范围

### 7.1 根目录材料

- `SPEC.md`：修正当前凭据、WebUI、运行时和配置模型；保留早期设计历史，但明确当前状态。
- `PLAN.md`：回填最近阶段的 commit、PR 和 CI，并新增本阶段完成摘要；不重写原始逐步计划。
- `AGENT_LOG.md`：回填用户完成 Git/PR 后的远端结果，追加最终证据同步过程。
- `SPEC_PROCESS.md`：记录最终材料审计、课程/PPT 对齐、人工确认和事实修正。
- `README.md`：强化最终评审入口、证据矩阵、复现命令和当前能力摘要。
- `REFLECTION.md`：本阶段不修改正文。

### 7.2 最终评审材料

- `docs/FINAL_SUBMISSION_CHECKLIST.md`：升级为当前完成状态和证据入口。
- `docs/PROJECT_WALKTHROUGH.md`：加入 Gate/HITL、凭据、Web runtime 和配置快照的当前讲解路径。
- `docs/AI4SE_Lab_9_12_Alignment.md`：修正凭据与当前产品边界，避免把早期 MVP 当成最终状态。
- `docs/DEPLOYMENT.md`：仅在发现与当前部署/凭据/并发配置不一致时同步。
- `docs/REFLECTION_FACT_CHECK.md`：新增学生本人修改指南。

## 8. 反思报告边界

`docs/REFLECTION_FACT_CHECK.md` 只包含：

- `REFLECTION.md` 中过期事实所在章节。
- 当前仓库可验证事实。
- 建议学生核对的问题。
- 课程“学生本人撰写、AI 仅可辅助润色”的提醒。

该文件不得给出可直接替换学生观点的完整段落，不评价学生应该得出什么结论，也不自动修改 `REFLECTION.md`。

## 9. 文档一致性测试

新增 `tests/test_final_evidence.py`，使用确定性测试验证：

- 权威证据矩阵、反思事实核对表和两张截图存在。
- README 包含课程要求的安装、运行、分发、安全边界、已知限制和评审入口。
- 证据矩阵包含 PR #11–#15、功能 commit 和 merge commit。
- 最终材料不再把 `.env fallback` 或 HMAC 描述为当前凭据存储方案。
- 最终材料描述固定 worker、有界队列、取消/超时/恢复和 schema v4 快照。
- 证据矩阵引用的关键实现与测试文件存在。
- `REFLECTION.md` 保留“学生本人完成”的作者边界声明。

测试只检查当前最终材料的确定性契约，不把历史日志中为了说明迁移而出现的 `.env`、HMAC 或旧 schema 视为错误。
最终差异审查另行使用 `git diff -- REFLECTION.md` 确认本阶段没有修改反思正文；单元测试不依赖 Git 工作区状态。

## 10. 复现与最终验证

本阶段最终执行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
python -m unittest discover -s tests
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
git status --short --branch
```

还要验证：

- 两张 PNG 可以读取且不包含凭据或本地私密路径。
- mock demo 命令可以在临时工作区复现，不污染仓库样例。
- 治理/HITL eval 和安全 benchmark 的说明命令与 CLI 当前参数一致。
- 最终变更只包含计划内文档、截图和文档一致性测试。

## 11. 错误处理与诚实边界

- 找不到独立截图时记录“未保留独立截图”，不补造图片。
- 无法取得精确 Actions run URL 时使用 PR 链接、workflow 页面和仓库截图，不编造 run ID。
- 历史测试数量保留当时记录；最终测试数量以本阶段重新运行结果为准。
- 发现文档声称完成但没有实现或测试证据时，必须降级状态或列为人工待办，不能仅补一句“已完成”。
- 发现生产缺口时停止材料同步并报告，不在 docs 分支偷偷补功能。

## 12. 验收标准

- `docs/FINAL_EVIDENCE_MATRIX.md` 可独立引导评审者定位每项重要能力。
- 当前行为与 `SPEC.md`、README、最终清单和讲解稿一致。
- PR #11–#15、关键 commit、merge commit 和远端状态可追溯。
- 两张 Actions 截图进入仓库并有文字说明。
- `.env fallback`、当前 HMAC、静态 WebUI-only 等过期描述已从最终材料修正。
- `REFLECTION.md` 保持学生所有，Agent 只交付事实核对表。
- 文档一致性测试、全量测试、编译、JavaScript 语法和差异检查通过。
- 没有生产代码变更，没有真实 LLM/网络作为自动验收前提，也没有虚构证据。
