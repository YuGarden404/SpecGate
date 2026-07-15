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

- 当前已合并功能基线为 `main@8d30ca5`；真实 LLM Web 接入正在 `feat-real-llm-web-integration` 分支实施，提交、PR 与 CI 事实应在真实产生后由学生补充。
- 当前实现事实：Web 默认 Mock；API key、Base URL、Model 完整后新 run 使用真实模型；Provider 失败不会降级；课程自动测试仍使用 Fake/Stub 且不访问网络。
- PR #12 合并后一度出现 Pages 依赖失败，PR #13 修复；这是适合人工反思的“验证发现真实交付缺口”案例。
- 请学生本人核对全文是否满足课程要求的 1500–2500 字，并确认“AI 只参与润色和结构整理”的声明与实际使用方式一致。
