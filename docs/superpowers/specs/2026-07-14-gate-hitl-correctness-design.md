# Gate 与 HITL 正确性加固设计

## 1. 背景

SpecGate 已具备 HTML Gate、人工审批队列、approve/deny/resume、Web 运行状态和独立 run workspace，但仍有四类正确性缺口：

1. Checklist 仅识别少量固定句式，未识别条目可能被静默忽略。
2. `finish` 可能复用旧 Gate 结果，最终产物与已验证内容不一致。
3. 创建审批后 Runner 仍可能继续调用 LLM，核心暂停语义不成立。
4. JSON 审批队列缺少并发版本控制，重复决策或恢复可能覆盖状态或重复执行动作。

本阶段采用增量加固，不重写 run storage，不迁移审批真源到 SQLite，不接入真实 LLM。

## 2. 目标

- 让每个 Checklist 复选项都得到“已验证”或“明确不支持”的确定性结论。
- 让 `trusted` 只表示最终发布内容通过了最新 Gate。
- 让审批请求真正暂停，approve/deny/resume 具备可恢复、可并发验证的状态语义。
- 让 Web 默认保护已有文件，同时不阻断首次创建 `index.html`。
- 保持机制可在移除真实 LLM 后通过 MockLLM 和单元测试验证。

## 3. 非目标

- 不实现通用自然语言理解器或完整 CSS 选择器。
- 不重写完整 Runner 状态机。
- 不把审批队列迁移到数据库。
- 不重新设计 WebUI 页面。
- 不处理安全凭据存储；该工作留给 `feat-secure-credentials`。

## 4. 总体架构

### 4.1 Checklist 规则层

新增 `src/specgate/checklist_rules.py`，职责仅包括：

- 解析 Markdown 复选项及其 SpecGate 指令。
- 将规则转换为结构化数据类型。
- 使用已解析的 HTML 特征评估规则。
- 返回稳定的规则结果和错误码。

该模块不读取文件，不修改 workspace，不决定 run 状态。

### 4.2 Gate 层

`src/specgate/gate.py` 负责：

- 通过安全文件接口读取 HTML 和 Checklist。
- 执行通用 HTML 与安全基线。
- 调用 Checklist 规则层。
- 记录输入 SHA-256 并生成单次一致的 `GateResult`。

删除对所有页面强制要求搜索框的领域硬编码。搜索或过滤能力只有在 Checklist 明确要求时才检查。

### 4.3 审批存储层

`src/specgate/approvals.py` 继续以每个 run 的 JSON 文件为审批真源，并增加：

- `schema_version`
- 单调递增的 `revision`
- 跨进程锁
- compare-and-swap 更新
- 恢复中间状态所需的目标与预期内容摘要

Web API 和 Runner 必须通过审批存储层修改队列，不能自行执行“读取后覆盖写入”。

### 4.4 Runner 与 Web 层

`RunResult` 增加明确的 outcome：

- `completed`
- `needs_approval`
- `failed`

保留现有 `passed` 兼容属性，但状态判断以 outcome 为准。

Web 层负责鉴权、HTTP 状态映射和 run 数据库状态，不复制 Gate 或审批状态机逻辑。

## 5. Checklist 规则设计

### 5.1 可执行条目

以下内容视为可执行 Checklist 条目：

- `- [ ] ...`
- `- [x] ...`
- 兼容的旧式 `- 必须包含 ...`

标题、说明段落和普通非任务文本不参与规则评估。

复选框是否勾选不改变 Gate 行为；它只保留文档可读性。

### 5.2 指令格式

复选项下方可附加一条 HTML 注释指令：

```markdown
- [ ] 页面包含主标题
  <!-- specgate: selector "h1" min=1 -->

- [ ] 至少三条新闻卡片
  <!-- specgate: selector "article.news-card" min=3 -->

- [ ] 每条新闻包含标题、摘要和时间
  <!-- specgate: each "article.news-card" has "h2" ".summary" "time" -->

- [ ] 页面包含版权文字
  <!-- specgate: text "版权所有" -->

- [ ] 不依赖外部资源
  <!-- specgate: forbid external-resources -->

- [ ] 不包含脚本
  <!-- specgate: forbid scripts -->
```

### 5.3 选择器范围

首版只支持简单、确定性的选择器：

- 标签：`article`
- class：`.news-card`
- id：`#main`
- 标签与 class：`article.news-card`
- 属性存在：`[data-role]`
- 属性等值：`[type="search"]`

不支持组合器、伪类、逗号组和完整 CSS 语法。超出范围的选择器产生 `invalid_checklist_rule`。

### 5.4 兼容规则

保留少量无歧义旧句式：

- `必须包含 X` 转换为文本包含规则。
- 现有知识图谱 `class=node`、节点数量和关系高亮规则继续支持。
- 已有明确的“无外部资源”句式可转换为 `forbid external-resources`。

不扩展开放式中文正则。不能确定性映射的复选项产生 `unsupported_check`，Gate 不通过。

## 6. Gate 正确性

### 6.1 通用基线

保留以下通用检查：

- doctype、html、head、title、body
- viewport
- 禁止疑似密钥
- 默认离线产物，不允许未明确允许的外部资源

搜索框不再是通用基线。

### 6.2 最终 Gate

写入动作后仍可运行中间 Gate，为 Agent 提供反馈。`finish` 时必须无条件重新运行 Gate，不得复用中间结果。

如果最终 Gate 失败：

- `finish` 不成功。
- Gate 结果进入 runtime feedback。
- Agent 在剩余步数内继续修复。
- 达到最大步数仍失败时，outcome 为 `failed`。

### 6.3 内容绑定

`GateResult` 增加：

- `artifact_sha256`
- `checklist_sha256`

摘要基于单次安全读取获得的原始文件字节计算，不能因 UTF-8 BOM 等解码细节与发布校验产生歧义。Web 发布 HTML、ZIP 和项目 workspace 前，必须确认当前文件摘要仍与最终 Gate 一致；写入 HTML/ZIP 的同一份字节也必须再次匹配该摘要。摘要不一致时返回 `stale_gate_result`，不得发布或标记为 trusted。

## 7. HITL 状态机

### 7.1 状态迁移

```text
pending -> approved -> applying -> applied
                           \-> failed

pending -> denied -> rejected
```

非法跳转必须拒绝。

### 7.2 真正暂停

当动作需要 review 时：

1. 捕获目标文件状态和动作载荷。
2. 原子追加 `pending` 审批。
3. 写入 trace 和 metrics。
4. 立即返回 outcome `needs_approval`。

创建审批后不得继续调用 LLM、工具或 Gate。

### 7.3 默认审批策略

Web 默认策略为：

- 首次创建不存在的 `index.html`：自动执行。
- 写入任何已经存在的文件：触发审批。

风险判定必须读取目标实际状态，不能只相信 Agent 使用了 `write_file` 还是 `replace_file`，防止通过更换 action 名称绕过审批。

### 7.4 approve 与恢复

审批记录保存：

- 审批时目标是否存在及 SHA-256
- 预期写入内容 SHA-256
- 经 schema 校验的完整动作载荷

resume 时先通过 CAS 将 `approved` 转为 `applying`，再执行动作。

如果执行中断：

- 目标仍为审批前状态：允许重试。
- 目标已等于预期内容：直接恢复为 `applied`。
- 目标为第三种状态：转为 `failed`，错误码为 `approval_target_changed`。

### 7.5 deny 与重新规划

denied resume 不执行原动作。拒绝原因作为结构化反馈交给 Agent，审批记录进入 `rejected` 终态，Agent 可提出安全替代动作。

## 8. 并发控制

审批队列顶层结构：

```json
{
  "schema_version": "2",
  "revision": 3,
  "approvals": []
}
```

approve/deny 请求必须携带 `expected_revision`。存储层在跨进程锁内完成：

1. 安全读取当前队列。
2. 比较 revision。
3. 验证状态迁移。
4. 写入新队列并令 revision 加一。

缺少 revision 返回 `400`；版本过期返回 `409 approval_conflict`。

旧队列缺少版本字段时按 schema version 1、revision 0 读取；第一次成功写入时升级，不单独执行迁移脚本。

## 9. Action 协议

在风险分类和审批创建前验证动作载荷：

- `write_file` 和 `replace_file` 必须包含字符串 `path` 与字符串 `content`。
- 缺少 content 不得默认写入空字符串。
- 非法载荷产生 `invalid_action_payload`，作为可修复反馈返回 Agent。
- 非法载荷不得进入审批队列。

## 10. Web API

- `GET /api/approvals` 返回队列 revision。
- approve/deny body 增加 `expected_revision`。
- 版本冲突返回 `409`，前端刷新审批列表并提示状态已变化。
- approve/deny 后继续使用现有 resume 入口。
- `needs_approval` 时不生成正式产物，不覆盖项目 workspace。
- 本阶段仅做必要交互调整，不改 WebUI 总体布局。

## 11. 审计与错误码

稳定错误码包括：

- `unsupported_check`
- `invalid_checklist_rule`
- `approval_conflict`
- `approval_target_changed`
- `stale_gate_result`
- `invalid_action_payload`

Trace 记录 approval id、状态迁移、revision、Gate 输入摘要和失败分类。不得记录文件正文、API key 或未经脱敏的动作参数。

## 12. 测试策略

严格使用 TDD，覆盖：

1. Checklist 指令解析、兼容句式、非法与不支持条目。
2. 选择器计数、each/has、文本和 forbid 规则。
3. 删除搜索框硬编码及最终 Gate 重跑。
4. Gate 摘要与发布前摘要不一致。
5. 创建审批后 LLM 和工具调用次数不再增加。
6. approve、deny、重复决策、CAS 冲突和跨进程并发。
7. applying 中断后的三类恢复结果。
8. 覆盖已有文件触发审批、首次创建不审批。
9. Web API 的 `400`、`409` 与状态映射。
10. 完整 approve/deny/resume Web 集成流程。
11. Windows、Ubuntu CI 和全量回归测试。

## 13. 验收标准

- 未被解析的 Checklist 任务不能产生 trusted 结果。
- `finish` 只能基于最终文件的新 Gate 成功。
- 审批创建后本轮执行立即停止。
- 两个并发决策最多一个成功，另一个稳定返回冲突。
- approved 动作在恢复和重试场景中不会覆盖第三方修改。
- denied 动作不执行，Agent 可以根据拒绝原因继续规划。
- Web 首次生成页面不中断，覆盖已有页面会进入审批。
- 所有新增测试、原有测试和 GitHub Ubuntu CI 通过。
