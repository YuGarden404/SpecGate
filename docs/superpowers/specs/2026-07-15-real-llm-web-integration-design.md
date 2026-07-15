# SpecGate Web 真实 LLM 接入设计

日期：2026-07-15

## 1. 背景

SpecGate 已经具备自研 Agent 主循环、严格 JSON Action Parser、Tool Dispatcher、WorkspacePolicy、HITL、最终 Gate、运行目录隔离、安全凭据存储、固定 worker、有界队列、取消与超时、运行配置快照、审计脱敏和发布 SHA-256 绑定。Web 产品当前虽然可以使用 AES-256-GCM 保存 `openai-compatible` API Key，但首次执行与审批恢复仍固定构造 `MockLLM`，保存凭据不会启用真实模型。

本阶段在不改变 Harness 主体结构的前提下，为 Web 产品接入 OpenAI-compatible Chat Completions。用户未保存 API Key 时继续使用默认 `MockLLM`；用户安全保存 API Key、Base URL 和 Model 后，新 run 使用真实模型，根据 `TASK_SPEC.md`、`CHECKLIST.md` 和可选现有 `index.html` 产生严格 JSON Action，最终创建或修改 `index.html`。

真实模型只替换 Harness 中“决定下一步动作”的可注入 LLM 部件。它不能直接写文件、绕过审批、宣布 Gate 通过或发布产物。所有输出仍必须依次经过 Context、Action Parser、WorkspacePolicy、Tool Dispatcher、HITL、最终 Gate 和发布哈希校验。

## 2. 课程需求对齐

本设计遵守《AI4SE 期末项目 · 通用要求》和《AI4SE Final Project A · Coding Agent Harness》的以下边界：

- Agent 主循环继续由 SpecGate 自己实现，不接入 LangChain AgentExecutor、AutoGen、CrewAI、LlamaIndex Agent 或供应商原生 Agent Runner。
- LLM 抽象保持可注入，核心机制继续使用 `MockLLM` / StubLLM 做离线确定性测试。
- 真实模型只通过底层单次对话补全 API 产生 Action；工具分发、治理拦截、反馈闭环、记忆、停机和 Gate 均由代码实现。
- 移除真实 LLM 后，路径治理、HITL、反馈回灌、上下文策略、取消、超时、恢复和发布绑定仍能独立测试。
- API Key 不硬编码、不提交 Git、不进入普通设置、运行快照、日志、Trace、异常或前端响应。
- 设计与实施继续遵循 Superpowers、TDD、验证后再声明完成以及中文过程材料优先的要求。
- 真实 Provider 的成功率不成为课程核心机制的通过条件；自动测试不访问真实网络。

因此，本阶段是既有 Harness 的可选真实决策源接线，不把项目改造成依赖真实模型才能证明机制的应用封装。

## 3. 已确认决策

- 用户可以配置 API Key、Base URL 和 Model。
- 第一版只支持 OpenAI-compatible Chat Completions，不支持 Responses API。
- 未保存凭据记录时默认使用 `MockLLM`。
- 存在可用 API Key 时必须使用真实模式；配置或调用失败均 fail closed，不自动回退 Mock。
- 缺少 `index.html` 时允许直接创建；覆盖导入或已有 `index.html` 时必须进入 HITL。
- `408`、`429`、`5xx` 和临时网络错误最多重试两次；认证、非法请求、安全校验和响应格式错误不重试。
- 保存设置只做本地校验，不访问 Provider；连接验证由独立“测试连接”操作触发。
- run 只保存不可逆 credential fingerprint，不复制密钥或密文。
- 用户更新、清除或重新加密 API Key 后，旧真实 run 在下一次 Provider 调用前以安全错误失败。
- Base URL 的主机必须位于部署环境变量 `SPECGATE_LLM_ALLOWED_HOSTS`；只允许公网 HTTPS，禁止重定向和 DNS Rebinding。
- LLM 配置使用独立 `LLMRunConfig`，不混入 `RunRuntimeConfig`；Provider 判断集中在 `WebLLMFactory`，不散落在 `web_runs.py`。

## 4. 目标

- 让 Web run 在默认 Mock 与用户配置的真实 OpenAI-compatible 模式之间安全切换。
- 让真实模型看到与 Mock Runner 相同的受治理 Context，并只返回严格 JSON Action。
- 让首次执行与审批恢复通过同一 Factory 构造 LLM，消除模式分叉。
- 冻结每个 run 的模型模式、Base URL、Model 和凭据版本身份，避免设置漂移。
- 阻止 SSRF、DNS Rebinding、重定向、私网访问、无界响应、无界重试和凭据泄漏。
- 提供不创建 run、不修改项目的独立连接测试能力。
- 保持课程默认 Mock 演示、固定 worker、有界队列、HITL、Gate 和发布语义不变。

## 5. 非目标

- 不实现 OpenAI Responses API、流式输出或 Provider 原生 tool calling。
- 不实现多 Provider 专用适配器、自定义请求头、非 Bearer 认证或 Provider 自动发现。
- 不允许 HTTP、私网 Provider、IP 字面量、通配符主机白名单或自动重定向。
- 不实现 OAuth、团队共享凭据、在线主密钥轮换或后台定时健康检查。
- 不实现调用失败后的模型切换或真实模式到 Mock 模式的自动降级。
- 不实现通用聊天界面、多文件网站生成框架或同源执行模型生成页面。
- 不修改现有 Action schema、WorkspacePolicy 写入范围、Gate 规则或 HITL 判定语义。
- 不把真实网络调用加入 CI、单元测试或课程核心验收。

## 6. 架构

### 6.1 组件职责

`LLMRunConfig`

- 表示 run 创建时冻结的 LLM 模式快照。
- 严格解析 `runs.llm_config_json`，拒绝未知字段、非法模式和不一致组合。
- 与治理、上下文和预算字段组成的 `RunRuntimeConfig` 独立演进。

`LLMEndpointPolicy`

- 解析和规范化 Base URL。
- 校验 HTTPS、精确主机白名单、端口、路径、长度和 URL 组成部分。
- 在保存设置、测试连接和正式调用三个阶段复用。

`PublicDNSResolver`

- 在固定大小的解析执行器中解析 A/AAAA 地址。
- 对解析设置有界超时，并拒绝任何非公网结果。
- 返回本次请求可以使用的已校验 IP 集合。

`SafeHTTPSChatTransport`

- 直接连接到已校验 IP，同时使用原始主机名完成 TLS SNI、证书校验和 HTTP `Host`。
- 不使用系统代理、不自动重定向，并对请求、响应、取消和 deadline 实施边界。
- 只返回成功响应的受限字节，不读取上游错误正文。

`OpenAICompatibleLLM`

- 构造 Chat Completions 请求并提取 `choices[0].message.content`。
- 继续实现现有 `LLMClient.complete(context: str) -> str` 协议。
- 不执行 Action，不宽松修复模型输出，也不接触 Workspace。

`WebLLMFactory`

- 是 Web 首次执行和审批恢复获得 LLM 的唯一入口。
- Mock 模式返回现有 `MockLLM` 脚本。
- 真实模式创建凭据绑定的 OpenAI-compatible 客户端。
- 在每次 Provider 调用前重新检查 credential fingerprint，避免一个长 run 永久持有已经失效的 Key。

`LLMConnectionTestService`

- 使用已经保存的设置和凭据发起最小 Chat Completions 请求。
- 复用正式调用的 URL、DNS、TLS、响应和脱敏边界。
- 不创建 run、不解析 Action、不执行工具、不修改项目。

### 6.2 依赖方向

```text
Web Settings / Run Creation
        │
        ├── LLMEndpointPolicy
        ├── WebCredentialService
        └── LLMRunConfig snapshot
                    │
WebRuntimeCoordinator
        │
        └── web_runs.execute/resume
                    │
              WebLLMFactory
                    │
          OpenAICompatibleLLM
                    │
          SafeHTTPSChatTransport
                    │
       PublicDNSResolver + TLS socket
```

Runner 只依赖 `LLMClient`，不知道当前是 Mock 还是真实 Provider。网络安全组件不知道 Runner、Workspace 或 Gate 的存在。

## 7. 数据模型与 schema v5

### 7.1 `user_settings`

新增：

- `llm_base_url text`
- `llm_model text`

两列允许为 `NULL`。API Key 仍只存在 `user_credentials` 的 AES-256-GCM 密文列中；不恢复旧的 `user_settings.api_key_ciphertext` 作为真实凭据来源。

### 7.2 `runs`

新增：

- `llm_config_json text`

严格 JSON 结构：

```json
{
  "schema_version": 1,
  "source": "created",
  "mode": "mock",
  "base_url": null,
  "model": null,
  "credential_fingerprint": null
}
```

字段约束：

- `schema_version` 只接受整数 `1`。
- `source` 只接受 `created` 或 `migration-v5`。
- `mode` 只接受 `mock` 或 `openai-compatible`。
- Mock 模式的 URL、Model 和 fingerprint 必须全部为 `null`。
- 真实模式的 URL、Model 和 fingerprint 必须都是经过校验的非空字符串。
- fingerprint 使用 64 位小写十六进制 SHA-256 表示。
- 解析拒绝布尔值伪装整数、未知字段、重复语义和模式/字段不一致。

### 7.3 credential fingerprint

fingerprint 不是 API Key 的哈希，避免为低熵密钥提供直接离线猜测材料。它由当前 `user_credentials` 行的以下字段按带长度前缀的规范编码计算 SHA-256：

- provider
- status
- ciphertext
- nonce
- key_version
- key_id
- updated_at

由于 AES-GCM 每次保存使用随机 nonce，即使用户重新录入同一个 Key，fingerprint 也会变化。更新、重新加密、迁移或清除凭据都会使旧真实 run 无法继续使用当前凭据。

fingerprint 可以写入 run 快照用于相等性比较，但不返回设置 API，也不显示在 UI、Trace 或普通日志中。

### 7.4 v4 到 v5 迁移

迁移在 `BEGIN IMMEDIATE` 中执行：

1. 为 `user_settings` 增加 URL 和 Model 列。
2. 为 `runs` 增加 `llm_config_json`。
3. 所有历史 run 回填 `source="migration-v5"` 的 Mock 快照。
4. 验证不存在空快照。
5. 设置 `pragma user_version = 5` 并提交。

迁移不会根据用户当前凭据推断历史 run 曾使用真实模型。v1、v2、v3、v4 均继续逐级迁移到 v5；未知未来版本继续拒绝启动。

## 8. 模式状态机

| 当前凭据与设置 | 设置状态 | 新 run 行为 |
|---|---|---|
| 没有凭据记录 | `mock` | 使用 MockLLM |
| 只有 URL/Model，没有凭据记录 | `mock` | 使用 MockLLM |
| 可用 Key、URL、Model 完整 | `openai-compatible` | 使用真实 LLM |
| 可用 Key，但 URL 或 Model 缺失 | `configuration_required` | 阻止创建 |
| 凭据需要重录、无法解密或存储不可用 | `configuration_required` | 阻止创建 |

“没有凭据记录”和“存在但不可用的凭据”必须区分。前者是用户没有选择真实模式，允许 Mock；后者说明用户曾选择真实模式但安全状态异常，必须 fail closed。

设置响应中的 `llm_configuration_complete` 表示当前状态是否允许创建 run：正常 Mock 与完整真实配置为 `true`，半配置或不可用凭据为 `false`。

### 8.1 创建 run

扩展现有 `_reserve_initializing_run()` 的 `BEGIN IMMEDIATE` 事务，在同一数据库快照中：

1. 校验项目所有权与活动 run 配额。
2. 读取用户运行设置。
3. 读取 `openai-compatible` 凭据行。
4. 判定模式并构造 `LLMRunConfig`。
5. 将 `runtime_config_json` 和 `llm_config_json` 一起写入 run。

配置错误发生在 run 行和 run storage 创建之前，因此不会留下半初始化 workspace、队列任务或不可恢复 run。

### 8.2 设置变化

- 修改 URL 或 Model 只影响之后创建的新 run。
- 修改、重新保存或清除 API Key 会改变之后的新 run，并使旧真实 run 的 fingerprint 检查失败。
- 清除 Key 后，新 run 恢复 Mock；旧真实 run 不会降级，而是以 `credential_missing` 失败。
- 收紧部署主机白名单立即约束所有后续调用，包括旧 run 的审批恢复。
- 连接测试成功不是创建真实 run 的前置条件；正式调用始终重新执行全部校验。

单个已经创建的 run 不允许切换模式。Provider 已经收到的请求无法被凭据更新追溯撤回；更新会在下一次调用前生效，用户若要终止正在进行的请求应同时取消 run。

## 9. Provider Factory 与执行数据流

### 9.1 首次执行

```text
读取 run
  → 解析 RunRuntimeConfig 与 LLMRunConfig
  → WebLLMFactory 创建 LLM
  → Runner 构造 SPEC / Checklist / index.html Context
  → LLM 返回一个严格 JSON Action
  → Action Parser
  → WorkspacePolicy
  → Tool Dispatcher / HITL
  → 最终 Gate
  → 发布 SHA-256 绑定产物
```

Mock 分支继续使用固定、确定性的响应序列。真实分支读取冻结的 URL/Model，但在每次调用前从凭据服务读取当前行、比较 fingerprint 并短暂解密 API Key。

### 9.2 审批恢复

审批恢复不从当前 Settings 重新推断模式，而是：

1. 读取原 run 的 `llm_config_json`。
2. 使用同一个 `WebLLMFactory`。
3. 真实模式重新验证 fingerprint、白名单、DNS 和 TLS。
4. 从持久化审批队列与 Runner 状态恢复。
5. 继续后续 Action、最终 Gate 和发布。

首次执行与恢复共用 Runner 构造辅助函数，差异只保留 Mock 响应脚本、`reset_audit` 和 `run()` / `resume_from_approval()` 入口，避免一条路径真实、一条路径意外 Mock。

### 9.3 文件与审批边界

现有 Web WorkspacePolicy 保持：

- 可读：`TASK_SPEC.md`、`CHECKLIST.md`、`index.html`
- 可写：仅 `index.html`
- 允许 Action：`read_file`、`list_files`、`write_file`、`replace_file`、`finish`

首次创建不存在的 `index.html` 可以直接执行；覆盖已有文件必须由治理配置生成 HITL。模型不能通过返回完整 HTML 绕过 Action Parser，也不能声明自己的输出已经通过 Gate。

## 10. URL、DNS 与 SSRF 防护

### 10.1 部署白名单

环境变量：

```text
SPECGATE_LLM_ALLOWED_HOSTS=api.openai.com,api.example.com
```

- 默认空白名单，即部署保持 Mock-only。
- 只接受逗号分隔的精确主机名或显式 `host:port`。
- 不支持 `*` 或后缀通配。
- 主机名按小写、去尾点和 IDNA 规则规范化。
- 未标端口时只允许 443；非 443 必须在白名单中精确声明。
- 白名单条目格式非法时应用启动失败。

### 10.2 URL 静态校验

- scheme 必须为 `https`。
- 禁止 username、password、query 和 fragment。
- 禁止 IPv4/IPv6 字面量。
- 拒绝空主机、控制字符、超长 URL、异常转义和 `.` / `..` 路径段。
- 允许 `/v1` 等基础路径；最终端点固定追加 `/chat/completions`。
- 追加端点后再次确认 scheme、host 和 port 未改变。

保存设置执行上述静态校验和白名单校验，但不解析 DNS、不发起网络请求。

### 10.3 DNS 公网校验

测试连接和正式调用前解析全部 A/AAAA 结果。任意结果不满足 `ipaddress.ip_address(value).is_global` 时整体拒绝，包括环回、私网、链路本地、保留、多播、未指定、文档与特殊用途地址。混合“公网 + 私网”也拒绝。

DNS 在固定大小的专用执行器中执行，受剩余 deadline 约束。解析线程超时后不会被复用为无界新线程；解析容量耗尽时 fail closed。

### 10.4 DNS Rebinding 与 TLS

普通客户端若在安全检查后再次按域名解析，会留下 DNS Rebinding 窗口。安全传输必须：

- 只连接本次已验证的 IP。
- 在多个已验证地址之间做有界尝试。
- TLS `server_hostname` 和 HTTP `Host` 使用原白名单主机。
- 使用系统 CA 和默认主机名校验，不提供跳过证书选项。
- 不读取 `HTTP_PROXY`、`HTTPS_PROXY` 或系统代理设置。
- 不在连接阶段重新解析域名。

### 10.5 禁止重定向

`301`、`302`、`303`、`307`、`308` 均返回 `llm_redirect_forbidden`，不读取 `Location`、不自动跟随。即使目标仍在白名单，用户也必须显式保存并重新校验新 Base URL。

## 11. 调用资源边界

### 11.1 deadline 与取消

真实调用复用现有 `RunControl`：

- run 总超时仍由 `SPECGATE_WEB_RUN_TIMEOUT_SECONDS` 控制。
- `RunControl` 增加只读剩余秒数能力，并与 `stop_check` 一起注入真实客户端。
- 单次请求超时取部署上限与 run 剩余时间的较小值。
- DNS、连接、发送、读取、重试和退避都计入总超时。
- 审批等待不计时；恢复由 Coordinator 提供新的有界执行窗口。

取消检查发生在 DNS 前后、连接前后、发送前、分块读取期间、每次重试前和退避期间。网络 socket 使用短周期 timeout 轮询取消。取消后关闭连接，不解析未完成响应、不执行 Action、不发布产物，run 进入 `cancelled`。

### 11.2 重试

最多三次请求，即首次加两次重试。

允许重试：

- HTTP `408`、`429`、`500`–`599`
- 临时 DNS 失败
- 连接超时、连接重置、远端提前关闭等临时网络错误

禁止重试：

- HTTP `400`、`401`、`403`、`404`、`422`
- TLS 证书失败
- URL、白名单、地址和重定向错误
- 成功响应 JSON 或结构错误
- LLM content 不是合法 Action
- 用户取消或 run deadline 到期

退避约为 0.5 秒和 1 秒，时钟、等待器和抖动源可注入测试。剩余时间不足时不再请求。只有完整响应通过结构和 Action 校验后才执行工具，因此 Provider 重试不会重复写文件或重复生成审批。

### 11.3 请求和响应限制

新增部署变量：

```text
SPECGATE_LLM_MAX_OUTPUT_TOKENS=4096
SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS=30
```

- output token 范围为 256–16384。
- 单次请求超时范围为 1–120 秒，且受 run 剩余时间进一步限制。
- 变量格式或范围非法时应用启动失败。
- 成功响应体最大 1 MiB。
- `Content-Length` 超限立即拒绝；缺少长度时分块读取并在越界时关闭连接。
- 只接受可解码的 UTF-8 JSON。
- 上游错误响应正文不读取、不保存、不展示。
- 第一版不使用流式输出，避免部分 JSON 和断流恢复歧义。

`SPECGATE_LLM_ALLOWED_HOSTS`、output token 和请求超时不是秘密，可以进入普通部署配置。`SPECGATE_WEB_CREDENTIAL_KEY` 是加密主密钥，生产环境应通过平台 Secret、Docker Secret 或权限受限且不提交 Git 的环境文件注入，不得把明文值直接写进命令行或部署脚本；环境文件仍具有明文和进程环境可见风险，部署文档必须明确说明。

### 11.4 Chat Completions 契约

请求固定包含：

- 冻结的 `model`
- system message：只允许返回一个严格 JSON Action，不得输出 Markdown 或解释文字
- user message：Runner 生成的当前 Context
- `temperature: 0`
- 部署限制的 `max_tokens`

响应依次经过 HTTP 状态、大小、JSON、`choices[0].message.content` 字符串和现有 Action Parser 校验。客户端不删除代码围栏、不提取混杂 JSON，也不自动补字段。

## 12. 凭据生命周期与脱敏

### 12.1 每次调用检查

真实 LLM 使用凭据绑定包装器。每次 `complete()`：

1. 调用 stop check。
2. 原子读取当前凭据行并计算 fingerprint。
3. 与 run 快照比较。
4. 使用现有 AES-256-GCM 服务解密。
5. 发起一次受控 Provider 请求。
6. 丢弃本次调用对明文 Key 的引用。

配置、Factory、Transport 和异常对象均不得在 `repr` 中包含 Key。已经进入网络栈的单次请求不能被后续 Key 更新追溯撤销，但下一次模型调用必须看到变化。

### 12.2 稳定错误码

- `llm_configuration_required`
- `credential_missing`
- `credential_changed`
- `credential_requires_reentry`
- `credential_unavailable`
- `llm_url_invalid`
- `llm_host_not_allowed`
- `llm_dns_resolution_failed`
- `llm_address_not_public`
- `llm_redirect_forbidden`
- `llm_tls_failed`
- `llm_request_timeout`
- `llm_rate_limited`
- `llm_authentication_failed`
- `llm_request_rejected`
- `llm_provider_unavailable`
- `llm_response_too_large`
- `llm_response_invalid`
- `llm_action_invalid`

run 失败沿用现有安全 `error_message` 字段保存稳定错误码，不保存 Provider 正文、底层地址、Authorization、Prompt 或 traceback。

### 12.3 不得出现明文的位置

- `user_settings`
- `runs.llm_config_json`
- Trace、Runner evidence、报告与发布清单
- HTTP 响应和前端 state
- Python 异常、`repr` 和应用日志
- 测试连接结果
- Provider 错误正文

## 13. 设置 API 与 UI

### 13.1 设置读写

`PUT /api/settings` 扩展 `llm_base_url` 和 `llm_model`。所有运行配置与 LLM 字段先整体校验，再在一个事务中更新，防止部分写入。该请求不访问网络。

`GET /api/settings` 增加：

- `llm_mode`: `mock`、`openai-compatible` 或 `configuration_required`
- `llm_base_url`
- `llm_model`
- `llm_configuration_complete`
- 现有 API Key 状态字段

不返回 fingerprint、密文、nonce、Key ID 或 API Key 掩码。API Key 继续通过现有独立 PUT/DELETE 接口保存与清除，保存成功后前端立即清空密码输入框且永不回填。

### 13.2 测试连接

新增：

```http
POST /api/settings/llm/test
```

请求体为空，不接受临时 URL、Model 或 API Key，只读取当前用户已保存配置。流程为：配置完整性 → 凭据解密 → URL/白名单 → DNS 公网校验 → 固定 IP TLS → 最小 Chat Completions → 标准响应结构校验。

测试请求使用同一 Model、`temperature=0` 和极小输出上限，但不执行返回 content。选择 `/chat/completions` 而不是 `/models`，因为兼容服务不一定实现模型列表接口。

测试连接：

- 硬超时 10 秒。
- 不自动重试。
- 使用专用全局有界并发限制。
- 同一用户只允许一个并发测试，并设置短暂冷却。
- 不创建 run、Action、审批、Trace 或项目产物。
- 结构化安全日志只记录用户 ID、规范化主机、Model、稳定结果码和时间。

成功返回 `ok=true` 和中文提示；失败返回稳定 code，不展示模型生成内容。

### 13.3 UI 状态

设置页增加 Model Service 区域：

- 当前模式状态卡
- Base URL 输入
- Model 输入
- API Key 密码输入
- 保存模型设置、保存 Key、清除 Key、测试连接按钮

状态文案明确区分：

- `Mock 模式：未配置 API Key`
- `真实模型：配置完整`
- `配置未完成：请补充 Base URL 和 Model`
- `API Key 需要重新录入`
- `安全凭据存储不可用`

项目运行按钮附近显示即将使用的模式。配置未完成时前端禁用运行并提供设置页入口，后端同时拒绝绕过。run 详情只显示冻结的 `llm_mode` 和 `llm_model`，不显示 fingerprint；Mock run 不显示无关 URL/Model。

## 14. HTTP 错误映射

| 场景 | 稳定 code | 测试连接 HTTP |
|---|---|---:|
| 配置不完整 | `llm_configuration_required` | 409 |
| 凭据缺失、变化或需要重录 | 对应 credential code | 409 |
| URL 或主机非法 | `llm_url_invalid` / `llm_host_not_allowed` | 400 |
| 上游认证失败 | `llm_authentication_failed` | 502 |
| 上游拒绝请求 | `llm_request_rejected` | 502 |
| 上游限流 | `llm_rate_limited` | 502 |
| 上游不可用 | `llm_provider_unavailable` | 502 |
| 上游超时 | `llm_request_timeout` | 504 |
| 测试连接过频 | `llm_test_rate_limited` | 429 |
| 响应非法或过大 | 对应 response code | 502 |

上游 `401/403` 不作为 SpecGate HTTP 401 返回，避免与 Web 会话失效混淆。`404` 无法在不读取错误正文的情况下可靠区分错误 Base URL 和错误 Model，因此统一映射为 `llm_request_rejected`。

## 15. 测试策略

所有实现严格执行 Red-Green-Refactor。自动测试使用 `FakeResolver`、`FakeTransport`、`FakeClock`、FakeCredentialService 和脚本化 Provider，不访问真实网络。

### 15.1 配置与迁移

- 新数据库直接创建 v5。
- v1、v2、v3、v4 均升级到 v5。
- 历史 run 回填严格 Mock 快照。
- 新 run 在一个事务中冻结 runtime 与 LLM 配置。
- 半配置不创建 run 行、storage 或队列任务。
- 未知字段、错误类型、非法组合和未来 schema 被拒绝。

### 15.2 模式与凭据

- 无 Key、仅 URL/Model、完整真实配置和半配置状态表。
- 清除 Key 后新 run 回 Mock。
- 旧真实 run 对 Key 更新、重存、清除和主密钥变化 fail closed。
- canary Key 不出现在数据库快照、Trace、响应、异常、日志和对象表示。
- 真实调用失败不创建 Mock 客户端。

### 15.3 SSRF 与 Transport

- HTTPS、精确白名单、默认端口和显式端口。
- userinfo、query、fragment、IP 字面量、IDNA 和异常路径。
- IPv4/IPv6 的公网与全部非公网分类。
- 混合公网/私网解析整体拒绝。
- 固定 IP 连接仍保留原 SNI/Host。
- 系统代理不参与请求。
- 所有重定向被拒绝。
- 响应大小、UTF-8、JSON 与 choices 结构。

### 15.4 重试、取消和超时

- `408`、`429`、`5xx` 与临时网络错误最多重试两次。
- 认证、非法请求、TLS、安全校验和非法响应不重试。
- FakeClock 验证退避，不真实等待。
- deadline 不足时停止重试。
- DNS、读取和退避期间均响应取消。
- 重试不会重复执行工具或审批。

### 15.5 Runner、HITL 与 Gate

- 真实 Stub 收到 SPEC、Checklist 和可选 `index.html` Context。
- 缺少 `index.html` 时创建成功。
- 已有 `index.html` 时暂停审批，未审批前不覆盖、不发布。
- 审批恢复使用冻结配置和同一 Factory。
- fingerprint 变化时不消耗后续 Action、不发布。
- 非法 content 不执行工具。
- 最终 Gate 重新检查实际文件，发布 SHA-256 与 Gate artifact 一致。

### 15.6 API 与前端

- 保存设置不调用网络。
- 设置响应不暴露密钥材料。
- 测试连接只使用已保存配置且不创建 run。
- 测试连接并发、冷却、超时和错误映射。
- Mock、真实、配置未完成和 run 冻结模式正确显示。
- 前端不回填 Key、不展示 Provider content 或 fingerprint。

### 15.7 回归验证

- 全量 `python -m unittest discover -s tests`
- `python -m compileall -q src tests`
- `node --check src/specgate/web_static/app.js`
- 文档/工作流契约测试
- `git diff --check`

测试进程若发生未注入的 DNS 或 socket 网络访问，应直接失败。

## 16. 文档、部署与证据

实施完成后同步：

- `SPEC.md`：更新 Web 真实模式、凭据威胁模型、外部 Provider 和验收标准。
- `PLAN.md`、`AGENT_LOG.md`：记录 TDD 红绿证据、审查和实际验证结果。
- `README.md`：清除“Web 永远只运行 Mock”旧描述，说明默认 Mock 与真实配置流程。
- `docs/DEPLOYMENT.md`：增加主机白名单、输出限制、请求超时和 Docker/PowerShell 示例。
- `docs/PROJECT_WALKTHROUGH.md`：增加真实模式受 Harness 治理的数据流。
- `docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md`、`docs/REFLECTION_FACT_CHECK.md`：只同步已经验证的事实。

不会伪造真实 Provider、CI 或部署截图。GitHub Pages 仍只是静态评审入口，不能安全保存凭据或调用真实 Provider；真实模式只存在于运行 SpecGate Web 后端的部署中。

## 17. 验收标准

- 全新用户不配置任何 Key 即可继续使用 Mock Web run，且没有外部网络访问。
- 用户保存完整、安全的 Key、Base URL 和 Model 后，新 run 使用真实 Stub Provider 而非 Mock。
- 真实模型只返回 Action，文件操作、审批、Gate 和发布仍由自研 Harness 决定。
- 缺少现有 `index.html` 可直接创建；覆盖已有文件必须 HITL。
- 首次执行和审批恢复通过同一 `WebLLMFactory`，恢复不读取当前 URL/Model 替代冻结值。
- Key 更新、清除、重新保存或不可解密时，旧真实 run fail closed 且不发布。
- Base URL 只有在精确白名单、公网 HTTPS、固定已验证 IP 和有效 TLS 下才可连接。
- 重定向、私网/环回/保留地址、系统代理、无界响应和无界重试均被阻止。
- 取消、总超时、固定 worker、有界队列和重启恢复语义保持有效。
- API Key 不出现在 Git、普通数据库列、run 快照、HTTP 响应、Trace、日志、异常或前端。
- 所有核心机制继续能在 Mock/Stub LLM 下离线确定性验证。
- 全量测试、Python 编译、JavaScript 语法、文档契约和 whitespace 检查全部通过。

## 18. 已知限制

- “OpenAI-compatible”只保证本设计使用的 Chat Completions 请求与响应子集；不同服务的额外字段、认证方式和模型能力不在兼容范围。
- 禁止错误正文意味着无法根据 Provider 自定义错误 JSON 精确区分“模型不存在”和“端点不存在”，两者统一为安全错误码。
- 更新 Key 不能撤回已经发送到 Provider 的单次请求，只能阻止后续调用；取消 run 是终止进行中工作的入口。
- DNS 超时无法强制终止操作系统内部已经开始的解析线程，因此使用固定大小解析执行器限制资源占用，并在容量耗尽时 fail closed。
- 静态 GitHub Pages 不提供真实模型功能；需要持久数据库、凭据主密钥和服务端网络策略的 Web 后端部署。
