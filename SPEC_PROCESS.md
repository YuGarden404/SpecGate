# SpecGate 规约过程记录

## 1. 过程概览

本文档记录 SpecGate 设计如何通过 Superpowers 风格流程产生：先 brainstorming，再写 `SPEC.md`，再写 `PLAN.md`，再做冷启动验证，最后才进入实现。

截至 2026-07-07：MVP 边界已经确认，课程要求已经重新阅读，初版 `SPEC.md` 已写入。实现代码尚未开始。

## 2. 关键 brainstorming 迭代

### 第 1 轮：理解课程资料

先阅读了 `D:\code\NJU\AI4Coding\docs` 中的 AI4SE 课程资料。核心结论是：期末项目不是考“AI 能不能写代码”，而是考学生能不能设计工程机制来控制 AI 写代码。

决策：

- 选择 A 类 `Coding Agent Harness`，因为它是课程首选方向，也最贴合 Prompt / Context / Harness Engineering 主线。

### 第 2 轮：区分 A 类和 B 类

对 A 类和 B 类做了澄清：

- A 类重点是 harness core：loop、tools、guardrails、memory/context、feedback、config、deterministic tests。
- B 类重点是应用产品；如果 B 类里有 agent 部分，该 agent 部分仍需遵守 A 类边界。

决策：

- SpecGate 是 A 类项目。
- 不能用 LangChain AgentExecutor、AutoGen、CrewAI、LangGraph 或宿主 coding agent runner 作为交付物核心。

### 第 3 轮：确定 MVP 边界

比较多个可能范围后，最终 MVP 定为：

```text
Python CLI harness + mock LLM + 静态 HTML 生成/修复
+ Checklist/Gate 反馈闭环 + 静态 Web 报告
```

明确排除：

- 不开放 shell。
- 不做 Playwright。
- 不做复杂前端。
- 不做实时 dashboard。

决策：

- 主要贡献聚焦在确定性 Checklist/Gate 反馈闭环，而不是 UI 复杂度或广泛工具访问。

### 第 4 轮：重新核对期末要求

2026-07-07 重新阅读了通用要求和 A 类要求。设计因此补充了：

- 凭据威胁模型。
- Docker 分发。
- 通过 Pages 提供静态 WebUI URL。
- `.gitlab-ci.yml` 中必须有 `unit-test` job。
- mock LLM 确定性测试。
- 机制演示：guardrail 拦截、反馈驱动修复、主贡献机制行为。
- 实现前进行冷启动验证。

## 3. 采纳的 AI 建议

- 用静态 HTML 任务缩小范围，使反馈可以确定性检查。
- WebUI 做成静态报告，而不是 live dashboard。
- `MockLLM` 作为主要验证路径。
- MVP 不开放 shell，使安全边界更清晰。
- 把 Checklist/Gate 作为主贡献维度。

## 4. 拒绝或后置的 AI 建议

- 浏览器自动化后置，因为 Playwright 会扩大范围。
- 通用 coding agent 被拒绝，因为它会削弱重点机制并增加安全风险。
- 复杂前端 dashboard 被拒绝，因为课程只要求可访问 WebUI，静态报告足够。
- shell 执行被排除出 MVP，因为它是最高风险工具类别，且不是静态 HTML Gate 演示所必需。

## 5. 冷启动验证计划

在正式实现前，需要让另一个不同类型的 agent 只读取 `SPEC.md` 和 `PLAN.md`，尝试完成 1-2 个小任务。它遇到不清楚的地方必须暂停提问，而不是猜测实现。

后续需要在这里记录：

- 第二个 agent 在哪里暂停。
- 它暴露了哪些 SPEC / PLAN 缺陷。
- 它做出了哪些与原意不一致的解读。
- 根据反馈对 `SPEC.md` / `PLAN.md` 做了哪些修订。

冷启动验证已于 2026-07-08 由 Gemini 3.5 思考完成。验证对象只包含 `SPEC.md` 和 `PLAN.md`。

验证结论：

- `SPEC.md` 与运行时输入 `TASK_SPEC.md` 的边界清晰。
- Task 2 Action parser 可以按红-绿步骤直接执行。
- Task 3 Workspace Policy / Guardrail 可以按计划执行。
- Windows PowerShell 的测试命令可执行。

暴露的问题：

- `PLAN.md` Task 3 中后三个测试使用 `Path.cwd()`，虽然能运行，但测试隔离性不如 `tempfile.TemporaryDirectory()`。
- `SPEC.md` 第 9.1 节描述了完整 `credentials set/status/clear` 交互，而 `PLAN.md` Task 10 的 MVP 实现只做 `credential_status` fail-closed 存根，范围精细度需要对齐。

处理决策：

- 采纳 Task 3 测试隔离建议，统一使用临时目录。
- 采纳凭据范围说明建议，在 `SPEC.md` 明确 MVP 只要求凭据状态存根和 fail-closed 行为，完整 keyring CLI 属于后续扩展。

## 6. 当前自检

- 还没有在 SPEC 之前写实现代码。
- 当前 `SPEC.md` 已包含 A 类额外要求：“领域与机制设计”。
- 当前 `SPEC.md` 已把课程要求映射成具体机制。
- `PLAN.md` 已写入，已经把实现拆成 TDD 小任务，并明确每个任务的验证步骤。

## 7. 语言调整记录

2026-07-07 根据人工反馈，将主要说明文档从英文改为中文。保留文件名、命令名、JSON 字段、模块名和测试 job 名称等英文标识，避免影响后续 LLM 和自动化处理。

## 8. SPEC 命名澄清

2026-07-07 根据人工反馈，澄清两类 SPEC：

- 根目录 `SPEC.md` 是课程交付物，描述 SpecGate harness 本身。
- harness 运行时的 HTML 任务输入不再叫 `SPEC.md`，改名为 `TASK_SPEC.md`，并和 `CHECKLIST.md` 一起放在示例任务目录中。

这样可以避免把“项目设计文档”和“被 harness 处理的 HTML 任务设计”混在一起。

## 9. PLAN 写入记录

2026-07-07 写入实现计划：

- 根目录课程交付物：`PLAN.md`。
- Superpowers 计划证据：`docs/superpowers/plans/2026-07-07-specgate-mvp.md`。

计划按以下模块拆分：

- 项目骨架与测试入口。
- Action parser。
- Workspace policy 与 guardrail。
- 文件工具与 dispatcher。
- 静态 HTML Gate。
- Trace store 与 context builder。
- `MockLLM` 与 `AgentRunner` 主循环。
- 静态报告生成。
- CLI、示例 `TASK_SPEC.md`、端到端 mock demo。
- 凭据边界、Docker、CI 与最终文档。

计划自检结果：

- 覆盖 `SPEC.md` 中的 A 类 harness 核心机制。
- 明确 `TASK_SPEC.md` 是 harness 运行输入。
- 明确 `.gitlab-ci.yml` 必须包含 `unit-test` job。
- 保留冷启动验证作为实现前下一步。

## 10. MVP 实现记录

2026-07-08 按 `PLAN.md` 完成 Task 1 到 Task 10 的 MVP 实现。

已完成：

- Python 包骨架与 unittest 入口。
- 严格 JSON `Action` 解析。
- workspace guardrail 与白名单文件工具。
- 静态 HTML Gate 与 Checklist 检查。
- trace 记录、密钥样文本脱敏与 context pack。
- `MockLLM` 与 `AgentRunner` 主循环。
- 静态报告生成。
- CLI mock demo 与示例任务 `examples/knowledge_nav`。
- 凭据 fail-closed 边界。
- Dockerfile 与 `.gitlab-ci.yml` 的 `unit-test` job。
- `REFLECTION.md` 人工反思结构。

验证方式：

- 每个实现任务均先写失败测试，再补最小实现。
- 最终全量测试使用 `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v`。
- mock demo 使用 `python -m specgate.cli run-mock-demo examples/knowledge_nav`。
- Docker 由用户在本机 PowerShell 使用代理环境变量完成 `python:3.11-slim` 拉取、`specgate:local` 镜像构建和容器运行验证。

远端发布记录：

- GitHub Actions CI 已通过。
- GitHub Pages 已通过 Actions 部署。
- WebUI 首页：`https://yugarden404.github.io/SpecGate/`。
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`。
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`。
# 2026-07-10 Context Harness Deepening 过程记录

本轮 brainstorming 的目标是确定 SpecGate 在 HITL Review Gate 之后的继续深入方向。人工首先指出项目不应继续陷入真实 LLM 性能比较，而应回到“小 Codex 产品”的 harness 能力建设。随后把候选方向收束为 Context Engineering 与 Harness Engineering 的主线。

关键决策：

- 采用一条大分支 `feat-context-harness-deepening` 连续推进。
- 采用阶段化方案 A，而不是一次性大改或先做 benchmark 再反推机制。
- 阶段顺序为 Select / RAG Harness -> Explainable Select -> Compress Lifecycle -> Isolate + Benchmark。
- 根目录 `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md` 重新纳入持续维护范围，作为课程最终交付证据。
- 所有核心验收以 mock/stub LLM 为主，真实 LLM 只作为后续可选人工实验。

本轮重新参考了课程通用要求、A 类 Coding Agent Harness 要求和 `pecehe-with-notes.pptx`。课件中 PE ⊂ CE ⊂ HE、Write/Select/Compress/Isolate、Agent = Model x Harness、Workflow 优先、先减法再加法等原则，被映射为本轮设计约束：先实现轻量可测机制，不引入向量库、真实并发沙箱或真实 LLM 评测主线。

## 2026-07-10 Context Harness Deepening 计划记录

## 2026-07-10 Task 7 Mock Eval Cases 过程记录

Task 7 将前面已经实现的 Select、Compress、Isolate、Benchmark 机制落到可复现的 mock eval cases 上。新增 case 均不依赖真实 LLM、网络、向量库或外部 agent runner。

新增样例：

- `examples/eval_cases/retrieval-context-select`
- `examples/eval_cases/context-compression-lifecycle`
- `examples/eval_cases/isolation-role-boundary`

文档同步更新 `README.md`、`SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md` 和 `AGENT_LOG.md`。核心原则保持不变：真实 LLM 只作为后续可选人工实验，课程验收以 mock/stub LLM 和确定性测试为准。

Task 7 审查与修正：
- 规格审查确认三个新增 case 和文档基本满足要求，但指出 `examples/eval_cases/eval-runs/` 运行产物需要防误提交。
- 质量审查确认新增 case 均走 `MockLLM`，不依赖网络或真实 LLM；同时建议把“验证策略能力”的措辞收窄为“展示/记录 evidence”。
- 已在 `.gitignore` 增加 `examples/eval_cases/eval-runs/`，并更新 README / SPEC 对运行产物和 evidence 的说明。

Task 7 验证结果：
- `python -m specgate.cli eval examples/eval_cases --context-strategy rag-select`：`cases=7, expected_matches=7`
- `python -m specgate.cli eval examples/eval_cases --context-strategy compressed-rag`：`cases=7, expected_matches=7`
- `python -m specgate.cli eval examples/eval_cases --context-strategy isolated-harness`：`cases=7, expected_matches=7`
- `python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness`：`strategies=4, cases=7`
- `python -m unittest discover -s tests -v`：`Ran 190 tests ... OK`

## 2026-07-15 最终材料审计与证据同步过程

本阶段没有修改运行时行为，而是把 `main@f45e73a` 的当前事实同步到课程交付材料，并用文档契约测试防止最终提交再次退回旧描述。

brainstorming 与人工决策形成四项明确结论：

1. 材料审计发现 `.env fallback`、静态 WebUI-only 和“等待远端回填”等表述已不符合当前 `main`。
2. 人工选择“权威证据矩阵 + 仓库内原始 Actions 截图”，没有只贴外部链接，也没有全面重写历史材料。
3. 人工要求 `REFLECTION.md` 保持学生所有；Agent 只新增事实核对清单，不提供可直接替换的反思段落。
4. 课程/PPT 中“目标定义、测试基础设施、PR 审查、文档同步”和“真实记录失败→修复”的 Harness 观念被落实为本阶段验收规则。

实现采用 Superpowers `executing-plans` 和 TDD：先新增 `tests/test_final_evidence.py`，确认它因缺少矩阵、截图、README 章节及当前安全/运行时描述而 RED，再逐项同步材料至 GREEN。由于本阶段没有生产代码行为变化，测试对象是课程文档与证据之间的确定性契约，而不是新增运行时代码。

远端证据链统一记录于 `docs/FINAL_EVIDENCE_MATRIX.md`：PR #11–#15 对应 Gate/HITL、安全凭据、Pages 热修复、Web Runtime 和 Runtime Config。PR #12 合并后的 Pages 失败与 PR #13 修复均被保留，避免用最终绿色状态覆盖真实工程过程。

在规格确认后，使用 Superpowers `writing-plans` 将大工程拆分为 8 个可执行任务。计划保存到 `docs/superpowers/plans/2026-07-10-context-harness-deepening.md`，并同步在根目录 `PLAN.md` 追加摘要。

计划设计原则：

- 不并行派发实现任务，因为多个任务会共同修改 `context.py`、`metrics.py`、`report.py`、`cli.py` 和 `eval_runner.py`。
- 每个任务都以失败测试开头，再写最小实现，再跑聚焦测试和完整测试。
- 所有新增机制以 mock/stub LLM 或纯单元测试验证。
- 最终 benchmark 比较 harness strategy，而不是比较真实 LLM 能力。

## 2026-07-10 Task 8 Final Review 过程记录

冷启动/审查记录：
- Task 7 的规格审查子代理只拿到任务说明和文件范围，没有依赖本对话历史；它能定位到 `eval-runs/` 运行产物误提交风险。
- Task 7 的质量审查子代理同样只做只读审查；它确认新增 case 都走 `MockLLM`，并指出文档措辞应从“验证策略能力”收窄为“展示/记录 evidence”。
- 上述两个问题均已修复在 `8a602cb`：`.gitignore` 忽略 `examples/eval_cases/eval-runs/`，README / SPEC 同步更新。

最终验证范围：
- 单元测试：`python -m unittest discover -s tests -v`
- Harness benchmark：`python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness`
- Git 状态：确认只剩 `.env`、`eval-runs/`、缓存等 ignored 本地文件。
