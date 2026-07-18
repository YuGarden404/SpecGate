# 最终提交同步与双仓库交付设计

日期：2026-07-17
状态：已由用户分段确认

## 1. 背景

SpecGate 的 harness 内核、确定性 MockLLM 测试、真实 LLM 可选路径、凭据治理、Docker 本地构建、GitHub Actions 与静态 Pages 已完成。当前主线为 PR #23 合并后的 `main@5fd86fa`，但权威最终材料仍有部分内容停留在 PR #20 和 919 项测试快照；根 `PLAN.md` 与 `AGENT_LOG.md` 也尚未记录 PR #22、PR #23 和 NJU SE Hub 四模型验证。

课程通用要求同时要求通过 NJU Git 仓库链接提交，并保留 CI/CD 通过记录。当前开发历史只位于公开 GitHub 仓库 `YuGarden404/SpecGate`。本阶段需要在不破坏 GitHub PR/Actions 证据链、不代写学生反思、不提前声称公网部署或公开镜像完成的前提下，建立 NJU GitLab 课程镜像并同步最终材料。

## 2. 目标

1. 保留 GitHub 作为开发主仓库与 PR/Actions/Pages 权威证据源。
2. 建立 NJU GitLab 私有课程镜像，完整保留可达 commit、作者、时间、merge 历史与 tags。
3. 让 NJU GitLab 使用仓库现有 `.gitlab-ci.yml` 产生独立的 `unit-test` 和 `docker-build` Pipeline 证据。
4. 把最终快照同步到 PR #23、`main@5fd86fa`、最新 921 项完整回归和 NJU SE Hub 真实验证。
5. 为学生本人修订 `REFLECTION.md` 提供事实、字数与过期表述检查，不生成观点或替换段落。
6. 完成 GitHub、NJU GitLab、测试、Docker、截图、凭据和材料一致性的最终验收。

## 3. 非目标

- 不在本阶段部署公网交互式 Web 后端。
- 不在本阶段完成公开容器 registry 或发布 GHCR/其他公开容器镜像。
- 不把尚未收到的教师答复写成部署或 registry 豁免。
- 不修改 `src/specgate/` 生产代码或现有 UI。
- 不直接修改或代写 `REFLECTION.md` 正文。
- 不迁移、删除或重写 GitHub PR、Actions、Pages、Issues 或仓库历史。
- 不恢复已经删除的历史功能分支；已合并提交由 `main` 的 merge 历史保留。
- Agent 不执行任何 Git 命令；所有分支、remote、push、commit、PR 与 GitLab 操作均由用户执行。

## 4. 双仓库架构

### 4.1 仓库职责

| 仓库 | 职责 | 证据 |
| --- | --- | --- |
| GitHub `YuGarden404/SpecGate` | 开发主仓库 | commit、PR、Actions、Pages、评审记录 |
| NJU GitLab `SpecGate` | 课程提交镜像 | 完整 Git 历史、课程访问 URL、GitLab Pipeline |

本地继续保留 `origin` 指向 GitHub，并新增 `nju` remote 指向用户在 `git.nju.edu.cn` 创建的空项目。首次同步只推送 `main` 与 tags，避免旧本地分支触发大量 Pipeline 或在项目公开后暴露未合并内容；全部已合并 commit 和 merge 关系已经由 `main` 保留。后续固定采用“GitHub PR 合并 → 更新本地 `main` → 推送 `main` 与 tags 到 NJU GitLab → 核对两边最终 commit”的流程。

Git commit 对象不依赖托管平台，因此 SHA、作者、时间和父提交关系可以保留。GitHub PR 页面、评审对话和 Actions 运行记录属于 GitHub 平台元数据，不迁移到 GitLab；最终材料继续链接 GitHub 原始证据。GitLab 根据 `.gitlab-ci.yml` 运行新的 Pipeline，不把 GitHub Actions 的成功替代为 GitLab 成功。

### 4.2 可见性

NJU GitLab 项目初始设为 Private。私有阶段通过 NJU 登录或项目成员权限访问；课程检查前由用户改为 Public。公开前必须再次执行凭据扫描，并使用未登录浏览器确认项目 URL、默认分支和 Pipeline 证据可访问。

## 5. 学生反思边界

`REFLECTION.md` 的观点、案例选择、批判结论和最终文字继续由学生本人负责。Agent 只允许：

- 更新 `docs/REFLECTION_FACT_CHECK.md` 中的当前事实。
- 计算可复现的非空白字符数量并提示课程 1500–2500 字范围。
- 标出“未来 provider”等已经被真实四模型验证取代的过期事实。
- 提醒学生考虑 PR #22 假超时修复、双仓库取舍和教师部署答复。
- 在学生完成修改后运行字数与事实检查。

证据契约可以检查学生本人声明、字数范围和明确过期事实，但不得检查、生成或规定学生的主观评价。当前正文约 2877 个非空白字符，建议由学生压缩到 2200–2450 字，为 Markdown 标题和不同计数口径保留余量。

## 6. 权威证据同步

### 6.1 当前快照

权威材料应把当前主线更新为 `main@5fd86fa`，并增加以下已合并阶段：

| 阶段 | 功能或证据 commit | Merge commit | PR |
| --- | --- | --- | --- |
| 最终交付合规 | `e34452c` | `2082fc9` | #21 |
| LLM 连接测试超时修复 | `a5861aa` | `3905e1e` | #22 |
| NJU SE Hub 真实 LLM 审计 | `5635ad2` | `5fd86fa` | #23 |

PR #23 阶段已验证 921 项完整测试、27 项跳过；静态检查通过。历史 919、908、896 等数字继续作为对应阶段的真实记录保留，但不得继续标记为当前最终快照。

### 6.2 修改范围

- `docs/FINAL_EVIDENCE_MATRIX.md`：当前主线、PR #21–#23、最新测试、NJU SE Hub 审计、GitHub 与 GitLab 证据。
- `docs/FINAL_SUBMISSION_CHECKLIST.md`：双仓库职责、课程提交 URL、当前 CI/Pages、待教师答复的部署边界。
- `README.md`：GitHub 开发主仓库、NJU GitLab 课程镜像、私有/公开访问说明和 CI 边界。
- `PLAN.md`、`AGENT_LOG.md`：PR #22、PR #23、本阶段执行与人工 Git 边界。
- `docs/REFLECTION_FACT_CHECK.md`：学生需处理的最新事实与字数事项。
- `tests/test_final_evidence.py`：新的最终快照、双仓库、反思边界和截图契约。
- `docs/evidence/github-actions-pr23-final.png`：用户提供且经检查的 GitHub Actions 总览截图。
- `docs/evidence/gitlab-pipeline-final.png`：只在 NJU GitLab Pipeline 实际通过且用户提供合格截图后加入。

GitHub CI #59、Pages #34、NJU GitLab 项目和 Pipeline 的精确 URL 必须通过只读浏览或用户提供的页面核验，不能根据编号或路径猜测。GitLab 未创建、未同步或 Pipeline 未通过时，材料只能记录真实待处理状态。

## 7. TDD 与验证设计

先在 `tests/test_final_evidence.py` 写失败契约，要求：

- 当前快照包含 `main@5fd86fa`、PR #23 和 921 项测试。
- PR #21、#22、#23 的 commit/merge/PR 映射精确存在。
- 当前快照不再把 PR #20、`main@c39d101` 或 919 项测试写成最新结果。
- README 和最终材料明确区分 GitHub 主仓库、NJU GitLab 课程镜像、GitHub Actions 与 GitLab Pipeline。
- 反思正文保留学生本人声明、位于课程字数范围且不含明确过期最终事实。
- GitHub PR #23 截图存在、格式有效、被证据矩阵引用。
- 公网后端与公开 registry 在教师答复前仍保持待确认或待完成，不能提前写成完成。

红灯必须来自缺少新证据或学生尚未完成的人工内容，不得通过伪造 URL、Pipeline、截图或部署状态消除。用户完成 GitLab 同步和学生反思后，再最小更新材料使契约转绿。

最终验证包括：

1. 最终证据与工作流契约。
2. 六项课程确定性核心机制。
3. 完整 Python 测试套件。
4. `python -m compileall -q src tests`。
5. `node --check src/specgate/web_static/app.js`。
6. Docker build 与 WebUI entrypoint smoke。
7. 排除 fixtures、测试和实施计划后的疑似凭据扫描。
8. GitHub Actions、Pages、NJU GitLab Pipeline 与项目可访问性人工核验。

## 8. 外部操作与证据门禁

以下步骤必须由用户完成：

1. 在 NJU GitLab 创建空的私有 `SpecGate` 项目，不初始化 README、`.gitignore` 或 License。
2. 添加 `nju` remote，并只推送 `main` 与 tags。
3. 等待 GitLab `unit-test` 和 `docker-build` 均通过。
4. 提供不含 token、凭据或个人敏感信息的 GitLab 项目/commit 与 Pipeline 截图。
5. 完成 `REFLECTION.md` 本人修订。
6. 完成 GitHub PR，并在合并后把最终 `main` 同步到 NJU GitLab。
7. 检查前把 NJU GitLab 项目改为 Public，并使用未登录窗口复核。

任何外部步骤失败时都保持真实状态：

- GitLab push 失败时不写“镜像已同步”。
- Pipeline 失败时保留 job 与错误，不用 GitHub Actions 成功替代。
- 截图缺失或含敏感信息时不纳入仓库。
- 学生反思未完成时保持人工门禁，不由 Agent 代写。
- 教师尚未回复时不改变公网部署和公开 registry 的待定状态。

## 9. 完成标准

- GitHub PR/Actions/Pages 历史完整保留并可访问。
- NJU GitLab 包含与 GitHub 最终 `main` 相同的 commit，并有通过的 `unit-test` 与 `docker-build` Pipeline。
- 私有阶段访问边界和检查前公开步骤有明确说明。
- 最终证据矩阵、提交清单、README、PLAN 和 AGENT_LOG 使用同一当前快照。
- PR #21–#23、921 项测试和 NJU SE Hub 四模型审计映射完整。
- `REFLECTION.md` 由学生本人完成，并通过字数和事实检查。
- GitHub 与 GitLab 截图均已脱敏、被权威矩阵引用且来源可追溯。
- 完整测试、静态检查、Docker smoke 和疑似凭据扫描全部通过。
- 公网后端和公开 registry 状态继续与教师实际答复一致，不提前宣称完成。
