# SpecGate v0.3.0 发布证据同步设计

日期：2026-08-02  
状态：用户已通过创建 `v030-release-evidence` worktree 确认

## 1. 背景

SpecGate v0.3.0 已由 PR #32 合并到 `main@e3ec022`，标签、GitHub Release、CI、Pages 和 GHCR 均已产生可验证的公开事实。公开镜像已在一次性空 Docker 配置下完成匿名拉取、CLI help、Mock Demo、Web help、RepoDigest、OCI revision 和 OCI version 验证。

仓库当前发布材料仍把 v0.2.0 写成“当前发布”。本阶段需要将 v0.3.0 提升为当前发布，同时保留 v0.2.0、v0.1.1 和 v0.1.0 的历史证据。

## 2. 目标

1. 归档 v0.3.0 GHCR workflow、workflow summary 和 GitHub Release 三张截图。
2. 在用户入口、部署说明、交付矩阵、提交清单、项目讲解和事实核对中统一当前发布事实。
3. 记录精确的 PR、commit、Actions run、镜像 digest 和 OCI 标签。
4. 通过最终证据测试约束截图完整性、当前发布一致性和历史保留。
5. 记录完整验证的实际输出，不预写测试结果。

## 3. 非目标

- 不修改 `src/specgate/**`、CLI、Shell、Web、Dockerfile 或 workflow 行为。
- 不删除或重写 v0.2.0、v0.1.1、v0.1.0 的历史证据。
- 不声称公网交互式 Web 后端已经部署。
- 不声称 DeepSeek V4 Pro 兼容；已验证的真实模型仅为 `deepseek-v4-flash`。
- 不把 NJU GitLab 写成已同步；既有外部 TLS/网络阻塞事实继续保留。
- Agent 不执行暂存、提交、推送、PR 或分支清理。

## 4. 已核验事实

- PR：#32
- 当前源码：`main@e3ec022`
- 完整 commit、tag peeled commit、OCI revision：`e3ec02236f6e65ccce2c49ab444ba0676db5a7ed`
- Release：<https://github.com/YuGarden404/SpecGate/releases/tag/v0.3.0>
- CI #77 / run `30728989649`
- Pages #43 / run `30728989651`
- GHCR #4 / run `30729409707`
- 镜像：`ghcr.io/yugarden404/specgate:0.3.0`
- RepoDigest：`sha256:baa5c61bd791f2b5e266e98fbd17affb1e9e6fd6dab6e829279a05d934f021e0`
- OCI version：`0.3.0`

GitHub 公共 API 显示 Release 不是 draft 或 prerelease，三个 Actions run 均为 `completed/success`，且 head SHA 与当前 commit 一致。

## 5. 证据结构

新增截图：

- `docs/evidence/github-actions-ghcr-v0.3.0-success.png`
- `docs/evidence/github-actions-ghcr-v0.3.0-summary.png`
- `docs/evidence/github-release-v0.3.0.png`

当前发布事实同步到：

- `README.md`
- `SPEC.md`
- `PLAN.md`
- `AGENT_LOG.md`
- `docs/DEPLOYMENT.md`
- `docs/FINAL_EVIDENCE_MATRIX.md`
- `docs/FINAL_SUBMISSION_CHECKLIST.md`
- `docs/PROJECT_WALKTHROUGH.md`
- `docs/REFLECTION_FACT_CHECK.md`

`tests/test_final_evidence.py` 先增加 v0.3.0 契约并观察失败，再更新文档和截图使其通过。测试约束稳定事实，不锁定自然语言排版。

## 6. 验收标准

1. 三张新增 PNG 通过签名、chunk、CRC、zlib、IEND 和最小尺寸检查。
2. 当前发布材料包含全部 v0.3.0 精确事实。
3. v0.2.0、v0.1.1 和 v0.1.0 继续作为历史发布存在。
4. 过期的 v0.2.0“当前发布”措辞不再出现在当前事实区。
5. 聚焦测试、最终证据套件、三项机制演示、`compileall`、`git diff --check` 和完整离线套件通过。
6. 最终 diff 不包含 `src/specgate/**`、workflow、`REFLECTION.md` 或运行产物。
