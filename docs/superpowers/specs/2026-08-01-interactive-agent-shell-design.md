# SpecGate 交互式 Agent Shell 设计

日期：2026-08-01
状态：已由用户分段确认并完成书面自查，待用户最终复核
目标版本：v0.3.0

## 1. 背景

SpecGate v0.2.0 已具备独立 Agent Loop、结构化工具调用、Governance、Gate、审批恢复、上下文管理、Workspace Memory、Runtime Event、Hook 和运行报告等能力。当前 CLI 主要以一次性子命令驱动：用户准备 `TASK_SPEC.md` 和 `CHECKLIST.md` 后执行命令，等待最终 HTML 或报告生成。

这种方式适合脚本和自动化，但普通用户难以感知 LLM 正在读取什么上下文、调用什么工具、为什么被治理规则拦截、Gate 是否通过以及最终文件位于何处。v0.3.0 需要在保留现有运行边界的前提下，增加类似 Codex 或 Claude Code 的交互式 Shell。

## 2. 目标

1. 裸执行 `specgate` 时进入持续运行的交互式 Shell。
2. 允许用户用自然语言要求 Agent 根据 Spec 和 Checklist 生成或修改 HTML。
3. 实时展示经过脱敏的 Context、Agent、Tool、Governance、Gate、Approval 和 Done 事件。
4. 支持 MockLLM 固定演示和 OpenAI-compatible 真实 LLM，并明确区分两者能力。
5. 首次运行引导用户配置模式、Base URL、API key、模型和工作区，后续启动恢复上次配置。
6. API key 只进入操作系统 keyring，任何持久化输出均不得泄漏密钥。
7. 每条自然语言请求保持独立 `AgentRun`，复用 v0.2.0 的 Runtime、治理、审批、Trace、Memory 和 Gate。
8. 保留全部现有 CLI 子命令和脚本兼容性。

## 3. 非目标

- 不引入第二套 Agent Loop、工具调度器、Governance 或 Gate。
- 不把 Shell 变成长生命周期的单一 LLM 消息会话。
- 不让交互层绕过 Runtime 直接修改工作区文件。
- 不将用户自然语言原文作为跨会话 Shell 历史保存。
- 不把 API key 降级保存到明文文件或项目目录。
- 不要求公网部署；交付方式继续以 GitHub Release 和容器制品为主。
- 不在本阶段增加递归子 Agent、后台任务或新的多 Agent 编排协议。
- 不移除或改变 `specgate run`、`resume`、`eval`、`benchmark`、`configure`、`credentials` 和 `approvals` 等现有入口。

## 4. 方案选择

采用“现有 Agent Runtime 上的轻量交互层”。

未采用以下方案：

- 长生命周期 Agent 会话：会模糊 `AgentRun`、审批、Gate、Trace 和上下文压缩的归属边界。
- 调用现有 CLI 子进程的外部包装器：难以稳定接收结构化事件，也会重复初始化配置和 Runtime。

交互 Shell 只负责输入、配置、控制和呈现。`AgentService` 仍是每次运行和恢复的统一边界。

## 5. 总体架构

```text
specgate
  -> InteractiveShell
       -> SlashCommandRouter
       -> ShellSetup
       -> UserRequestContextContributor
       -> AgentService
            -> AgentLoop
            -> ActionPipeline / Governance / Approval
            -> Tools / Workspace boundary
            -> Gate / Report / Trace / Memory
       <- Runtime Events / Hooks
       <- ShellEventRenderer
  -> SpecGate >>
```

### 5.1 `InteractiveShell`

负责 REPL 生命周期：读取输入、区分本地命令与自然语言、创建运行、捕获取消、返回提示符以及正常退出。它不理解或执行 Agent Action。

### 5.2 `SlashCommandRouter`

只解析以 `/` 开头的本地命令。命令名称大小写不敏感，路径、URL、模型名等参数保留原始大小写。未知命令显示帮助建议，不发送给 LLM。空输入只重新显示提示符。

### 5.3 `ShellSetup`

负责首次向导、配置修改、脱敏状态摘要和可选连接测试。配置验证成功后才替换已有值。

### 5.4 `UserRequestContextContributor`

将本次自然语言输入作为临时 `User Request` 上下文段加入现有 Context Builder。它不改写 `TASK_SPEC.md`，不改变其他 Context Contributor 的顺序和信任边界，也不将请求原文写入跨运行 Memory。

### 5.5 `ShellEventRenderer`

消费现有结构化 Runtime Event 和 Hook 输出，映射为稳定的终端事件类别。Renderer 不读取未脱敏的模型请求、工具结果或凭据。

### 5.6 `ShellApprovalPrompt`

连接现有审批挂起与恢复服务。它只显示审批 ID、动作类型、目标和脱敏风险摘要，接收批准或拒绝后调用既有恢复边界，不自行执行动作。

### 5.7 终端适配层

增加 `prompt-toolkit` 作为唯一的新交互式终端依赖，用于：

- Windows、Linux 和 macOS 的提示符与 ANSI 颜色兼容；
- 当前进程内的输入历史；
- API key 密文输入；
- `Ctrl+C` 和 EOF 处理；
- Runtime Event 输出后正确恢复提示符。

非 TTY、`NO_COLOR` 生效或终端不支持颜色时自动使用纯文本。终端适配层通过接口注入，单元测试不依赖真实控制台。

## 6. 运行边界与上下文

Shell 进程跨多次请求保持运行，但每条自然语言请求创建一个新的 `AgentRun`。每次运行拥有独立的：

- run ID 和状态机；
- Trace 与报告；
- Context Budget 和压缩生命周期；
- Gate 与修复循环；
- 审批挂起与恢复记录；
- 成功、失败、取消或等待审批终态。

后续请求只通过当前工作区文件以及现有 `memory.json` 获得跨运行信息，不继承上一次运行的完整消息列表。

用户请求原文只在本次运行构造模型上下文时存在。持久化 Trace 只记录脱敏请求摘要；Workspace Memory 继续执行现有提取、选择和最近运行上限策略，不保存 Shell 原始历史。

## 7. 启动流程

### 7.1 配置完整

加载上次模式、工作区、Base URL、模型、详细输出开关和 keyring 状态，显示脱敏摘要后直接进入提示符：

```text
SpecGate 0.3.0
Mode: Real LLM
Model: deepseek-v4-pro
Base URL: https://api.example.com/v1
API key: securely configured
Workspace: D:\code\NJU\project
Verbose: off
Type /help for commands.

SpecGate >>
```

`SpecGate >>` 默认使用蓝色；颜色关闭时保持相同文本。

### 7.2 配置缺失或失效

只询问缺失或失效的字段。首次启动先选择：

1. MockLLM Demo；
2. Real LLM。

Mock 模式明确告知只能运行固定 Demo。Real 模式依次收集 Base URL、API key、模型和工作区。已有有效值可按 Enter 保留。

### 7.3 连接测试

Real 配置完成后询问是否发送最小连接测试，并在发送前提示可能产生少量 API 费用。测试不是正式 `AgentRun`，响应不进入 Workspace Memory。测试失败时保留配置并显示脱敏、可操作的错误信息。

## 8. 输入与命令

### 8.1 输入分类

- 以 `/` 开头：由本地命令路由器处理，不创建 `AgentRun`。
- `exit`、`quit`、`q` 及大小写变体：正常退出。
- 其他非空输入：作为自然语言请求创建独立 `AgentRun`。

### 8.2 首版命令集

| 命令 | 无参数时 | 可选参数形式 |
| --- | --- | --- |
| `/help` | 显示命令、示例和退出方法 | 无 |
| `/status` | 显示模式、工作区、URL、模型、keyring 状态、verbose 和最近运行状态 | 无 |
| `/setup` | 启动完整配置向导，已有值可保留 | 无 |
| `/mode` | 显示并交互切换模式 | `/mode mock`、`/mode real` |
| `/workspace` | 显示并交互修改工作区 | `/workspace <path>` |
| `/model` | 显示并交互修改模型 | `/model <name>` |
| `/url` | 显示并交互修改 Base URL | `/url <url>` |
| `/api-key` | 密文读取并安全替换 API key | 无 |
| `/verbose` | 显示并交互切换详细输出 | `/verbose on`、`/verbose off` |
| `/approvals` | 列出待处理审批，并允许选择后批准或拒绝 | 无 |
| `/clear` | 只清空终端显示 | 无 |
| `/exit` | 刷新必要状态并退出 Shell | 无 |

`/clear` 不删除文件、配置、Trace、Memory 或运行记录。`/status` 和所有错误输出不得显示 API key 原文。

## 9. 自然语言运行流程

```text
SpecGate >> 请根据 TASK_SPEC.md 和 CHECKLIST.md 生成 index.html
[Context] Loaded TASK_SPEC.md, CHECKLIST.md and workspace memory
[Agent] Run started: run_20260801_001
[Tool] write_file: index.html
[Governance] Allowed
[Gate] Checking 8 requirements
[Gate] 1 requirement failed
[Agent] Repairing generated file
[Gate] Passed
[Done] D:\code\NJU\project\index.html
SpecGate >>
```

默认输出只显示理解进度所需的信息：

- `[Context]`：已选择的上下文类别和文件名，不显示大段原文；
- `[Agent]`：运行开始、推理阶段和修复阶段，不显示隐藏推理内容；
- `[Tool]`：工具名、脱敏目标和结果状态，不显示大段文件内容；
- `[Governance]`：允许、拒绝或需要审批及简短原因；
- `[Gate]`：检查数量、失败摘要、修复和最终状态；
- `[Approval]`：审批 ID、风险摘要及用户决定；
- `[Done]`、`[Failed]`、`[Cancelled]`、`[Pending approval]`：唯一终态。

`/verbose on` 可显示更多已经脱敏的阶段、事件 ID、耗时和重试信息，但仍不显示密钥、隐藏推理、完整请求载荷或大段工具内容。

完成时显示生成或修改文件的绝对路径，以及 Trace 或报告位置。Gate 未通过时不得输出 `[Done]`。

## 10. MockLLM 行为

MockLLM 不解释任意自然语言。用户在 Mock 模式输入普通请求时显示：

```text
[Mock] 当前模式不会处理自定义需求，只能展示内置 Demo。
是否运行 Mock Demo？[Y/n]
```

确认后创建独立 Mock `AgentRun`，使用现有固定 Demo 和完整 Runtime Event 展示流程。拒绝后直接返回提示符。不得根据用户输入伪造不同的 Mock 结果。

用户可通过 `/mode real` 切换真实模式；缺失真实配置时立即进入补充向导。

## 11. 配置与凭据

用户配置以向后兼容方式扩展为概念上的以下结构：

```json
{
  "schema_version": 2,
  "provider": "openai-compatible",
  "mode": "real",
  "base_url": "https://api.example.com/v1",
  "model": "deepseek-v4-pro",
  "workspace": "D:\\code\\NJU\\project",
  "verbose": false
}
```

实现必须复用现有用户级配置位置和原子写入机制。旧配置缺少字段时应用默认值，不要求手工迁移。字段损坏时只重新收集对应值。

配置命令在新值验证成功后立即持久化。工作区必须解析为可访问的现有目录；无效路径不替换旧值。URL 做基本格式与规范化检查；模型名不得为空。

API key：

- 只保存到现有 OS keyring；
- 通过密文输入获取，且该输入不加入当前会话历史；
- 不进入用户配置、项目文件、Trace、Memory、报告或终端历史；
- keyring 写入失败时保留旧值并明确报错；
- 不允许静默降级为明文存储；
- 状态只显示 `securely configured` 或 `not configured`。

现有环境变量凭据入口继续兼容并保持其当前优先级。通过 `/api-key` 输入的新密钥只写入 keyring；当环境变量正在覆盖 keyring 时，`/status` 只显示安全来源状态，不显示任何凭据内容。

## 12. 审批、取消与恢复

### 12.1 即时审批

需要人工批准时暂停当前运行并显示脱敏风险摘要。用户输入 `y`/`yes` 或 `n`/`no`，命令大小写不敏感。批准后经现有 AgentService 恢复；拒绝结果反馈给 Agent，Agent 可以调整方案但不能绕过同一审批边界。

### 12.2 `/approvals`

列出进程异常退出或其他入口留下的待处理审批。用户选择一项后查看摘要并批准或拒绝。无待处理项时明确显示为空。

### 12.3 `Ctrl+C`

- 运行中：向当前运行发送取消，完成 Trace 收尾后返回提示符；
- 空闲时：退出 Shell；
- 被取消的运行终态必须为 `Cancelled`，不得显示成功。

进程在挂起审批或运行过程中退出时，已经落盘的状态继续由现有 `resume` 和审批恢复机制管理。

## 13. 错误处理

一次运行失败不得拖垮 Shell。除无法初始化终端或用户配置等致命错误外，异常处理后都返回提示符。

- LLM 超时、限流和网络错误：复用现有有界重试，最终显示脱敏错误类别和建议。
- 非法 Action JSON：复用协议校验和修复；最终失败时不得将普通文本当成工具调用。
- Governance 拒绝：结果反馈给 Agent；没有替代方案时明确失败。
- Gate 失败：复用现有修复循环；达到边界仍失败时显示未满足项和 `[Failed]`。
- 工作区失效：运行前阻止执行并引导 `/workspace`。
- Renderer 失败：记录内部错误并降级为纯文本简化输出，不中断 Runtime。
- EOF：完成必要清理后正常退出。

文件写入继续经过现有 Workspace 边界、Governance、文件锁和原子替换机制。Shell 不增加任何直接写文件捷径。

## 14. 兼容性

CLI 入口调整为：

- 无子命令：进入交互 Shell；
- 有现有子命令：按 v0.2.0 行为执行，不启动 Shell；
- `-h`/`--help`：继续显示 CLI 帮助，不进入配置向导；
- 非 TTY 场景：现有显式子命令不变，裸 `specgate` 若无法获得交互输入则显示清晰错误和帮助，而不是无限等待。

旧配置、已有 keyring 凭据、运行状态、Trace、Memory 和报告格式保持可读取。配置扩展是加法式变更。

## 15. 测试设计

实现遵循测试驱动开发，覆盖以下层次。

### 15.1 命令解析

- 裸入口进入 Shell；
- 现有子命令不回归；
- 命令名称和退出词大小写不敏感；
- 命令参数保留原始大小写；
- 空输入和未知命令行为确定。

### 15.2 配置与安全

- 旧配置迁移、默认值、原子保存和损坏字段恢复；
- 工作区、URL 和模型验证；
- keyring 成功、失败和保留旧值路径；
- API key 不出现在配置、输出、Trace、Memory 和报告中；
- 连接测试成功、失败、拒绝测试和费用提示。

### 15.3 Shell 控制

- 首次配置与完整配置快速启动；
- Mock 确认和 Real 模式切换；
- 当前进程历史不跨会话保存；
- `Ctrl+C` 取消当前运行以及空闲退出；
- 非 TTY、`NO_COLOR` 和 Renderer 降级。

### 15.4 Runtime 集成

- 每条自然语言输入只创建一个 `AgentRun`；
- User Request 临时注入且不改写 Spec；
- Event 类别与顺序正确；
- 审批原地恢复和拒绝路径；
- Gate 失败不显示成功；
- 取消、失败和等待审批终态正确。

### 15.5 端到端 Mock

在临时工作区运行完整 Shell，确认固定 Demo 生成预期 HTML、输出绝对路径，并留下合法 Trace 和报告。

### 15.6 真实模型 smoke test

自动测试不依赖公网，使用本地假 OpenAI-compatible 服务覆盖正常响应、超时、限流、非法 JSON 和修复流程。发布前以 DeepSeek V4 Pro 或目标兼容模型手工验证：

1. 最小连接测试；
2. 根据 Spec 和 Checklist 生成 HTML；
3. 修改已有 `index.html`；
4. 一次 Gate 修复；
5. 非法响应和超时；
6. `Ctrl+C` 取消后继续使用 Shell。

DeepSeek V4 Pro 只有在支持 OpenAI-compatible `/chat/completions`，并能稳定遵循 SpecGate 的严格 JSON Action Protocol 时才视为兼容。模型能力不能替代协议 smoke test。

## 16. 验收标准

1. Windows PowerShell 中裸执行 `specgate` 可完成首次配置并进入蓝色 `SpecGate >>` 提示符。
2. 重启后恢复上次模式、工作区、URL、模型和凭据状态，不重复收集有效配置。
3. 普通请求可生成或修改 HTML，并实时显示脱敏 Runtime 进度。
4. 每条请求对应独立运行、Trace、Gate 和终态。
5. Mock 模式不会声称理解自定义请求。
6. 审批可在当前 Shell 内批准或拒绝并恢复。
7. 运行中 `Ctrl+C` 取消本次运行，Shell 仍可继续使用。
8. API key 不出现在任何明文持久化文件和用户可见输出中。
9. `exit`、`quit`、`q` 及大小写变体可正常退出。
10. 现有完整测试套件和新增 Shell 测试全部通过，现有 CLI 子命令无回归。

## 17. 实施约束

- 先写失败测试，再写最小实现。
- 优先扩展现有 `AgentService`、Context Contributor、Runtime Event、Hook、UserConfig 和 Credentials 边界。
- 不在 Shell 中复制 Action Pipeline、审批状态机或 Gate 逻辑。
- 终端输出必须从结构化事件生成，不解析日志文本推断运行状态。
- 不在设计和实现阶段执行发布、推送或公网部署。
- 按项目既有协作约定，Git 暂存、提交、推送和 PR 由用户执行。
