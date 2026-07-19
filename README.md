# SpecGate

SpecGate 是 AI4SE 期末项目的 A 类选题：一个从零实现、以 GitHub 为开发主仓库的 CLI-first `Coding Agent Harness`。

`specgate` CLI 与自行实现的 Harness 内核是核心产品。它使用可注入的 `MockLLM`，围绕静态 HTML 生成/修复任务运行 Checklist/Gate 反馈闭环，并生成静态 Web 报告；WebUI 是课程要求的配套评审与演示入口，不替代 Agent loop、工具、治理或 Gate。

## 评审快速入口

- 最终提交清单：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 最终证据矩阵：`docs/FINAL_EVIDENCE_MATRIX.md`
- 反思事实核对：`docs/REFLECTION_FACT_CHECK.md`（由学生本人修改 `REFLECTION.md`）
- 项目讲解稿：`docs/PROJECT_WALKTHROUGH.md`
- Lab 9-12 对齐说明：`docs/AI4SE_Lab_9_12_Alignment.md`
- SpecGate Skill：`skills/specgate-static-html-harness/SKILL.md`
- 公开静态评审首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`

仓库交付采用双仓库分工：GitHub 是开发主仓库，保留完整 commit、PR、GitHub Actions、Docker 构建与 Pages 证据；[NJU GitLab 课程镜像](https://git.nju.edu.cn/YuyuanLiang/specgate) 是公开可克隆的课程检查入口，运行 `unit-test` Pipeline。GitHub 平台的 PR/Actions 元数据不会迁移到 GitLab，两个仓库只同步源码与 Git 标签。

课程检查优先从 NJU GitLab 克隆：

```powershell
git clone https://git.nju.edu.cn/YuyuanLiang/specgate.git SpecGate
cd .\SpecGate
```

需要查看 GitHub PR、Actions 和 Pages 发布链时，从开发主仓库克隆：

```powershell
git clone https://github.com/YuGarden404/SpecGate.git SpecGate
cd .\SpecGate
```

推荐评审顺序：先看最终提交清单，再看项目讲解稿，然后运行本地测试或打开公开报告。

## 两类 SPEC

这里有两个层级，不能混在一起：

- 根目录 `SPEC.md`：课程要求的项目设计文档，说明 SpecGate 这个 harness 项目要做什么。
- 示例任务里的 `TASK_SPEC.md`：SpecGate 运行时读取的 HTML 任务输入，说明这一次要生成什么页面。

也就是说，我们要交付的是 SpecGate harness；harness 的 demo 输入会是类似 `examples/knowledge_nav/TASK_SPEC.md` + `CHECKLIST.md` 的 HTML 设计任务。

## MVP 边界

包含：

- 自实现 agent loop。
- `MockLLM`。
- 严格 JSON Action Protocol。
- 白名单文件工具。
- 确定性 guardrail。
- 静态 HTML Gate。
- 失败反馈驱动的修复闭环。
- 静态 Web 报告。

不包含：

- 不开放 shell。
- 不做 Playwright。
- 不做复杂前端。
- 不使用现成 agent framework 作为 harness core。

## 课程交付物

本仓库最终需要包含：

- `SPEC.md`
- `PLAN.md`
- `SPEC_PROCESS.md`
- `README.md`
- `AGENT_LOG.md`
- `REFLECTION.md`
- 源代码和 mock-LLM 单元测试
- `.gitlab-ci.yml`，其中包含 `unit-test` job
- Docker 本地与 CI 构建文件
- 静态 Web 报告部署 URL

## 当前状态

- 自实现 Agent loop、Action/Tool、Gate 反馈和 MockLLM 确定性闭环。
- Workspace 路径安全、HITL revision/CAS、最终 Gate 和发布摘要绑定。
- Select/Compress/Isolate 上下文策略与安全 benchmark。
- OS keyring、Web AES-256-GCM 和旧 HMAC `requires_reentry` 迁移。
- 固定 worker、有界队列、取消、超时和重启恢复。
- schema v5 的 `runtime_config_json` / `llm_config_json` 不可变配置快照与 Debug/Audit 脱敏展示。
- Web 默认使用 MockLLM；API key、Base URL、Model 完整后，新 run 可使用 OpenAI-compatible 真实模型，失败不会降级到 Mock。
- Docker 本地与 GitHub Actions 构建、GitLab `unit-test`、GitHub Pages 和公开静态评审入口；NJU GitLab unit-test-only Pipeline 已通过；GHCR 公开镜像已完成匿名拉取验证；公网交互式 Web 后端未部署。

## 安装

要求 Python 3.11 或更高版本。在刚克隆的仓库根目录执行：

```powershell
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -c "import specgate.workspace_fs as m; print(m.__file__)"
specgate --help
```

导入检查打印的路径必须位于当前克隆目录。提示符已经显示 `(.venv)` 时不要再次运行 `python -m venv .venv`；如需重建环境，应先退出并删除旧环境，再重新创建。课程自动验收和 Mock Demo 不需要 API key。CLI 可选真实 provider 的安全配置见“CLI 凭据管理”，Web 主密钥见“Docker / 服务器部署”。

## Mock Demo

每个可移植 CLI 工作区必须包含名称完全一致的 `TASK_SPEC.md` 和 `CHECKLIST.md`。`index.html` 是可选输入：已有文件时 SpecGate 可以修复它；没有时可以新建；运行完成后它是最终产物。以下命令使用固定、确定性的知识图谱响应验证 Harness，不调用真实模型：

```powershell
$Workspace = Join-Path $env:TEMP "specgate-teacher-demo"
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
Copy-Item .\examples\knowledge_nav\TASK_SPEC.md $Workspace -Force
Copy-Item .\examples\knowledge_nav\CHECKLIST.md $Workspace -Force
specgate run-mock-demo $Workspace
```

成功后检查三个输出：

```powershell
Get-Item (Join-Path $Workspace "index.html")
Get-Item (Join-Path $Workspace "runs\latest\trace.jsonl")
Get-Item (Join-Path $Workspace "reports\latest\index.html")
```

验收时应同时确认命令退出码为 0、最终 Gate 通过、trust 状态为 `trusted`，并确认 `parse_errors=0`。`run-mock-demo` 的任务内容是固定的，因此适合离线回归 Harness；要生成任意任务，必须配置真实 provider 后使用 `specgate run`。

## 目录结构

```text
src/specgate/                 自实现 harness、Web 服务与安全原语
tests/                        MockLLM 和确定性机制测试
examples/knowledge_nav/       可重复运行的 mock demo
examples/eval_cases/          治理、注入、上下文和 HITL eval cases
docs/superpowers/             设计与实施计划
docs/evidence/                最终 CI/Pages 截图证据
skills/                       SpecGate 可复用 Skill
.github/workflows/            GitHub CI 与 Pages
```

## 本地测试

```powershell
python -m unittest discover -s tests
```

## 真实模型运行

首次使用 OpenAI-compatible provider 时执行交互式配置。Base URL 与 Model 保存到用户配置；API key 通过隐藏输入保存到操作系统 keyring，不写入仓库或配置文件：

```powershell
$Workspace = Join-Path $env:TEMP "specgate-teacher-demo"
if (-not (Test-Path (Join-Path $Workspace "TASK_SPEC.md"))) {
  throw "请先执行 Mock Demo 章节创建工作区"
}
specgate configure
specgate credentials status openai-compatible
specgate run $Workspace --max-steps 5 --timeout 120 --governance-profile strict
specgate credentials clear openai-compatible
```

`https://njusehub.info/v1` 与 `glm-5.2` 是 2026-07-19 已完成两步 smoke 的示例组合，不是硬编码默认值，也不应把 API key 写入文档、命令历史或 trace。Provider 调用失败时 SpecGate 会失败关闭，不会降级到 MockLLM。

PowerShell 5.1 的控制台可能用错误编码显示 trace 中的中文；文件本身仍是 UTF-8，应显式读取：

```powershell
Get-Content -Encoding UTF8 `
  (Join-Path $Workspace "runs\latest\trace.jsonl") `
  -Tail 10
```

## 治理指标

SpecGate 会在 `runs/latest/trace.jsonl` 和 `reports/latest/index.html` 中记录治理证据，包括 `llm_calls`、`tool_calls`、`blocked_actions`、`parse_errors`、`gate_runs`、是否触达 `max_steps_reached`，以及每一次 permission decision 的 action、path、allowed/blocked、reason、profile 和 rule family。报告还会汇总 trust summary，状态为 `trusted`、`warning` 或 `failed`。

可以显式选择治理配置：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav --governance-profile strict
```

`review` profile 只用于记录审计证据和报告标签，不会绕过 allowlist、路径边界或 snapshot 保护。

### HITL 审批恢复闭环

SpecGate 支持 mock-first 的人工审批流程。高风险 action 在 `review` profile 下不会直接执行，而是写入 `runs/latest/pending_approvals.json`；人工可以列出、批准或拒绝审批项，再用 `resume` 继续运行。对应 trace 会记录 `approval_requested`、`approval_applied`、`approval_rejected` 或 `approval_failed` 等事件，静态 report 会显示 Approval History，便于审计审批生命周期。

审批队列带有单调递增的 `revision`。Web 端执行 approve / deny 时必须提交当前 `expected_revision`；若其他页面或进程已经更新队列，旧 revision 会返回 `409 approval_conflict`，前端会重新加载审批列表并要求用户基于最新状态再次确认，避免并发决定相互覆盖。

推荐用 governance eval case 做确定性 smoke。`--save-workspaces` 会保留本次 eval 的工作区，后续审批命令可以直接指向生成的 HITL case 工作区：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite governance --context-strategy injection-safe --save-workspaces
python -m specgate.cli approvals list examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume
python -m specgate.cli approvals approve examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume approval-step-1
python -m specgate.cli resume examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume --max-steps 5
```

approve / deny 只记录人工决定，不会立即执行 action。调用 `resume` 后，已批准 action 会先进入 `applying`，再次校验目标文件状态、路径策略和快照边界，通过后至多应用一次，再继续 Agent loop 和最终 Gate；已拒绝 action 会进入 `rejected`，原 action 不会执行，拒绝原因会作为反馈交给 Agent 重新规划：

```powershell
python -m specgate.cli approvals deny examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume approval-step-1 --reason "范围太大"
python -m specgate.cli resume examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume --max-steps 5
```

`approve` 只表示人工允许尝试执行，不会绕过 `WorkspacePolicy`、硬阻断路径或 snapshot 保护。`.env`、路径逃逸和外部修改仍然会 fail closed。

`finish` 每次都会对当前 `index.html` 重新运行最终 Gate。Web 发布前还会比较最终 Gate 记录的 SHA-256 与待发布文件；若二者不一致，运行以 `stale_gate_result` 失败，且不会生成或 promotion 过期产物。

运行后可以打开：

```text
examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume/reports/latest/index.html
```

## 批量评估上下文策略

SpecGate 支持在 MockLLM / StubLLM 下批量运行 eval cases，用于比较不同上下文策略对成功率、安全拦截和反馈修复的影响。

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --context-strategy baseline
python -m specgate.cli eval examples/eval_cases --context-strategy compressed
python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe
```

评估结果写入：

```text
examples/eval_cases/eval-runs/latest/results.json
```

当前 eval 默认使用 MockLLM / StubLLM，不需要真实 API key。真实 LLM eval 是可选演示/人工实验能力，不作为确定性单元测试前提。

## CLI 凭据管理

当前课程验收和默认演示使用 `MockLLM`，不需要任何凭据。CLI 保留 OpenAI Chat Completions 兼容接口作为可选人工实验能力；WebUI 在完整配置后也可为新 run 启用真实模型，但二者都不属于确定性测试前提。

日常持久化使用操作系统 keyring。命令不会回显凭据明文，SpecGate 也不读取或写入 `.env`：

```powershell
specgate credentials set openai-compatible
specgate credentials status openai-compatible
specgate credentials clear openai-compatible
```

进程环境变量的优先级高于 keyring，适合 CI 或一次性人工实验：

```powershell
$env:OPENAI_COMPATIBLE_API_KEY="<临时凭据>"
```

在 Linux 或 Docker 中如果没有可用的 keyring backend，请显式使用进程环境变量；系统会失败关闭，不会回退到明文文件。`credentials clear` 只删除 keyring 中的值，不修改环境变量，因此 status 仍可能显示有效来源为 environment。

配置一次后的完整运行示例：

```powershell
$Workspace = Join-Path $env:TEMP "specgate-teacher-demo"
if (-not (Test-Path (Join-Path $Workspace "TASK_SPEC.md")) -or
    -not (Test-Path (Join-Path $Workspace "CHECKLIST.md"))) {
  throw "请先执行 Mock Demo 章节创建工作区"
}
specgate configure
specgate credentials status openai-compatible
specgate run $Workspace --max-steps 5 --timeout 120 --governance-profile strict
specgate credentials clear openai-compatible
```

单次实验仍可通过 `--model`、`--base-url` 和环境变量覆盖用户默认值，不需要修改配置文件。

即使使用该可选接口，文件读写仍然经过 `Tool Registry`、`WorkspacePolicy`、快照保护和 HTML Gate；缺少安全凭据时 CLI 会 fail closed，不会启动 runner，也不会生成 trace。

示例任务目录说明：

- `examples/knowledge_nav/TASK_SPEC.md`：运行时用户需求，描述要生成的 HTML 页面。
- `examples/knowledge_nav/CHECKLIST.md`：运行时验收清单；自然语言复选项可以紧跟确定性的 SpecGate 指令，由 Gate 自动检查。
- `examples/knowledge_nav/index.html`：SpecGate 生成的最终 HTML 产物。
- `examples/knowledge_nav/reports/latest/index.html`：一次运行的静态报告。
- `examples/knowledge_nav/runs/latest/trace.jsonl`：逐步运行日志，每行是一条 JSON 事件。
- `examples/knowledge_nav/memory.json`：跨会话记忆文件，记录最近运行的 Gate 摘要和步数。

仓库会保留一个示例 `reports/latest/index.html` 方便评审直接查看；`runs/latest/trace.jsonl` 和 `memory.json` 是本地运行产物，不进入 Git，可通过 Mock Demo 重新生成。

`site/index.html` 是 GitHub Pages 的公开首页，不是 harness 的运行输入；Pages workflow 会把示例产物复制到公开站点中。

### Checklist 确定性指令

Checklist 仍使用便于人工阅读的 Markdown。需要确定性验收的复选项，应在下一行紧跟 `<!-- specgate: ... -->` 指令，例如：

```markdown
- [ ] 至少包含 3 条新闻卡片
  <!-- specgate: selector "article.news-card" min=3 -->
- [ ] 每条新闻都有标题、摘要和时间
  <!-- specgate: each "article.news-card" has "h2" ".summary" "time" -->
- [ ] 页面包含版权文字
  <!-- specgate: text "版权所有" -->
- [ ] 不加载外部资源
  <!-- specgate: forbid external-resources -->
- [ ] 不包含脚本
  <!-- specgate: forbid scripts -->
```

支持的指令包括：`selector SELECTOR [min=N]` 检查元素数量，`each SELECTOR has CHILD...` 检查每个目标元素的后代，`text TEXT` 检查页面文本，以及 `forbid external-resources`、`forbid scripts`。选择器范围刻意保持简单，只支持标签 `tag`、类 `.class`、ID `#id`、标签加类 `tag.class`、属性存在 `[attr]` 和属性精确值 `[attr="value"]`；不支持后代/子元素组合符、伪类或完整 CSS 选择器。

为兼容已有案例，`- 必须包含 ...`、复选项中的“必须包含 ...”以及语义明确的“禁止外部资源/脚本”仍可解析。其他没有确定性指令且无法兼容解析的复选项会产生 `unsupported_check`；格式错误或超出支持范围的指令会产生 `invalid_checklist_rule`。两者都会使 Gate 失败，因此对应产物可以保留和下载，但不能标记为 `trusted`。

## 上下文管理

SpecGate 的 context pack 会扫描任务目录，并生成 `Context Manifest`。默认优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`，跳过 `runs/`、`reports/`、`.git/`、`__pycache__/` 等运行产物或缓存目录，并使用字符预算控制进入 LLM 的内容规模。

每次运行结束后，SpecGate 会把本次结果写入 `memory.json`。下一次构建 context pack 时会加入 `Memory` 段，用来提供跨会话历史约定和最近 Gate 结果摘要。

## 工具管理

SpecGate 使用 `Tool Registry` 结构化描述可用工具。当前注册的工具包括 `read_file`、`write_file`、`replace_file`、`list_files` 和 `finish`。注册表会进入 context pack，并展示在静态报告中；实际权限仍由 `WorkspacePolicy` 和文件快照保护共同执行。

## AgentOS / Superpowers 对齐

当前阶段优先接入 Lab 10 Skill，而不是扩大到浏览器 MCP 或真实 LLM。仓库内新增 `skills/specgate-static-html-harness/SKILL.md`，把 SpecGate 静态 HTML 任务的上下文选择、工具边界、安全检查、Gate 闭环和报告输出沉淀为可复用流程。

Lab 9-12 的取舍记录见 `docs/AI4SE_Lab_9_12_Alignment.md`。当前结论是：Lab 10 已作为本阶段交付；Lab 9 MCP 暂不做；Lab 11 Hook 和 Lab 12 AgentPack 作为后续候选方向。

Lab 11 Hook 已补充为可选示例：`hooks/pre-commit.sample`。它用于提交前疑似密钥扫描、demo 必要文件检查和测试提示，不会自动安装，也不是 SpecGate runtime 的一部分。

## Context Harness Deepening

### True Multi-Agent Isolation

`multi-agent-isolated` 是单进程 planner -> implementer -> reviewer 三阶段运行策略。它仍然使用同一套 deterministic MockLLM / StubLLM 输入，但每个角色会收到不同的 context、state 和 allowed actions。

planner 和 reviewer 不能写文件；如果它们尝试 `write_file` 或 `replace_file`，SpecGate 会在 role capability 层阻断，并记录 `role_action_blocked`。implementer 可以发起写入，但写入仍必须经过 `WorkspacePolicy`、snapshot guardrail、HITL review profile 和 `ToolDispatcher`。

常用命令：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated --save-workspaces
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
```

运行后可查看 `runs/latest/isolation.json`，以及 report 中的 Role Execution Evidence。

这一阶段继续沿着 Context Engineering 和 Harness Engineering 深入，但核心验收仍然使用 MockLLM / StubLLM，不需要真实 API key。

新增策略包括：

- `rag-select`：从 workspace 文本文件中检索相关片段，并把来源、行号、命中词和选择原因写入 evidence。
- `compressed-rag`：在检索基础上压缩运行反馈，清理大体积 tool result，并把关键约束放在上下文末尾。
- `isolated-harness`：在压缩检索基础上渲染 planner / implementer / reviewer 的角色上下文隔离证据。
- `benchmark`：固定 mock eval cases，对比不同 harness strategy，而不是比较真实 LLM 性能。

常用命令：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --context-strategy rag-select
python -m specgate.cli eval examples/eval_cases --context-strategy compressed-rag
python -m specgate.cli eval examples/eval_cases --context-strategy isolated-harness
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
```

benchmark 会写入：

```text
examples/eval_cases/eval-runs/latest/benchmark.json
examples/eval_cases/eval-runs/latest/results.json
examples/eval_cases/eval-runs/latest/results-<strategy>.json
```

`examples/eval_cases/eval-runs/` 是本地运行产物，不应提交到 Git。

### Prompt Injection Benchmark

Prompt Injection Benchmark 使用 MockLLM / StubLLM，不需要真实 API key。它评测的是 harness 的确定性安全边界，不比较真实 LLM 性能。

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli benchmark examples/eval_cases --suite security --strategies baseline injection-safe rag-select compressed-rag isolated-harness
```

输出会写入：

```text
examples/eval_cases/eval-runs/latest/benchmark.json
examples/eval_cases/eval-runs/latest/results-<strategy>.json
```

security suite 覆盖任务注入、RAG 间接注入、checklist 注入、隐藏 HTML 注入、tool result 注入、路径逃逸和敏感文件写入。

## 配套 WebUI 评审入口

SpecGate 是 CLI-first 产品；除 `specgate` CLI 和静态报告外，仓库保留一个 mock-first 的本地交互式 WebUI，作为课程要求的配套评审与演示入口。WebUI 复用同一套 Harness 内核，用于演示“用户上传/创建项目 -> 和 harness 对话 -> 生成或修复 HTML -> 查看报告与审批”的完整流程，不是另一套 Agent。它不会直接修改用户原始目录，而是把项目导入到隔离工作区，再返回生成产物和报告。当前仓库已完成本地/Docker 启动路径与确定性测试，但没有把该 Web 后端部署为公网服务。

启动本地 WebUI：

```powershell
specgate-web --host 127.0.0.1 --port 8000
```

然后打开：

```text
http://127.0.0.1:8000
```

当前 WebUI 包含：

- 注册、登录、退出和会话 cookie。
- 用户设置页可用 AES-256-GCM 加密保存 API key，并配置 Base URL、Model 与测试连接；Key 输入保存后立即清空且永不回填。
- 手动创建项目，或上传 zip 项目。上传项目必须包含 `SPEC` / `TASK_SPEC` 之一和 `CHECKLIST`，导入后会规范化为 `TASK_SPEC.md` 和 `CHECKLIST.md`；也可以包含已有 `index.html` 和其他辅助文件。
- Codex 风格的左侧项目列表、中央任务输入、右侧预览/报告/审批/设置面板。
- 后台 run 状态轮询：`queued`、`running`、`needs_approval`、`cancel_requested`、`publishing`、`completed`、`cancelled`、`timed_out`、`failed`。
- Web 运行工作台可以取消排队中、运行中或等待审批的任务；运行中的取消是协作式的，会在当前阻塞步骤返回并到达下一个安全停止点后确认。
- Web HITL 审批：首次创建不存在的 `index.html` 可以直接执行；覆盖任何已有文件时会先暂停为 `needs_approval`，不会在审批前修改文件。页面 approve / deny 会携带队列 revision，冲突时重载最新状态；随后由 resume 应用已批准 action，或把拒绝原因反馈给 Agent 重新规划。
- 产物下载和源码预览。生成的 HTML 默认作为下载附件或纯文本源码查看，避免在同源认证上下文中直接执行用户/模型生成的 HTML。

### Web 运行配置快照

设置页提供七项会真正传入 Runner 的运行配置：

| 配置 | 默认值 | 合法范围或选项 |
| --- | ---: | --- |
| `governance_profile` | `review` | `strict`、`demo`、`review` |
| `context_strategy` | `injection-safe` | `injection-safe`、`rag-select`、`compressed-rag` |
| `max_steps` | `5` | `1`–`20` |
| `context_budget_chars` | `12000` | `1000`–`100000` |
| `retrieval_top_k` | `6` | `1`–`20` |
| `retrieval_budget_chars` | `9000` | `500`–`50000` |
| `compression_max_tool_result_chars` | `1200` | `100`–`10000` |

设置只影响之后创建的 run。创建 run 时，七项配置会在同一 SQLite 事务中规范化为不可变 JSON 快照；首次执行、HITL resume、排队补入和进程重启恢复都只使用该快照，不会读取后来修改的用户设置。非法或损坏的快照会稳定失败关闭，不会调用 Agent 或发布产物。

运行工作台的 Debug/Audit 页面会展示本次 run 的实际配置、冻结的 `llm_mode` / `llm_model` 及 `runtime_config_applied` Trace 事件，便于核对创建、恢复和审计行为；不会展示凭据 fingerprint 或密钥材料。

### Web 模型模式

Web 默认使用 MockLLM，不需要 API key，也不会访问模型网络。只有 API key、Base URL 和 Model 都完整时，之后创建的新 run 才使用 OpenAI-compatible Chat Completions；真实模式失败不会降级到 MockLLM。模型只返回严格 JSON Action，路径策略、HITL、Gate 和发布 SHA-256 仍由 SpecGate Harness 执行。

真实模式部署还必须显式配置精确主机白名单和资源上限：

```powershell
$env:SPECGATE_LLM_ALLOWED_HOSTS="api.example.com"
$env:SPECGATE_LLM_MAX_OUTPUT_TOKENS="4096"
$env:SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS="30"
```

自动测试使用 Fake/Stub Resolver 与 Transport，不访问真实 DNS、socket 或 Provider。GitHub Pages 只是公开静态评审入口，不是公网交互式 Web 后端；真实模型能力需要运行带持久化数据库、凭据主密钥和网络策略的 Web 后端。该公网部署留到后续独立阶段。

WebUI 默认数据目录是：

```text
var/specgate_web/
```

可以用环境变量覆盖：

```powershell
$env:SPECGATE_WEB_DATA="D:\path\to\specgate-web-data"
```

如需在 Web 设置页保存 API key，必须设置按 `docs/DEPLOYMENT.md` 生成的 32 字节独立主密钥：

```powershell
$env:SPECGATE_WEB_CREDENTIAL_KEY="<部署文档生成的主密钥>"
```

如果使用 `http://公网IP:8000` 直接检查，不要开启 secure cookies；只有在 HTTPS 反向代理已经配置完成时，才设置：

```powershell
$env:SPECGATE_WEB_SECURE_COOKIES="1"
```

Web API key 使用独立的 `SPECGATE_WEB_CREDENTIAL_KEY` 主密钥加密，不能复用其他服务密钥；生成、备份和恢复方式见 `docs/DEPLOYMENT.md`。会话仍使用数据库里的随机 session token。重存、更新、清除 Key 或更换主密钥后，旧真实 run 的 fingerprint 校验失败并停止，不会读取当前设置替换冻结配置。

Web 运行时默认使用 4 个固定 worker 和 32 个排队槽位；每个用户最多同时保留 4 个活动 run，每个项目最多 1 个活动 run。worker 认领任务后开始计算 60 秒执行超时，排队时间和人工审批等待时间不计入超时。可通过以下环境变量调整，合法范围和单进程部署约束见 `docs/DEPLOYMENT.md`：

```text
SPECGATE_WEB_WORKERS=4
SPECGATE_WEB_QUEUE_CAPACITY=32
SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER=4
SPECGATE_WEB_RUN_TIMEOUT_SECONDS=60
```

课程自动验收仍以 MockLLM/Fake/Stub 为确定性路径。这些并发、取消、超时、恢复和真实模式安全边界均可在无真实 LLM、无外部网络的情况下验证。

上传 zip 当前限制为 5 MiB。导入逻辑会拒绝绝对路径、路径逃逸、Windows 盘符、反斜杠路径和空路径，避免 zip 内容写出隔离目录。

## Docker / 服务器部署

SpecGate 的 Docker 镜像默认启动 `specgate` CLI，并以 `--help` 作为默认参数。WebUI 仍保留，但必须通过 `--entrypoint specgate-web` 显式启动。发布镜像不等于部署服务。

本地构建：

```powershell
docker build -t specgate:local .
```

本地验证 CLI：

```powershell
docker run --rm specgate:local --help
docker run --rm specgate:local run-mock-demo /opt/specgate/examples/knowledge_nav
```

本地运行 WebUI：

```powershell
$credentialKey = $env:SPECGATE_WEB_CREDENTIAL_KEY
docker run --rm -p 8000:8000 `
  --entrypoint specgate-web `
  -e SPECGATE_WEB_CREDENTIAL_KEY="$credentialKey" `
  -v "${PWD}\var\specgate_web_docker:/data/specgate-web" `
  specgate:local `
  --host 0.0.0.0 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

GHCR Package 已设为 Public。v0.1.1 已发布，CLI 用户可以直接使用当前镜像：

```powershell
docker pull ghcr.io/yugarden404/specgate:0.1.1
docker run --rm ghcr.io/yugarden404/specgate:0.1.1 --help
docker run --rm `
  --env-file "$HOME\.specgate.env" `
  -v "D:\Projects\my-page:/workspace" `
  ghcr.io/yugarden404/specgate:0.1.1 `
  run /workspace
```

v0.1.1 已完成匿名拉取验证。PR #28 合并后的 `main@9cf9093` 由 [CI #69](https://github.com/YuGarden404/SpecGate/actions/runs/29678498485) 和 [Pages #39](https://github.com/YuGarden404/SpecGate/actions/runs/29678498457) 验证；[GHCR #2](https://github.com/YuGarden404/SpecGate/actions/runs/29679264248) 发布 `ghcr.io/yugarden404/specgate:0.1.1`。RepoDigest 为 `sha256:8cb8e5b9c9483a7f6bb70cc27fc3f3053b48be2f4a69374865e7bcbbaca4fd0f`，OCI revision 为 `9cf909341cd1a5feb8ed2b244ce31f0495016c4c`。一次性空 Docker 配置中的 pull、CLI help、Mock Demo 和 Web help 均以退出码 0 完成，临时配置已清理；证据见 `docs/evidence/github-actions-ghcr-v0.1.1-success.png`、`docs/evidence/github-package-specgate-v0.1.1-public.png` 与 `docs/evidence/ghcr-v0.1.1-anonymous-smoke.png`。

v0.1.0 是已验证的历史公开镜像 `ghcr.io/yugarden404/specgate:0.1.0`：`main@44b236f`、[GHCR #1](https://github.com/YuGarden404/SpecGate/actions/runs/29649149933)、digest `sha256:324fad1d8ae82880990a3e032847408b9339bf52bd81dc53b61e74dcb4b6ea3d` 以及 `docs/evidence/github-actions-pr25-ci-success.png`、`docs/evidence/github-actions-pr25-pages-success.png`、`docs/evidence/github-actions-ghcr-v0.1.0-success.png`、`docs/evidence/github-package-specgate-public.png`、`docs/evidence/ghcr-anonymous-pull-smoke.png` 均作为历史证据保留。`--env-file` 由 Docker 读取，应放在仓库外且不得提交；SpecGate 本身仍不读取 `.env`。公网交互式 Web 后端未部署，发布公开 CLI 镜像不等于部署公网交互式 Web 后端，发布镜像不等于部署服务。

Mock 模式不需要 API key。WebUI 默认使用 MockLLM；保存完整且符合部署白名单的 API key、Base URL 和 Model 后，新 run 才切换为真实模型。

## CI

`.gitlab-ci.yml` 包含 `unit-test` job，会运行：

```text
python -m unittest discover -s tests -v
```

GitHub 是开发主仓库；`.github/workflows/ci.yml` 运行完整测试并执行 Docker 镜像构建检查，`.github/workflows/pages.yml` 发布静态评审入口，`.github/workflows/ghcr.yml` 校验版本标签并发布 CLI-first 镜像。当前源码发布基线是 PR #28 合并后的 `main@9cf9093`，[CI #69](https://github.com/YuGarden404/SpecGate/actions/runs/29678498485)、[Pages #39](https://github.com/YuGarden404/SpecGate/actions/runs/29678498457) 与 [GHCR #2](https://github.com/YuGarden404/SpecGate/actions/runs/29679264248) 均成功。历史发布链继续保留：PR #25 合并后的 [CI #63](https://github.com/YuGarden404/SpecGate/actions/runs/29649068245)、[Pages #36](https://github.com/YuGarden404/SpecGate/actions/runs/29649068246) 与 `v0.1.0` 触发的 [GHCR #1](https://github.com/YuGarden404/SpecGate/actions/runs/29649149933) 均成功。

NJU GitLab 课程镜像从同一 `main` commit 独立运行 `.gitlab-ci.yml`。课程文件只保留 `unit-test`，安装项目、运行完整测试并执行 `specgate --help` CLI smoke；GitLab Pipeline 的成功由实际 Pipeline 证明，不用 GitHub Actions 成功替代。

NJU GitLab Pipeline #312781 在 `main@5fd86fa` 上运行：`unit-test` 已通过，`docker-build` 因共享 Runner 未启用 privileged 模式而失败。Pipeline #312784 中 `unit-test` 再次通过，但 `docker-build` 在拉取 `gcr.io/kaniko-project/executor` 时出现 `context deadline exceeded`。Pipeline #312797 成功拉取 `moby/buildkit:rootless` 并进入脚本，随后 RootlessKit 在 `fork/exec /proc/self/exe` 处返回 `operation not permitted`。三次结果共同证明学校共享 Runner 不适合容器构建，而不是 Dockerfile 或 Python 测试失败。

历史 [Pipeline #312806](https://git.nju.edu.cn/YuyuanLiang/specgate/-/pipelines/312806) 针对 `main@66ea825` 只运行 `unit-test` 并通过，[job #595758](https://git.nju.edu.cn/YuyuanLiang/specgate/-/jobs/595758) 完成 `Ran 926 tests in 33.684s`、`OK (skipped=18)` 与 CLI smoke。教师源码基线 `main@6dbaa75` 由 Pipeline #313088 / job #596503 覆盖并通过；当前 `main@9cf9093` 由 [Pipeline #313118](https://git.nju.edu.cn/YuyuanLiang/specgate/-/pipelines/313118) / [job #596642](https://git.nju.edu.cn/YuyuanLiang/specgate/-/jobs/596642) 覆盖并通过。GitLab Pipeline 已通过；Docker 构建继续由 GitHub Actions 的成功 job 独立覆盖。

## 已知限制

- MVP 不开放 shell。
- MVP 不做 Playwright。
- MVP 只处理静态单页 HTML 任务。
- WebUI 通过轮询展示 run 状态，但生成内容仍限定为静态单页 HTML 和可审计报告，不执行同源模型生成页面。
- 当前 WebUI 功能范围与运行方式不变；其早期界面采用项目自定义的轻量样式，未采用 Open Design 设计系统或 skill。这是已记录的课程推荐流程偏离，本阶段不借最终材料重做 UI。

## 第三方依赖与许可证

| 依赖 | 版本范围 | 用途 | 许可证 | 官方项目 |
| --- | --- | --- | --- | --- |
| `cryptography` | `>=44,<47` | Web 凭据 AES-256-GCM 加密 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| `fastapi` | `>=0.115,<1` | Web API 框架 | MIT | https://github.com/fastapi/fastapi |
| `httpx` | `>=0.27,<1` | 测试与 HTTP 客户端支持 | BSD-3-Clause | https://github.com/encode/httpx |
| `keyring` | `>=25,<26` | CLI 操作系统凭据存储 | MIT | https://github.com/jaraco/keyring |
| `python-multipart` | `>=0.0.9,<1` | Web 表单与文件上传解析 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `uvicorn` | `>=0.30,<1` | ASGI Web 服务器 | BSD-3-Clause | https://github.com/Kludex/uvicorn |

该表只覆盖直接运行时依赖，完整传递依赖以安装环境中的包元数据为准。

## 安全边界

Mock 模式不需要任何凭据。CLI 的 `specgate credentials status/set/clear <provider>` 使用系统 keyring，进程环境变量具有最高优先级；SpecGate 不读写 `.env`，keyring 不可用时失败关闭，也不会回退到明文文件。Web 凭据使用独立主密钥和 AES-256-GCM 加密，响应、异常、Trace 与普通数据库表不得出现凭据明文。

Harness 自有的 Trace、Memory、Report、Context artifact summary 和 Runner evidence 也统一经过 `workspace_fs` 安全文件边界，不跟随符号链接、Windows 目录联接或 reparse point。工具或 Gate 读取到非法 UTF-8 时返回 `invalid_encoding` 结构化失败，不向用户暴露原始字节或 Python traceback。OpenAI-compatible Provider 的 HTTP 错误只保留状态码与标准原因，响应正文不会进入 CLI、Trace 或报告；Web run 只能通过 `WebRuntimeCoordinator` 的固定 worker 和有界队列执行。

运行期间，SpecGate 会对允许写入的文件建立快照。`write_file` / `replace_file` 写入前会检查目标文件是否被外部修改；如果用户在 run 期间改过文件，harness 会阻止覆盖并在 trace 中记录 blocked tool result。

## 静态 Pages 评审入口

GitHub Pages 提供无需登录的公开静态首页、demo 和一次运行报告，与本地 Docker 启动的交互式 Web 产品壳相互独立。Pages 不运行 Web 后端，不提供项目导入、凭据保存或真实模型调用。静态报告会展示：

- loop steps。
- trace 中的模型响应和工具执行事件。
- blocked tool result 等护栏拦截证据。
- gate checks 和失败问题。
- Memory Summary。
- Tool Registry。
- final artifact 链接。

GitHub Pages 公开静态评审地址：

- 静态评审首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`
