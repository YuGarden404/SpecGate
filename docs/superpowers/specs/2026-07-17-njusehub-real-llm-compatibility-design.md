# NJU SE Hub 真实 LLM 兼容性验证设计

日期：2026-07-17  
状态：已由用户分段确认

## 1. 背景

SpecGate 已实现 OpenAI-compatible Chat Completions 接入，并分别提供 CLI 直接工作区运行和本地 WebUI 隔离工作区运行。课程项目不需要部署公网 Web 服务；本阶段只验证南京大学提供的 NJU SE Hub API 能否在本机真实驱动 SpecGate。

用户提供的接口与模型如下：

- Base URL：`https://njusehub.info/v1`
- `qwen3.7-max`
- `kimi-k2.7-code`
- `glm-5.2`
- `deepseek-v4-pro`

API Key 已由用户持有，但不得进入聊天、命令历史、截图、仓库、测试夹具、Trace 或报告。

## 2. 目标

本阶段需要回答以下问题：

1. NJU SE Hub 是否接受 SpecGate 当前发送的 OpenAI-compatible 请求。
2. 四个模型是否都能通过 `choices[0].message.content` 返回文本结果。
3. 四个模型是否能遵守 SpecGate 的严格 JSON Action 协议。
4. 模型是否能在最多 4 个 Agent step 内写入合格的 `index.html` 并请求 `finish`。
5. WebUI 的白名单、安全传输、加密凭据、运行审计和工件发布路径是否能与学校接口协同工作。
6. CLI 是否能使用同一接口直接修改指定的本地临时工作区。
7. 所有验证是否能留下不含凭据的可审计证据。

## 3. 非目标

本阶段明确不做以下工作：

- 不部署公网 Web 服务。
- 不购买域名、服务器或处理 ICP 备案。
- 不修改正式示例 `examples/knowledge_nav`。
- 不使用真实模型修改 SpecGate 仓库生产代码。
- 不把 API Key 写入 `.env`、命令参数、测试文件或文档。
- 不以连接测试成功代替完整 Action 和 Gate 验证。
- 不预先修改 LLM 适配代码来迎合尚未观察到的问题。
- 不对模型质量、价格或性能做超出最小兼容性测试的横向评测。

## 4. 当前协议契约

SpecGate 会向 Base URL 追加 `/chat/completions`，因此本阶段的实际接口为：

```text
https://njusehub.info/v1/chat/completions
```

请求使用 Bearer 鉴权，并发送以下核心字段：

```json
{
  "model": "qwen3.7-max",
  "messages": [
    {"role": "system", "content": "严格 JSON Action 指令"},
    {"role": "user", "content": "SpecGate context"}
  ],
  "temperature": 0,
  "max_tokens": 4096
}
```

SpecGate 要求响应至少满足：

```text
choices[0].message.content 为字符串
```

完整 run 中，该字符串还必须是一个不带 Markdown 围栏或自然语言前后缀的严格 JSON Action 对象。连接测试只验证请求能够完成并返回标准内容字段，不验证 Action 协议。

## 5. 方案选择

本阶段采用“WebUI 首测，CLI 复测”的两阶段方案。

未采用只发送原始 HTTP 请求的方案，因为它会绕过 SpecGate 的安全传输、Action 解析、权限、Gate 和审计。未采用只测 WebUI 的方案，因为 WebUI 修改的是导入后的隔离副本，不能证明 CLI 可以直接修改指定本地目录。

验证顺序为：

1. WebUI 使用 `qwen3.7-max` 完成基线连接和完整 run。
2. WebUI 依次验证 `kimi-k2.7-code`、`glm-5.2`、`deepseek-v4-pro`。
3. CLI 使用 `qwen3.7-max` 完成一次直接本地文件验证。

## 6. 凭据与隔离设计

WebUI 使用独立数据目录：

```text
D:\code\NJU\SpecGate\.specgate-web\njusehub-smoke
```

`.specgate-web/` 已被 Git 忽略。该目录与现有 `var/specgate_web` 分离，避免旧凭据指纹、旧用户、撤销测试或历史 run 干扰结果。

WebUI 启动时必须设置：

```text
SPECGATE_WEB_DATA=D:\code\NJU\SpecGate\.specgate-web\njusehub-smoke
SPECGATE_LLM_ALLOWED_HOSTS=njusehub.info
SPECGATE_WEB_CREDENTIAL_KEY：当前 PowerShell 会话中临时生成的 32 字节 URL-safe Base64 独立主密钥
```

Base URL 和模型在 Web 设置页保存。API Key 只在本地设置页输入，由 Web 凭据服务加密保存；输入完成后页面不得回填密钥。

CLI 阶段使用另一个系统临时目录，并通过隐藏输入将 API Key 放入当前 PowerShell 会话的 `OPENAI_COMPATIBLE_API_KEY`。测试结束后立即清除该环境变量。不得把 Key 作为 `--value` 或其他命令行参数传入。

## 7. WebUI 安全传输与连接测试

WebUI 的 Base URL 固定为：

```text
https://njusehub.info/v1
```

主机白名单只允许精确主机 `njusehub.info`，不使用通配符。Web 安全传输层继续执行 HTTPS、DNS 结果、公网地址、TLS 主机名、重定向和系统代理限制；不得为了通过学校接口而关闭这些保护。

每个模型先执行一次连接测试。连接测试具有以下边界：

- 10 秒总超时。
- 只尝试一次传输。
- 最多请求 8 个输出 tokens。
- 不创建项目或 run。
- 只证明接口、鉴权、模型名和标准响应内容字段可用。

连接测试失败后不立即连续点击。先按错误类型记录和排查，再决定是否重试一次。

## 8. 最小测试项目

每个模型使用一个全新的手动项目，且不提供初始 `index.html`。下文的 `{MODEL_ID}` 必须在创建项目时替换为本轮模型的完整名称，不得原样输入。项目名采用：

```text
NJU API Smoke - {MODEL_ID}
```

`TASK_SPEC.md` 的任务要求为：

- 创建单文件、离线的中文 `index.html`。
- 页面标题和 `<h1>` 为 `NJU School API Smoke Test`。
- 页面包含 `{MODEL_ID} compatibility verified` 文本。
- 包含 UTF-8 charset、移动端 viewport 和搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成后请求 `finish`。

`CHECKLIST.md` 使用模型对应的确定性文本检查：

```markdown
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 {MODEL_ID} compatibility verified
```

不放置初始 `index.html` 的目的是让首次 `write_file` 在 `review` profile 下直接执行，避免覆盖审批影响模型之间的可比性。

## 9. Web 完整运行配置

每个模型的新 run 使用以下运行配置：

```text
governance_profile: review
context_strategy: injection-safe
max_steps: 4
```

其余上下文和检索预算沿用当前默认值，不在本阶段调参。预期正常动作序列为：

```text
step 1: write_file(index.html)
Gate: passed
step 2: finish
Gate: passed
run: completed
trust: trusted
```

`max_steps=4` 限制的是逻辑 Agent step。完整 Web run 的安全传输层对瞬时失败可能在单步内重试，当前每步最多三次传输，因此极端情况下 HTTP 请求数可能超过 4。记录中必须区分逻辑调用与传输重试，不把二者混为一谈。

## 10. 兼容性分级与通过标准

每个模型按三级记录：

| 等级 | 判断条件 |
| --- | --- |
| 接口兼容 | 连接测试成功 |
| Action 兼容 | 完整 run 能返回并解析严格 JSON Action |
| 完整兼容 | Run 完成、Gate 通过、产生工件且 Trust 为 `trusted` |

完整兼容需要同时满足：

- Run 记录 `llm_mode=openai-compatible`。
- `llm_model` 与本轮模型完全一致。
- `index.html` 和 ZIP 工件存在。
- `parse_errors=0`。
- `blocked_actions=0`。
- `gate_failures=0`。
- `finish_actions=1`。
- `approval_requests=0`。
- 状态为 `completed`。
- Trust 为 `trusted`。
- 没有失败后降级到 Mock。
- 工件、Trace、报告和截图均不含 API Key。

若模型需要额外一步自我修复，但最终在 4 步内完成，则记录为“完整兼容，但动作稳定性次于两步基线”。不得把它写成严格两步通过。

## 11. CLI 直接工作区验证

四模型 Web 矩阵完成后，只用 `qwen3.7-max` 执行一次 CLI 验证，以控制额度。CLI 工作区为：

```text
%TEMP%\specgate-njusehub-cli-qwen
```

该目录使用与 Web 基线相同的最小 `TASK_SPEC.md` 和 `CHECKLIST.md`，初始不包含 `index.html`。运行参数固定为：

```text
provider: openai-compatible
base_url: https://njusehub.info/v1
model: qwen3.7-max
max_steps: 4
timeout: 60
governance_profile: review
```

CLI 通过标准为：

- 进程退出码为 0。
- 指定临时目录中实际新增 `index.html`。
- `runs/latest/trace.jsonl` 存在。
- `reports/latest/index.html` 存在。
- 最终 Gate 通过。
- Trace 和产物不含 API Key。

该结果用于证明 SpecGate 能直接修改指定本地工作区；它不使用 Web 导入副本。

## 12. 失败分类与处理

失败按以下边界分类：

| 错误或现象 | 初步含义 | 首要检查 |
| --- | --- | --- |
| `llm_authentication_failed` | 401/403 或账号权限失败 | Key 状态、账号授权、模型权限 |
| `llm_request_rejected` | 请求被平台拒绝 | 模型名、`temperature`、`max_tokens` 等字段 |
| `llm_provider_unavailable` | 网络或服务端不可用 | 校园网络、平台状态、DNS 与 TLS |
| `llm_request_timeout` | 请求超过限制 | 平台延迟、模型负载、当前超时 |
| `llm_response_invalid` | 响应结构不符合契约 | `choices[0].message.content` 是否存在且为字符串 |
| `parse_errors > 0` | 模型输出不符合 Action 协议 | Markdown 围栏、解释文字、非严格 JSON |
| `max_steps_reached` | 模型未在预算内完成 | 动作规划、重复修复、未请求 `finish` |
| Gate 失败 | 生成内容不满足 SPEC | HTML 与 Checklist，不误判为 API 不兼容 |

出现失败时执行以下原则：

1. 不连续重复调用同一模型。
2. 先保存脱敏状态、指标和错误代码。
3. 确认是配置、网络、平台协议、模型输出还是 Gate 问题。
4. 只有网络瞬时问题允许间隔后重试一次。
5. 若需要修改 SpecGate，先进入 `systematic-debugging` 定位根因，再通过 TDD 修改最小适配层。
6. 不为调试而打印响应正文、请求头或 API Key。

## 13. 证据设计

验证结果记录到：

```text
docs/superpowers/audits/2026-07-17-njusehub-real-llm-compatibility.md
```

审计文档至少记录：

- 测试日期和本机运行方式。
- Base URL，仅记录公开地址。
- 模型名。
- Web 连接测试结果。
- Run ID、状态和 Trust。
- steps、llm_calls、tool_calls、parse_errors、gate_failures、finish_actions 和 approval_requests。
- 工件存在性。
- CLI 退出码和本地文件存在性。
- 错误代码、一次重试事实和最终结论。
- 人工操作，包括输入凭据、创建项目、点击连接测试和发起 run。

截图必须在 API Key 输入框清空后获取。原始 API Key、Authorization 请求头、Web 数据库、凭据主密钥和未经检查的日志不得进入审计文档或 Git。

## 14. 清理与保留

测试完成后执行：

1. 清除当前 PowerShell 会话中的 `OPENAI_COMPATIBLE_API_KEY`。
2. 保留 `.specgate-web/njusehub-smoke`，直到脱敏审计文档完成并复核。
3. 审计完成后，由用户决定是否删除隔离 Web 数据目录和系统临时 CLI 工作区。
4. 不删除用户原有 `var/specgate_web` 数据。
5. 不提交 Web SQLite、API Key、主密钥、临时项目或运行缓存。

## 15. 实施边界

本设计的第一目标是运行验证，不预设生产代码一定需要变化。实施计划应先提供安全启动和人工操作步骤，再执行连接与完整 run。

若全部模型兼容，代码可以保持不变，只新增脱敏审计材料以及必要的文档契约测试。若发现真实协议差异，则暂停矩阵中的后续付费调用，形成可复现失败，再单独设计和实施最小兼容性修复。

## 16. 完成标准

本阶段完成必须同时满足：

- 四个模型均有真实、脱敏、可区分层级的兼容性结论。
- 至少一个模型完成 WebUI 的完整可信 run。
- `qwen3.7-max` 完成 CLI 直接本地工作区验证。
- 没有把连接成功误写成 Action 或完整兼容。
- 没有凭据进入聊天、命令历史、截图、工件、Trace、报告或 Git。
- 所有失败和重试均如实记录。
- 如果发生代码修改，必须经过根因分析、TDD 和完整回归；没有观察到问题时不做适配性重构。
