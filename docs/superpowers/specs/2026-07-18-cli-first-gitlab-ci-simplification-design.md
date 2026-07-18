# SpecGate CLI-first 定位与 GitLab CI 收缩设计

日期：2026-07-18

## 1. 背景

SpecGate 的课程选题是 A 类 Coding Agent Harness。仓库原始 SPEC 将核心定义为 Python CLI harness，并以静态 HTML 生成与 Gate 修复闭环作为收窄后的 coding 领域。课程通用要求同时要求提供可访问的 WebUI URL，因此 CLI 与 Web 不是互斥关系。

NJU GitLab 共享 Runner 已连续暴露三类基础设施限制：

- Pipeline #312781：Docker-in-Docker 需要 privileged Runner。
- Pipeline #312784：Runner 拉取 `gcr.io` 的 Kaniko 镜像超时。
- Pipeline #312797：RootlessKit 创建 user namespace 时返回 `operation not permitted`。

三次 Pipeline 的 `unit-test` 均通过。Dockerfile 也已由 GitHub Actions 的 `docker-build` job 成功验证。

## 2. 决策

项目统一采用以下定位：

> SpecGate 是 CLI-first 的 Coding Agent Harness；WebUI 是课程要求的配套评审与演示入口，不是 Harness 内核。

现有 `specgate` CLI、Agent loop、Tool Registry、治理、Gate、上下文、记忆和 mock/stub 测试继续作为核心交付。现有 Web 代码不删除；README 和最终材料降低其产品叙事权重，并明确其职责是项目导入、配置、运行观察、审批和在线评审。

本阶段不新增 Claude Code 风格的交互式 TUI/REPL。当前子命令式 CLI 已满足核心运行入口；交互式终端体验属于可选后续增强。

## 3. CI 职责

### 3.1 GitHub Actions

- 每次 push 运行完整单元测试。
- 构建 Docker 镜像，证明容器分发路径可构建。
- 部署 GitHub Pages 静态评审入口。

### 3.2 NJU GitLab Pipeline

- `.gitlab-ci.yml` 只保留名为 `unit-test` 的 job。
- 安装项目、运行完整测试，并执行 `specgate --help` CLI smoke。
- 不再声明或尝试 Docker 构建，因为学校共享 Runner 不具备 DinD 或 rootless builder 所需权限。
- 新 Pipeline 通过前，材料状态保持“修复验证中”。

该分工满足通用要求中“GitHub Actions 在容器分发时构建镜像”“GitLab CI 包含 `unit-test` job”和“最后一次 CI/CD 必须 pass”的不同职责，不用 GitHub 成功伪装 GitLab 成功，也不重复尝试已证实不兼容的 Runner 构建方案。

## 4. 证据与文档

新增并归档 Pipeline #312797 列表与 BuildKit 权限失败截图。最终材料保留三次失败的时间线，并说明：

- Dockerfile 与 Docker 构建由 GitHub Actions 成功证据覆盖。
- GitLab 仅验证课程要求的 `unit-test` job。
- WebUI 保留为配套入口；SpecGate CLI 是核心产品与主要使用方式。
- 不在新 Pipeline 产生前声称 GitLab 已通过。

需要同步的材料包括 `SPEC.md`、`README.md`、最终证据矩阵、最终提交清单、反思事实核对、`PLAN.md` 与 `AGENT_LOG.md`。

## 5. 测试策略

先修改契约测试并确认 RED：

- `.gitlab-ci.yml` 必须只包含 `unit-test`，不得再包含 `docker-build`、DinD、Kaniko 或 BuildKit。
- `unit-test` 必须执行完整测试和 `specgate --help`。
- 最终材料必须记录 Pipeline #312797、`operation not permitted`、CLI-first 定位和 GitLab CI 职责收缩。
- 两张新 PNG 必须存在、可解析并在证据矩阵中引用。

随后做最小配置与材料修改并验证 GREEN。真实成功只由推送后新产生的 NJU GitLab Pipeline 证明。

## 6. 非目标

- 不删除 Web 实现或 Web 测试。
- 不新增交互式 TUI/REPL。
- 不改 Harness 核心运行语义。
- 不部署公网后端、不发布公开容器镜像。
- 不尝试第四种 GitLab 容器构建器。

## 7. 验收标准

- 本地工作流和最终证据测试通过。
- `.gitlab-ci.yml` 可被 YAML 解析，且只定义 `unit-test` job。
- README 与 SPEC 首先把 SpecGate 描述为 CLI-first Harness。
- 三次 GitLab 失败均被如实保留。
- 推送后的最新 NJU GitLab Pipeline 为 pass，之后再补录成功 URL 与截图。
