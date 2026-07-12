# SpecGate

SpecGate 是 AI4SE 期末项目的 A 类选题：一个从零实现的小型 `Coding Agent Harness`。

MVP 是 Python CLI harness，使用可注入的 `MockLLM`，围绕静态 HTML 生成/修复任务运行 Checklist/Gate 反馈闭环，并生成静态 Web 报告。

## 评审快速入口

- 最终提交清单：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 项目讲解稿：`docs/PROJECT_WALKTHROUGH.md`
- Lab 9-12 对齐说明：`docs/AI4SE_Lab_9_12_Alignment.md`
- SpecGate Skill：`skills/specgate-static-html-harness/SKILL.md`
- 公开 WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`

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
- Docker 分发文件
- 静态 Web 报告部署 URL

## 当前状态

项目已完成 MVP 主链路的核心实现：Action 解析、workspace guardrail、文件工具、静态 HTML Gate、trace/context、`MockLLM` runner 和静态报告生成。

CLI demo、凭据边界、Dockerfile、`.gitlab-ci.yml`、GitHub Actions CI、GitHub Pages workflow 和示例静态报告已补齐。

GitHub Pages 已配置为 GitHub Actions 发布，并已成功部署公开 WebUI。

## 本地测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

## Mock Demo

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
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

推荐用 governance eval case 做确定性 smoke。`--save-workspaces` 会保留本次 eval 的工作区，后续审批命令可以直接指向生成的 HITL case 工作区：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite governance --context-strategy injection-safe --save-workspaces
python -m specgate.cli approvals list examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume
python -m specgate.cli approvals approve examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume approval-step-1
python -m specgate.cli resume examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume --max-steps 5
```

拒绝审批时，`resume` 会把该项解析为人工拒绝，不会执行被拒绝的 action：

```powershell
python -m specgate.cli approvals deny examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume approval-step-1 --reason "范围太大"
python -m specgate.cli resume examples/eval_cases/eval-runs/latest/workspaces/hitl-approve-resume --max-steps 5
```

`approve` 只表示人工允许尝试执行，不会绕过 `WorkspacePolicy`、硬阻断路径或 snapshot 保护。`.env`、路径逃逸和外部修改仍然会 fail closed。

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

## 真实 LLM 运行

真实 LLM 是可选能力，默认演示仍然使用 `MockLLM`。当前实现支持 OpenAI Chat Completions 兼容接口，适合第三方聚合平台。

先在本机隐藏录入 API key，不要把 key 粘贴到聊天记录或提交到 Git：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli credentials set openai-compatible --env-file .env
```

然后运行：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run examples/knowledge_nav --provider openai-compatible --model <模型名> --base-url <平台的 /v1 地址> --env-file .env --max-steps 5
```

如果第三方平台按请求指纹拦截，可以追加 `--user-agent "<另一个可用客户端的 User-Agent>"` 做兼容性排查。

真实模型只负责输出下一步 JSON Action。文件读写仍然经过 `Tool Registry`、`WorkspacePolicy`、快照保护和 HTML Gate；缺少凭据时 CLI 会 fail closed，不会启动 runner，也不会生成 trace。

示例任务目录说明：

- `examples/knowledge_nav/TASK_SPEC.md`：运行时用户需求，描述要生成的 HTML 页面。
- `examples/knowledge_nav/CHECKLIST.md`：运行时验收清单，其中 `- 必须包含 ...` 会被 Gate 自动检查。
- `examples/knowledge_nav/index.html`：SpecGate 生成的最终 HTML 产物。
- `examples/knowledge_nav/reports/latest/index.html`：一次运行的静态报告。
- `examples/knowledge_nav/runs/latest/trace.jsonl`：逐步运行日志，每行是一条 JSON 事件。
- `examples/knowledge_nav/memory.json`：跨会话记忆文件，记录最近运行的 Gate 摘要和步数。

仓库会保留一个示例 `reports/latest/index.html` 方便评审直接查看；`runs/latest/trace.jsonl` 和 `memory.json` 是本地运行产物，不进入 Git，可通过 Mock Demo 重新生成。

`site/index.html` 是 GitHub Pages 的公开首页，不是 harness 的运行输入；Pages workflow 会把示例产物复制到公开站点中。

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

## WebUI 产品壳

除 CLI 和静态报告外，SpecGate 现在提供一个 mock-first 的 WebUI 产品壳，用于演示“用户上传/创建项目 -> 和 harness 对话 -> 生成或修复 HTML -> 查看报告与审批”的完整流程。它不是直接修改用户原始目录，而是把项目导入到隔离工作区，再返回生成产物和报告。

启动本地 WebUI：

```powershell
$env:PYTHONPATH="src"
python -m specgate.web --host 127.0.0.1 --port 8000
```

然后打开：

```text
http://127.0.0.1:8000
```

当前 WebUI 包含：

- 注册、登录、退出和会话 cookie。
- 用户设置页，可保存 API key 配置状态；当前仍然默认 `MockLLM`，不会主动调用真实 LLM。
- 手动创建项目，或上传 zip 项目。上传项目必须包含 `SPEC` / `TASK_SPEC` 之一和 `CHECKLIST`，导入后会规范化为 `TASK_SPEC.md` 和 `CHECKLIST.md`；也可以包含已有 `index.html` 和其他辅助文件。
- Codex 风格的左侧项目列表、中央任务输入、右侧预览/报告/审批/设置面板。
- 后台 run 状态轮询：`queued`、`running`、`needs_approval`、`completed`、`failed`。
- Web HITL 审批：高风险 action 可以在页面里 approve / deny，再 resume 继续运行。
- 产物下载和源码预览。生成的 HTML 默认作为下载附件或纯文本源码查看，避免在同源认证上下文中直接执行用户/模型生成的 HTML。

WebUI 默认数据目录是：

```text
var/specgate_web/
```

可以用环境变量覆盖：

```powershell
$env:SPECGATE_WEB_DATA="D:\path\to\specgate-web-data"
```

部署到服务器时建议额外设置：

```powershell
$env:SPECGATE_WEB_SECRET="<随机长密钥>"
$env:SPECGATE_WEB_SECURE_COOKIES="1"
```

`SPECGATE_WEB_SECRET` 只用于 API key 配置状态的保护摘要；会话仍使用数据库里的随机 session token。WebUI 默认仍是 MockLLM，不会因为设置了 API key 就调用真实 LLM。

上传 zip 当前限制为 5 MiB。导入逻辑会拒绝绝对路径、路径逃逸、Windows 盘符、反斜杠路径和空路径，避免 zip 内容写出隔离目录。

## Docker

```powershell
docker build -t specgate:local .
docker run --rm specgate:local
```

已由用户在本机 PowerShell 设置代理环境变量后，完成 `python:3.11-slim` 拉取、镜像构建和容器运行验证。

Mock 模式不需要 API key。真实 LLM 模式尚未作为 MVP 默认能力开放。

## CI

`.gitlab-ci.yml` 包含 `unit-test` job，会运行：

```text
python -m unittest discover -s tests -v
```

因为仓库实际托管在 GitHub，`.github/workflows/ci.yml` 也提供同名 `unit-test` job，并额外执行 Docker 镜像构建检查。

## 已知限制

- MVP 不开放 shell。
- MVP 不做 Playwright。
- MVP 只处理静态单页 HTML 任务。
- WebUI 是静态报告，不是实时 dashboard。

## 安全边界

Mock 模式不需要任何凭据。真实 LLM 支持如果后续加入，必须使用 credential manager，不能打印、记录或提交密钥。当前 CLI 提供 `specgate credentials status/set/clear <provider>` 的最低实现，使用 `.env` 作为本地开发 fallback；`.env` 已被忽略，命令不会回显密钥明文。

运行期间，SpecGate 会对允许写入的文件建立快照。`write_file` / `replace_file` 写入前会检查目标文件是否被外部修改；如果用户在 run 期间改过文件，harness 会阻止覆盖并在 trace 中记录 blocked tool result。

## 静态 WebUI

本项目的 WebUI 是一次运行的静态报告，不是复杂前端应用。报告会展示：

- loop steps。
- trace 中的模型响应和工具执行事件。
- blocked tool result 等护栏拦截证据。
- gate checks 和失败问题。
- Memory Summary。
- Tool Registry。
- final artifact 链接。

GitHub Pages 已部署地址：

- WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`
