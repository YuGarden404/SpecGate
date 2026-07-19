# SpecGate 项目讲解稿

## 1. 一句话介绍

SpecGate 是一个面向静态 HTML 任务的小型 Coding Agent Harness。它让 LLM 只能输出严格 JSON action，由 harness 负责选择上下文、检查权限、调用白名单工具、运行 Gate、记录 trace，并生成静态报告。

## 2. 为什么它属于 A 类 Coding Agent Harness

A 类项目关注的是 agent 工程机制，而不是具体业务页面。SpecGate 的核心贡献在 harness 层：

- 自己实现 agent loop。
- 自己定义 Action JSON 协议。
- 自己实现工具分发和 Tool Registry。
- 自己实现 WorkspacePolicy 和文件快照保护。
- 自己实现 context pack 和 Context Manifest。
- 自己实现 Gate 反馈闭环。
- 自己生成 trace 和静态 Web 报告。

示例 HTML 页面只是演示任务，不是项目主体。项目主体是控制 LLM 如何安全、可测、可追踪地修改代码文件。

## 3. 一次运行的数据流

```text
Settings transaction → runtime_config_json + llm_config_json snapshots
→ Context Select/Compress/Isolate
→ MockLLM or real Chat Completions → strict JSON Action Parser
→ WorkspacePolicy / ApprovalQueue revision-CAS
→ Tool Dispatcher
→ final Gate + artifact SHA-256
→ Trace / Debug / Audit / artifacts
```

Gate 失败会作为结构化 observation 回灌下一轮；需人工确认的写入先进入 HITL 队列，批准后仍须经过同一 WorkspacePolicy、快照保护和最终 Gate。

## 4. 主要模块

| 模块 | 文件 | 作用 |
| --- | --- | --- |
| Action 协议 | `src/specgate/actions.py` | 解析和校验 LLM 输出的 JSON action。 |
| 配置读取 | `src/specgate/config.py` | 读取 `specgate.toml`。 |
| 上下文管理 | `src/specgate/context_selector.py`、`src/specgate/context.py` | 选择任务文件，跳过运行产物，构建 context pack。 |
| LLM 抽象 | `src/specgate/llm.py`、`src/specgate/web_llm.py` | 默认 `MockLLM`；完整配置后由冻结 Factory 构造真实模型客户端。 |
| LLM 网络边界 | `src/specgate/llm_transport.py` | 精确白名单、公网 DNS、固定 IP TLS、禁止重定向和有界重试/响应。 |
| 工具注册 | `src/specgate/tool_registry.py` | 结构化描述可用工具、权限、参数和结果。 |
| 工具执行 | `src/specgate/tools.py` | 执行 read/write/replace/list/finish。 |
| 安全策略 | `src/specgate/policy.py`、`src/specgate/snapshot.py` | 限制路径、动作和外部修改覆盖。 |
| Gate | `src/specgate/gate.py` | 检查静态 HTML 和 checklist。 |
| HITL | `src/specgate/approvals.py`、`src/specgate/web_approvals.py` | revision/CAS、批准/拒绝和幂等 resume。 |
| Web 运行时 | `src/specgate/web_runtime.py`、`src/specgate/web_runs.py` | 固定 worker、有界队列、取消、超时和重启恢复。 |
| 运行配置 | `src/specgate/runtime_config.py`、`src/specgate/llm_config.py`、`src/specgate/web_db.py` | 保存 schema v5 的 Runner 与 LLM 两类不可变快照。 |
| 凭据治理 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | OS keyring 与 Web AES-256-GCM，不回显明文。 |
| Runner | `src/specgate/runner.py` | 串联 agent loop。 |
| Trace | `src/specgate/trace.py` | 记录 JSONL 事件并脱敏。 |
| Report | `src/specgate/report.py` | 生成静态 HTML 报告。 |
| CLI | `src/specgate/cli.py` | 提供命令入口和 mock demo。 |

## 5. 三条工程主线

### 上下文管理

SpecGate 不把整个仓库塞给 LLM，而是扫描任务目录，优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`，跳过 `runs/`、`reports/`、`.git/`、缓存和二进制文件，并生成 Context Manifest。

价值：减少噪声，控制上下文规模，让评审能看到“为什么这些文件进入了 LLM 输入”。

### 安全性

SpecGate 使用 `WorkspacePolicy` 阻止路径越界、链接逃逸和 allowlist 外写入，使用 `FileSnapshot` 防止运行期间覆盖用户或外部进程刚改过的文件。CLI 凭据持久化进入操作系统 keyring，Web 凭据使用 AES-256-GCM；Mock 模式不需要 key。

价值：危险动作不是靠 prompt 约束，而是在代码层被拦截。

### 工具管理

SpecGate 使用 Tool Registry 描述 `read_file`、`write_file`、`replace_file`、`list_files`、`finish`。工具信息会进入 context pack，也会显示在静态报告里。

价值：LLM、runner 和评审者都能看到当前 harness 到底开放了哪些工具。

## 6. 为什么 Mock LLM 足够支撑 MVP

Mock LLM 不是为了证明模型能力，而是为了证明 harness 机制：

- JSON action 是否严格；
- 工具调用是否受控；
- Gate 失败是否能驱动下一轮修复；
- trace 和 report 是否完整；
- 安全边界是否可测试；
- CI 是否能稳定复现。

Web 默认路径保持 `mock`，这样课程评审不需要网络、API key 或模型额度。真实模型已经作为可选决策源接入：API key、Base URL、Model 完整后，新 run 使用 Chat Completions；失败不会降级到 Mock。无论模型来源如何，Action Parser、WorkspacePolicy、HITL、Gate 和发布 SHA-256 都不变。

## 7. 演示脚本

1. 在空目录从公开 NJU 课程镜像克隆，或从 GitHub 开发主仓库克隆，然后创建并激活 Python 3.11+ 虚拟环境：

```powershell
git clone https://git.nju.edu.cn/YuyuanLiang/specgate.git SpecGate
cd .\SpecGate
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
specgate --help
```

2. 展示任意工作区的两个准确输入文件名 `TASK_SPEC.md` 与 `CHECKLIST.md`。已有 `index.html` 是可选输入；运行后它会成为最终产物。

3. 用安装后的 CLI 运行固定、离线、可重复的 Mock Demo：

```powershell
$Workspace = Join-Path $env:TEMP "specgate-teacher-demo"
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
Copy-Item .\examples\knowledge_nav\TASK_SPEC.md $Workspace -Force
Copy-Item .\examples\knowledge_nav\CHECKLIST.md $Workspace -Force
specgate run-mock-demo $Workspace
```

打开 `$Workspace\index.html` 与 `$Workspace\reports\latest\index.html`，展示 trace、actions、Gate、tools、trust summary 和 final artifact；用 `Get-Content -Encoding UTF8 (Join-Path $Workspace "runs\latest\trace.jsonl") -Tail 10` 检查 `parse_errors=0`。

4. 运行教师式全量验收：

```powershell
python -m unittest discover -s tests
```

2026-07-19 在公开 NJU `main@6dbaa75` 的空目录克隆中得到 `Ran 954 tests in 213.679s`、`OK (skipped=27)` 和退出码 0。审批模块单独运行 53 项虽然通过，但此前全量调度能稳定暴露 Windows 锁竞态，因此全量验证不能由局部测试替代。

5. 可选展示真实模型。交互式录入凭据，不在讲解、截图或 trace 中展示 API key：

```powershell
specgate configure
specgate credentials status openai-compatible
specgate run $Workspace --max-steps 5 --timeout 120 --governance-profile strict
specgate credentials clear openai-compatible
```

已验证示例使用 `https://njusehub.info/v1` 与 `glm-5.2`，结果为 `passed=True, steps=2`、最终 Gate 通过、`trusted`、`parse_errors=0`。演示结束后确认 keyring 凭据已经清除。

6. 打开 `docs/FINAL_EVIDENCE_MATRIX.md`，沿源码链说明 PR #27 修复了 Windows 两进程在“写入锁字节”和“获取锁”之间的竞态，并加入锁准备失败恢复分支回归测试。真实并发行为另由审批并发用例连续 30 轮和完整套件验证；这个案例说明单文件测试全绿不等于并发协议在真实全量调度下正确。

7. 最后展示发布链并区分部署边界：PR #28 合并后的 `main@9cf9093` 已由 [CI #69](https://github.com/YuGarden404/SpecGate/actions/runs/29678498485)、[Pages #39](https://github.com/YuGarden404/SpecGate/actions/runs/29678498457) 和 [GHCR #2](https://github.com/YuGarden404/SpecGate/actions/runs/29679264248) 验证；`v0.1.1` 已发布，`ghcr.io/yugarden404/specgate:0.1.1` 已完成匿名拉取验证，digest 为 `sha256:8cb8e5b9c9483a7f6bb70cc27fc3f3053b48be2f4a69374865e7bcbbaca4fd0f`，OCI revision 为 `9cf909341cd1a5feb8ed2b244ce31f0495016c4c`。`v0.1.0` 的 `main@44b236f`、GHCR #1、历史 digest 与五张旧截图继续保留。公网交互式 Web 后端未部署；发布公开 CLI 镜像不等于部署公网交互式 Web 后端。

8. 打开 `docs/AI4SE_Lab_9_12_Alignment.md`，说明 Lab 10 Skill 与 Lab 11 Hook sample 已接入，Lab 9/12 的取舍合理。

## 8. 公开展示地址

- WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`

## 9. 后续方向

当前最终提交不需要继续扩张核心功能。合理后续方向是：

- 在人工测试环境验证更多 OpenAI-compatible 服务的兼容子集，但不把真实模型结果作为自动验收前提。
- AgentPack 草案：把权限和 max steps 写成可部署元数据。

这些方向都应保持“不开放 shell、不做浏览器自动化、不扩大 MVP 主路径”的边界。
