# SpecGate 最终使用文档与 v0.1.1 发布设计

## 1. 背景

PR #27 已合并到 `main@6dbaa75`，修复了 Windows 锁文件初始化与字节锁获取之间的跨进程竞态。教师式环境随后完成以下验证：

- NJU GitLab 空目录克隆与可编辑安装成功。
- Windows Python 3.13.5 完整套件为 `Ran 954 tests in 213.679s`、`OK (skipped=27)`，退出码 0。
- 独立工作区 Mock Demo 生成 `index.html`、`runs/latest/trace.jsonl` 与 `reports/latest/index.html`，退出码 0。
- NJU SE Hub `glm-5.2` 真实模型在 strict profile 下两步完成运行，Gate 通过、trust 为 `trusted`、解析错误为 0。
- 测试结束后，操作系统 keyring 中的真实模型凭据已清除。
- GitHub PR #27 合并后的 CI #67 与 Pages #38 成功；NJU GitLab Pipeline #313088 的 `unit-test` job #596503 成功。

当前材料仍把 PR #25、`main@44b236f`、947 项测试和 `v0.1.0` 作为“当前状态”。`v0.1.0` 镜像是有效且不可变的历史发布，但不包含 PR #27 的 Windows 修复。项目需要一次受控的文档同步和 `v0.1.1` 补丁发布，使源码、教师入口、过程材料和公开镜像重新一致。

## 2. 目标

本阶段完成以下目标：

1. 提供从空目录开始可执行的克隆、安装、测试和使用流程。
2. 清楚区分 Mock Demo、真实模型 CLI、本地 WebUI、Docker 和静态 Pages 的用途与边界。
3. 将教师已验证源码基线更新到 PR #27、`main@6dbaa75` 和 954 项测试，同时保留旧 PR、旧测试数字和 `v0.1.0` 为历史记录。
4. 将 Python 项目版本升级到 `0.1.1`，为不可变的 `v0.1.1` GHCR 发布做准备。
5. 发布完成后，用真实 Actions 链接、镜像 digest、匿名 pull 和截图完成第二次证据同步。
6. 保持 `REFLECTION.md` 的学生本人写作边界，不再扩写已达到 2499 个非空白字符的正文。

## 3. 非目标

本阶段不做以下工作：

- 不部署公网交互式 Web 后端。
- 不移动、删除或重建 `v0.1.0` 标签。
- 不覆盖 `v0.1.0` 的历史 digest 或截图。
- 不把真实模型或网络访问加入自动测试前提。
- 不修改 SpecGate 的 Agent loop、Gate、安全策略或 Web 运行行为。
- 不反向重写历史 `docs/superpowers/plans/`、历史审计或旧阶段完成记录。
- 不把发布前尚不存在的 GHCR run、digest 或截图写成已经完成。

## 4. 两阶段发布结构

### 4.1 阶段 A：v0.1.1 发布准备

阶段 A 在 `final-docs-v011-prep` 分支完成，并通过一个发布准备 PR 合并。

阶段 A 的状态表达必须同时包含：

- 教师已验证源码基线：PR #27、`main@6dbaa75`、954 项本地完整测试、CI #67、Pages #38、NJU Pipeline #313088。
- 当前已发布历史镜像：`v0.1.0`、原 digest 与原证据图片。
- 待执行发布：项目版本已准备为 `0.1.1`，但在标签 workflow 成功前不得声称 `v0.1.1` 镜像已经存在。

阶段 A 合并后，用户创建 annotated tag `v0.1.1` 并推送到 GitHub。现有 GHCR workflow 会校验 tag 与 `pyproject.toml` 版本完全一致，然后发布 `0.1.1`、`0.1`、`latest` 和 commit SHA 标签。

### 4.2 阶段 B：发布证据同步

只有 `v0.1.1` workflow 成功后才能开始阶段 B。阶段 B 使用独立分支和 PR，完成以下事实回填：

- GHCR workflow 的真实 run 链接和成功 job。
- `ghcr.io/yugarden404/specgate:0.1.1` 的不可变 digest。
- OCI revision 与发布 merge commit 的绑定关系。
- 空 Docker 配置下的匿名 pull、CLI help、Mock Demo 与 Web help 退出码。
- Package Public、GHCR workflow 和匿名 smoke 的新截图。
- `0.1` 与 `latest` 已指向 `v0.1.1` 发布的事实。

如果远端发布失败，阶段 B 记录真实失败原因并修复发布链，不把失败状态写成成功证据。

## 5. 信息架构与文件职责

### 5.1 README.md

README 是教师和普通用户的第一入口，按以下顺序组织：

1. 项目定位与公开入口。
2. GitHub 开发仓库和 NJU GitLab 课程镜像的职责与克隆地址。
3. Windows PowerShell 空目录快速开始：Python 要求、虚拟环境、安装、导入路径和 CLI help。
4. 工作区契约：CLI 必须使用 `TASK_SPEC.md` 与 `CHECKLIST.md`，可选已有 `index.html`。
5. Mock Demo：无需 API key，解释固定演示与任意真实任务的区别。
6. 真实模型：`specgate configure` 隐藏输入、NJU SE Hub 示例、`specgate run`、退出码、产物与凭据清除。
7. 本地 WebUI、Docker、Pages 和 GHCR 的独立用途。
8. 开发者测试、项目结构、核心机制和证据入口。

README 避免把教师命令散落在多个章节。详细服务器变量、白名单和持久化说明继续由 `docs/DEPLOYMENT.md` 负责。

### 5.2 docs/DEPLOYMENT.md

部署文档负责：

- 本地源码容器构建与 smoke。
- 已发布镜像的匿名使用方式。
- CLI 与 WebUI 的不同容器入口。
- API key、Web 主密钥、允许主机和持久化数据目录。
- “公开镜像不等于公网服务”的边界。
- 阶段 A 的 `v0.1.1` 待发布状态，以及阶段 B 的已验证 digest 状态。

### 5.3 docs/PROJECT_WALKTHROUGH.md

讲解稿提供一条 10 分钟内可执行的演示顺序：

1. 说明项目定位。
2. 展示 `TASK_SPEC.md` 与 `CHECKLIST.md`。
3. 运行 Mock Demo 并打开 HTML 与报告。
4. 展示 954 项完整测试证据。
5. 可选运行真实模型并解释凭据生命周期。
6. 展示最终证据矩阵、双仓库和公开分发边界。

### 5.4 最终事实材料

以下文件共同维护“当前事实”，必须由测试约束为一致：

- `docs/FINAL_EVIDENCE_MATRIX.md`
- `docs/FINAL_SUBMISSION_CHECKLIST.md`
- `docs/REFLECTION_FACT_CHECK.md`
- `PLAN.md` 的最新追加阶段
- `AGENT_LOG.md` 的最新追加阶段

旧章节保留旧 commit、PR、测试结果和 digest。新阶段只追加最新事实，不把历史数字全局替换为 954。

### 5.5 设计与实施记录

本设计保存在当前文件。实施计划另存为：

`docs/superpowers/plans/2026-07-19-final-docs-v011-release.md`

计划只描述本次阶段 A 的可执行步骤，并在结尾列出阶段 B 的远端证据门禁。

## 6. 版本与发布一致性

阶段 A 同步修改：

- `pyproject.toml`：项目版本 `0.1.1`。
- `src/specgate/__init__.py`：运行时版本 `0.1.1`。
- `tests/test_imports.py`：导入版本断言 `0.1.1`。

`.github/workflows/ghcr.yml` 已从 `pyproject.toml` 读取版本，并校验 push tag 为 `v<project_version>`，无需修改发布逻辑。工作流继续发布四类标签：完整版本、minor、latest 和 commit SHA。

阶段 A 文档不得把 `0.1` 或 `latest` 写成已经更新到 `v0.1.1`；该事实只能由阶段 B 的远端检查确认。

## 7. 测试策略

### 7.1 TDD 顺序

1. 先修改版本与最终证据契约测试，使其要求 `0.1.1`、PR #27、`main@6dbaa75`、954 项测试和新的教师流程。
2. 运行聚焦测试，确认因旧文档和旧版本声明而失败。
3. 最小修改版本声明和文档，使聚焦测试通过。
4. 运行导入、CLI、workflow 和最终证据测试。
5. 运行完整测试套件，记录实际总数、耗时、跳过数和退出码。
6. 用完整测试的真实结果刷新“当前最终验证”字段，再复跑证据测试和完整套件。

### 7.2 契约覆盖

`tests/test_final_evidence.py` 需要验证：

- 教师已验证源码基线只出现一次，且指向 PR #27 与 `main@6dbaa75`；阶段 A 的分支验证另行记录真实结果。
- 954 项教师验证作为已核验来源存在，但阶段 A 分支最终测试数字使用本阶段真实复跑结果。
- `v0.1.0` 只作为历史发布存在。
- 阶段 A 不声称 `v0.1.1` 已发布。
- README 包含克隆、虚拟环境、安装、工作区文件名、Mock、真实模型、凭据清除、WebUI 和 Docker 命令。
- 文档不包含明文 API key、token 或疑似 `sk-` 凭据。

阶段 B 再增加 `v0.1.1` run、digest、截图和匿名 smoke 的强绑定断言。

## 8. 凭据与隐私边界

- 文档只展示占位说明，不展示真实 API key。
- `specgate configure` 作为日常推荐路径，API key 通过隐藏输入进入系统 keyring。
- 自动化环境可使用 `OPENAI_COMPATIBLE_API_KEY`，但不得把真实值写入仓库、命令示例、trace、报告或截图。
- 教师真实模型 smoke 完成后应执行 `specgate credentials clear openai-compatible`。
- 新截图在提交前扫描 token、API key、账户敏感信息和本机无关隐私。

## 9. 验收条件

阶段 A 完成必须满足：

- 版本三处一致为 `0.1.1`。
- README 的空目录安装和工作区流程可由 Windows PowerShell 逐条执行。
- Mock 与真实模型路径明确分开，真实模型失败不降级的边界写清楚。
- 教师已验证源码基线更新到 PR #27，阶段 A 分支验证另行记录，历史 `v0.1.0` 证据保持完整。
- `PLAN.md`、`AGENT_LOG.md` 和三份最终事实材料使用一致的当前口径。
- 聚焦测试、完整测试、编译、JavaScript 语法、workflow 契约和空白检查全部通过。
- 不修改 `REFLECTION.md`，不触碰用户现有 stash，不执行用户保留的 Git 写操作。

阶段 B 完成必须满足：

- `v0.1.1` tag 指向发布准备 PR 的 merge commit。
- GHCR workflow 成功且 digest 已记录。
- 匿名环境的 pull、CLI help、Mock Demo 和 Web help 均退出码 0。
- 新证据图片存在、可解析、与文档引用一致且不含敏感信息。
- GitHub `main`、NJU GitLab `main` 和 `v0.1.1` 标签同步完成。
