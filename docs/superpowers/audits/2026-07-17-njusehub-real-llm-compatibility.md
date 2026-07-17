# NJU SE Hub 真实 LLM 兼容性验证审计

日期：2026-07-17

## 1. 范围与安全边界

本次验证只在本机运行 SpecGate WebUI 和 CLI，未部署公网服务。测试目标是确认用户提供的 NJU SE Hub OpenAI-compatible API 能否驱动 SpecGate 的严格 JSON Action、文件工具、HTML Gate、`finish` 和工件发布流程。

公开接口信息：

```text
Base URL: https://njusehub.info/v1
Chat Completions: https://njusehub.info/v1/chat/completions
```

API Key 由用户在本地 WebUI 或 PowerShell 隐藏输入中录入，没有发送给 Agent。验证材料不记录 Key、Authorization 请求头、Web 凭据主密钥或 Provider 响应正文。Web 与 CLI 验证结束后，用户均清除了 API Key；Web 服务正常关闭，敏感环境变量随后删除。

## 2. 接口契约

SpecGate 使用 Bearer 鉴权和 OpenAI-compatible Chat Completions，请求包含 `model`、`messages`、`temperature=0` 和输出 token 上限。响应必须提供字符串形式的 `choices[0].message.content`。完整 run 还要求该字符串是单个严格 JSON Action 对象。

本审计中的兼容性分级如下：

- 接口兼容：真实请求和标准响应结构可用。
- Action 兼容：返回内容可由 SpecGate 解析为严格 JSON Action。
- 完整兼容：run 为 `completed`，Trust 为 `trusted`，Gate 通过且发布两个工件。

## 3. WebUI 四模型兼容性矩阵

四次 run 均使用 `review`、`injection-safe`、`max_steps=4`，初始项目不包含 `index.html`。表中的 `llm_calls` 是逻辑模型调用数，不等同于 HTTP 传输尝试次数；当前公开 Trace 无法确定传输层内部重试次数。

| 模型 | Run | 状态 | Trust | Steps | LLM calls | Tool calls | Parse errors | Blocked | Gate failures | Finish | Approvals | Artifacts | 结论 |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `qwen3.7-max` | #1 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 | 完整兼容 |
| `kimi-k2.7-code` | #2 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 | 完整兼容 |
| `glm-5.2` | #3 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 | 完整兼容 |
| `deepseek-v4-pro` | #4 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 | 完整兼容 |

四个模型均完成 `write_file(index.html)`、Gate 通过、`finish`、最终 Gate 通过的两步基线。所有 run 均记录 `llm_mode=openai-compatible`，没有降级到 Mock。

## 4. qwen3.7-max Web 运行证据

- Run ID：#1。
- 状态：`completed`。
- Trust：`trusted`，原因 `clean_finish`。
- `llm_mode`：`openai-compatible`。
- `llm_model`：`qwen3.7-max`。
- `steps=2`、`llm_calls=2`、`tool_calls=2`。
- `parse_errors=0`、`blocked_actions=0`、`gate_failures=0`。
- `finish_actions=1`、`approval_requests=0`、`artifact_count=2`。
- 最大上下文：2957 字符。
- 产物：355 B 的 `index.html` 和 369 B 的 ZIP。
- 创建时间：2026-07-17T04:14:29.740493+00:00。
- 完成时间：2026-07-17T04:14:49.326017+00:00。

模型第一步返回合法 `write_file` Action，生成包含 `NJU School API Smoke Test`、`qwen3.7-max compatibility verified`、viewport 和搜索框的离线 HTML；第二步返回合法 `finish` Action。

结论：接口兼容、Action 兼容、完整兼容。

## 5. kimi-k2.7-code Web 运行证据

- Run ID：#2。
- 状态：`completed`。
- Trust：`trusted`，原因 `clean_finish`。
- `llm_mode`：`openai-compatible`。
- `llm_model`：`kimi-k2.7-code`。
- `steps=2`、`llm_calls=2`、`tool_calls=2`。
- `parse_errors=0`、`blocked_actions=0`、`gate_failures=0`。
- `finish_actions=1`、`approval_requests=0`、`artifact_count=2`。
- 最大上下文：3930 字符。
- 产物：1232 B 的 `index.html` 和 756 B 的 ZIP。
- 创建时间：2026-07-17T04:18:40.462352+00:00。
- 完成时间：2026-07-17T04:19:06.561747+00:00。

模型第一步返回合法 `write_file` Action，并生成带内联样式、搜索标签和搜索框的离线 HTML；第二步返回合法 `finish` Action。运行期间曾截取到 `publishing` 瞬时页面，最终 JSON 和后续页面均确认发布完成，不作为失败记录。

结论：接口兼容、Action 兼容、完整兼容。

## 6. glm-5.2 Web 运行证据

- Run ID：#3。
- 状态：`completed`。
- Trust：`trusted`，原因 `clean_finish`。
- `llm_mode`：`openai-compatible`。
- `llm_model`：`glm-5.2`。
- `steps=2`、`llm_calls=2`、`tool_calls=2`。
- `parse_errors=0`、`blocked_actions=0`、`gate_failures=0`。
- `finish_actions=1`、`approval_requests=0`、`artifact_count=2`。
- 最大上下文：3879 字符。
- 产物：1296 B 的 `index.html` 和 863 B 的 ZIP。
- 创建时间：2026-07-17T04:58:06.530551+00:00。
- 完成时间：2026-07-17T04:58:23.324472+00:00。

模型第一步返回合法 `write_file` Action，生成包含离线样式、搜索框和兼容性文本的 HTML；第二步返回合法 `finish` Action。

结论：接口兼容、Action 兼容、完整兼容。

## 7. deepseek-v4-pro Web 运行证据

- Run ID：#4。
- 状态：`completed`。
- Trust：`trusted`，原因 `clean_finish`。
- `llm_mode`：`openai-compatible`。
- `llm_model`：`deepseek-v4-pro`。
- `steps=2`、`llm_calls=2`、`tool_calls=2`。
- `parse_errors=0`、`blocked_actions=0`、`gate_failures=0`。
- `finish_actions=1`、`approval_requests=0`、`artifact_count=2`。
- 最大上下文：3072 字符。
- 产物：446 B 的 `index.html` 和 431 B 的 ZIP。
- 创建时间：2026-07-17T05:00:38.396744+00:00。
- 完成时间：2026-07-17T05:00:52.360291+00:00。

模型第一步返回合法 `write_file` Action，生成最小离线 HTML；第二步返回合法 `finish` Action。

结论：接口兼容、Action 兼容、完整兼容。

## 8. qwen3.7-max CLI 直接文件证据

CLI 使用全新的系统临时目录作为 workspace，初始只包含 `TASK_SPEC.md` 和 `CHECKLIST.md`。用户通过 PowerShell 隐藏输入把 API Key 放入当前进程环境，运行结束后立即清除。

实际输出：

```text
SpecGate run finished: passed=True, steps=2
CLI exit code: 0
```

用户随后执行三个 `Test-Path` 检查，结果均为 `True`：

- 临时工作区中的 `index.html`。
- `runs/latest/trace.jsonl`。
- `reports/latest/index.html`。

这证明 CLI 能使用 NJU SE Hub 的 `qwen3.7-max` 直接修改指定本地工作区，而不是只修改 WebUI 导入副本。

## 9. 失败、重试与人工操作

### 9.1 连接测试假超时

首次 WebUI 连接测试返回 `LLM request timed out`。调查得到以下事实：

- `njusehub.info` 解析为 `47.84.206.104`。
- TCP 443 检查成功。
- 不带凭据的 `/v1/models` 请求在 1.874096 秒内返回 HTTP 401，证明 DNS、TCP、TLS 和 HTTP 路径可达。
- 使用 SpecGate `OpenAICompatibleLLM`、60 秒 timeout 和 8-token 上限执行脱敏诊断，得到 `success elapsed=13.368s content_chars=45`。

根因为 WebUI 连接测试硬编码 10 秒 deadline，而 `qwen3.7-max` 的本次有效响应耗时超过 10 秒。该现象是客户端假超时，不是 NJU SE Hub 认证或协议失败。

修复采用 TDD：回归测试先观察到 `AssertionError: 10.0 != 47.0`，随后让连接测试读取 `SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS` 对应的 `LLMNetworkConfig.request_timeout_seconds`，同时保留单次尝试和 8-token 上限。

修复证据：

- 功能 commit：`a5861aa`。
- PR #22。
- 合并 commit：`3905e1e`。
- 相关回归：`Ran 65 tests in 46.572s`、`OK (skipped=1)`。
- 完整回归：`Ran 920 tests in 211.022s`、`OK (skipped=27)`。
- `python -m compileall -q src tests` 通过。
- `node --check src/specgate/web_static/app.js` 通过。
- 修复后使用 60 秒配置重新执行真实 `qwen3.7-max` 连接测试，页面显示“模型服务连接测试通过”。

### 9.2 人工操作与重试边界

以下操作由用户人工完成：

- 生成 Web 凭据主密钥并启动本地 WebUI。
- 在本地页面输入和清除 API Key。
- 创建四个相互隔离的测试项目并发起 run。
- 检查和发送不含凭据的截图、HTML 与原始 JSON。
- 通过隐藏输入执行 CLI 验证并清除进程环境中的 Key。
- 执行全部 Git、PR、合并和 worktree 清理操作。

初次连接测试超时后没有连续点击重试，而是先完成无凭据网络分层检查和一次 60 秒脱敏诊断。其余三个模型没有单独点击存在假阴性风险的旧连接按钮；它们各自的两步完整 run 已同时证明接口、Action 和完整流程兼容。修复后只重新执行一次 `qwen3.7-max` 连接测试。

Git 推送曾出现四次临时 TLS connect error，第五次成功。该问题发生在 GitHub 推送链路，与 NJU SE Hub 模型兼容性无关。

### 9.3 当前审计分支验证

审计材料完成后重新执行验证，结果如下：

- 审计契约：`Ran 1 test in 0.001s`、`OK`。
- 最终证据测试：`Ran 20 tests in 0.232s`、`OK`。
- LLM、传输、Web 与最终证据相关回归：`Ran 112 tests in 43.464s`、`OK (skipped=1)`。
- 完整套件：`Ran 921 tests in 395.229s`、`OK (skipped=27)`。
- `python -m compileall -q src tests`：退出码 0。
- `node --check src/specgate/web_static/app.js`：退出码 0。

这些数字属于当前审计分支，和 9.1 节记录的 PR #22 修复阶段 920 个测试的历史结果不是同一次运行。

## 10. 结论

NJU SE Hub 的 `qwen3.7-max`、`kimi-k2.7-code`、`glm-5.2` 和 `deepseek-v4-pro` 均与 SpecGate 当前 WebUI 完整兼容。四个模型都在两步内完成严格 JSON Action、文件写入、两次 Gate、`finish` 和双工件发布，未发生解析错误、阻断、Gate 失败或审批请求。

`qwen3.7-max` 还通过 CLI 直接本地工作区验证。测试暴露的 Web 连接测试假超时已通过 PR #22 修复并合并到 `main@3905e1e`。本阶段未部署公网服务，真实凭据未进入仓库或审计材料。
