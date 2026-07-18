# REFLECTION.md 事实核对清单

> 本文件只帮助学生核对仓库事实，不提供可直接替换的反思段落。`REFLECTION.md` 的观点、案例选择、批判结论和最终文字必须由学生本人修改并确认。

## 1. 凭据与分发章节

- 过期事实：正文仍把 `credential_status()` 存根和 `.env fallback` 描述为最终实现。
- 当前事实：CLI 的进程环境变量只读且优先；持久化使用操作系统 keyring；Web 使用独立主密钥和 AES-256-GCM；SpecGate 不读写 `.env`。
- 请学生本人说明：安全凭据阶段如何改变了你对“mock 项目也要做凭据治理”的理解。

## 2. Subagent 工作流章节

- 需要限定时间范围：早期 MVP 确实主要使用 Gemini 冷启动验证；Context Harness Deepening 阶段后来使用了独立实现/规格/质量审查 agent；Gate/HITL 之后因当前协作规则和人工选择改为主线程 Inline Execution。
- 请学生本人判断：不同阶段的 agent 使用方式如何影响你对 subagent 边界的结论。

## 3. WebUI 与部署章节

- 过期事实：部分表述仍把 WebUI 等同于静态报告。
- 当前事实：仓库同时包含交互式 Web 产品壳和 GitHub Pages 静态展示；Web 产品壳具备项目导入、运行、审批、取消、Debug/Audit 与产物下载。
- 当前事实：GitHub Pages 不能保存服务端凭据或调用真实 Provider；真实模式需要部署 Web 后端、持久化数据库、AES-256-GCM 主密钥和网络白名单。
- 请学生本人决定是否补充：为何保留静态 Pages 作为低成本评审入口。

## 4. 上下文与主要贡献章节

- 过期事实：只描述 Context Manifest，没有覆盖后续 Select/Compress/Isolate、Prompt Injection Benchmark、Gate/HITL 和运行配置快照。
- 当前事实：治理是主要贡献；上下文深化和 Web 运行可靠性提供了可测的辅助证据。
- 请学生本人选择最能代表判断变化的一个案例，不要罗列所有功能。

## 5. 最终证据

- 截至 2026-07-17，当前主线为 PR #23 合并后的 `main@5fd86fa`；当前最终验证为 `Ran 921 tests in 403.030s`、`OK (skipped=27)`。
- PR #23 合并后的远端证据已核验：[CI #59](https://github.com/YuGarden404/SpecGate/actions/runs/29566219258) 的 `unit-test`、`docker-build` 与 [Pages #34](https://github.com/YuGarden404/SpecGate/actions/runs/29566219221) 的 `build-pages`、`deploy-pages` 均成功；列表截图为 `docs/evidence/github-actions-pr23-final.png`，两张详情截图也已归档。
- 当前实现事实：Web 默认 Mock；API key、Base URL、Model 完整后新 run 使用真实模型；Provider 失败不会降级；课程自动测试仍使用 Fake/Stub 且不访问网络。
- 历史证据继续保留：PR #20 合并后的 `main@c39d101` 对应 CI #53、Pages #31 与 `docs/evidence/github-actions-pr20-final.png`，状态均为已完成、已核验。
- 双仓库边界：SpecGate 是 CLI-first Harness；GitHub 开发主仓库保存 PR/Actions、Docker 构建与 Pages 历史，[NJU GitLab 课程镜像](https://git.nju.edu.cn/YuyuanLiang/specgate) 已创建为 Private。Pipeline #312781、#312784、#312797 的三次 `unit-test` 已通过；容器构建分别受 DinD privileged、`gcr.io` 超时和 RootlessKit `operation not permitted` 限制。GitLab CI 随后只保留 `unit-test`；[Pipeline #312806](https://git.nju.edu.cn/YuyuanLiang/specgate/-/pipelines/312806) 在 `main@66ea825` 上通过，[job #595758](https://git.nju.edu.cn/YuyuanLiang/specgate/-/jobs/595758) 记录 `Ran 926 tests in 33.684s`、`OK (skipped=18)`。GitLab Pipeline 已通过，检查前再改为 Public。
- 部署边界：GHCR 发布工作流已实现，远端公开性待验证；版本标签、Package Public 与匿名 pull 完成前，公开容器 registry 仍为待完成。公网交互式 Web 后端未部署，发布镜像不等于部署服务。
- PR #12 合并后一度出现 Pages 依赖失败，PR #13 修复；这是适合人工反思的“验证发现真实交付缺口”案例。
- 当前机械检查：全文为 2430 个非空白字符，位于 1500–2500 要求内。
- 当前事实检查：“未来 provider”已经改为 NJU SE Hub 四模型真实验证后的实际理解。
- 可选案例：PR #22 的连接测试假超时修复，或 GitHub/NJU GitLab 双仓库决策带来的判断变化。
- 教师未回复前，不得声称公网交互式 Web 后端已获豁免或已经完成；公开容器 registry 也必须等远端证据成立后才能改为已完成。
- 请学生本人确认“AI 只参与润色和结构整理”的声明与实际使用方式一致。
