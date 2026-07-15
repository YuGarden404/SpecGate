# SpecGate 后端审计加固设计

日期：2026-07-15

## 1. 背景

SpecGate 已完成运行目录隔离、真实路径边界、Gate/HITL 正确性、安全凭据、Web 运行时治理和 Runner 配置接线。全量测试、Python 编译检查与前端语法检查均已通过，课程 A 类项目的核心机制已经具备。

最终后端审计仍发现四类收尾问题：Harness 自有产物存在绕过统一安全文件层的直接 `Path` 写入；OpenAI-compatible Provider 会把 HTTP 错误正文拼入异常；工具与 Gate 对非法 UTF-8 没有结构化失败；`web_runs.py` 遗留了一个无调用者的逐任务线程入口。上述问题不影响 MockLLM 默认演示，但会削弱真实 LLM 接入前的安全边界，因此必须先在独立分支修复。

## 2. 已确认决策

- 本阶段只修复后端审计问题，不接入真实 LLM Web 运行路径。
- 真实 LLM 后续仍采用“默认 MockLLM；用户配置 API Key 后才启用真实模式”的产品方向。
- 复用并小幅扩展 `workspace_fs`，不新建一套重复的存储安全实现。
- Harness 自有输出遇到链接、目录联接、reparse point、路径竞态或非普通文件时 fail closed，不回退到普通 `Path.open()`、`Path.write_text()` 或 `Path.mkdir()`。
- HTTP Provider 错误不保留响应正文；CLI 在异常展示边界继续执行统一脱敏。
- 非法 UTF-8 作为稳定的 `invalid_encoding` 规则族返回，不允许 `UnicodeDecodeError` 使 Runner 崩溃。
- 删除 `start_run_background()`，Web 后台任务只能经 `WebRuntimeCoordinator` 的固定 worker 与有界队列调度。
- 同步中文项目材料和本轮验证证据，但不顺带进行大文件重构。

## 3. 目标

- 让 Trace、Memory、Report 和 Runner evidence 的写入共享现有跨平台安全路径边界。
- 阻止预置 `memory.json`、`runs/`、`reports/` 链接把 Harness 产物写出可信根目录。
- 防止 Provider 控制的 HTTP 错误正文把任意用户密钥带入 CLI、Trace、报告或日志。
- 让非法 UTF-8 输入产生可审计、可修复、不会导致进程崩溃的结构化结果。
- 消除绕过 Web 运行协调器的无界线程入口，并用架构回归测试防止其重新出现。
- 保持现有 MockLLM、Gate、HITL、运行恢复、取消、超时、发布哈希和不可变配置快照语义不变。

## 4. 非目标

- 不实现 Web 真实 LLM 模式选择、模型配置、真实请求重试或真实网络测试。
- 不改变凭据加密格式、AES-256-GCM 存储或用户凭据所有权模型。
- 不引入容器沙箱、分布式队列、多进程 worker 或外部任务系统。
- 不重构 `workspace_fs.py`、`web_runs.py`、`runner.py` 等大文件的整体结构。
- 不修改现有 Action schema、业务 WorkspacePolicy、Gate 检查项或 HITL 审批规则。
- 不为符号链接提供白名单或兼容模式。

## 5. 方案比较

### 5.1 复用并扩展 `workspace_fs`（采用）

在现有安全文件模块中补充安全追加写入能力，并把遗漏的 Harness 产物接回该模块。该方案复用已经覆盖 POSIX `dir_fd`/`O_NOFOLLOW`、Windows reparse point、句柄复验和路径竞态的实现，新增攻击面最小。

### 5.2 新建 `HarnessArtifactStore`（不采用）

独立存储对象可以提供更明显的业务接口，但会重复路径规范化、链接拒绝和跨平台句柄校验。两套安全实现容易产生行为漂移，不适合作为收尾修复。

### 5.3 全面重构存储子系统（不采用）

全面重构可以同时治理超大文件和模块边界，但会显著扩大回归范围，并推迟真实 LLM 接入。大文件拆分只记录为后续熵管理工作。

## 6. 安全文件层设计

### 6.1 `workspace_fs` 最小扩展

新增 `append_workspace_text(root, relative, content, encoding="utf-8", errors="strict")`。函数必须复用 `open_workspace_file(..., access="update", create=True)` 获取已经验证的普通文件句柄，定位到文件末尾后完整写入编码后的字节。任何路径验证或 I/O 失败继续转换成稳定的 `WorkspacePathError`，不得按普通路径重新打开。

现有 `ensure_workspace_directory`、`read_workspace_text`、`read_optional_workspace_text` 和 `write_workspace_text` 继续作为目录、读取和覆盖写入的唯一入口。本阶段不增加通用删除 API；Runner 重置可选 evidence 时安全写入空 JSON 对象，从语义上清除旧 evidence，避免为删除操作引入新的跨平台竞态实现。

### 6.2 Trace

`TraceStore` 仍以 Trace 文件路径构造，保持现有调用方兼容；内部把 `path.parent` 作为可信根、`path.name` 作为相对文件名。父目录必须由调用方通过安全目录接口创建或由受验证的 run 初始化流程提供。

- `reset=True` 使用安全覆盖写入空内容。
- `append()` 先对 payload 脱敏并序列化，再调用安全追加写入。
- 父目录或 Trace 文件是链接、目录联接、reparse point、非普通文件或发生路径竞态时，直接抛出 `WorkspacePathError`。

CLI 默认运行目录由 Runner 通过 `ensure_workspace_directory(root, "runs/latest")` 创建。Web 独立 audit 目录继续由既有 run storage 所有权与初始化流程建立；Trace 写入仍会再次验证其真实路径边界。

### 6.3 Memory

`memory.json` 的存在性判断、读取和覆盖写入全部改用相对于 workspace 根的安全接口：

- 缺失文件返回空 memory。
- JSON 语法错误或 schema 不匹配继续按现有语义返回空 memory。
- 非法 UTF-8、链接对象、非普通文件和路径竞态不伪装成“无历史”，而是 fail closed，让调用方看到安全错误。
- `append_memory()` 返回值仍为 `root / "memory.json"`，不改变公开接口。

### 6.4 Report

报告目录通过 `ensure_workspace_directory(root, "reports/latest")` 创建，最终 HTML 通过 `write_workspace_text(root, "reports/latest/index.html", html)` 写入。报告读取 Trace、Memory 和 evidence 时也使用安全读取接口，避免通过恶意链接把工作区外内容嵌入报告。

报告生成遇到不安全路径时失败，不发布部分成功或写到工作区外的报告。CLI 由现有顶层错误边界返回非零状态，不输出服务器绝对路径或敏感内容。

### 6.5 Runner evidence

`AgentRunner` 在构造阶段明确建立并验证 `run_dir`：

- CLI 默认路径使用 workspace 根加相对路径 `runs/latest` 安全创建。
- 注入的 Web `audit_dir` 必须已经存在，并由安全文件接口验证为真实目录。
- Trace、`retrieval.json`、`compression.json`、`isolation.json` 均以 `run_dir` 为可信根、以单层文件名为相对路径操作。
- `reset_audit=True` 时，三个可选 evidence 文件安全写入 `{}`，保证旧 run 的内容不会残留；随后实际策略产生的新 evidence 会覆盖空对象。

该设计不改变 run isolation：Web run 仍写入自身 audit 目录，CLI 仍使用 `runs/latest`。

## 7. 非法 UTF-8 的结构化失败

### 7.1 ToolDispatcher

`read_file` 捕获 `UnicodeDecodeError`，返回：

- `ok=False`
- `blocked=True`
- `action="read_file"`
- `rule_family="invalid_encoding"`
- `data={"path": relative_path, "rule_family": "invalid_encoding"}`，其中 `relative_path` 是 Action 中已经通过 policy 校验的相对路径

消息只说明文件不是有效 UTF-8，不包含原始字节。该结果按现有工具反馈、permission decision 和 Trace 流程进入审计，Runner 可以继续修复或安全结束。

### 7.2 Gate

`_read_gate_file()` 继续对同一批安全读取字节计算 SHA-256，再严格执行 UTF-8-SIG 解码。`run_html_gate()` 分别捕获 artifact 和 checklist 的 `UnicodeDecodeError`：

- artifact issue code 为 `invalid_artifact_encoding`；
- checklist issue code 为 `invalid_checklist_encoding`；
- issue severity 为 `error`；
- evidence 为 `invalid_encoding`；
- repair hint 要求替换为有效 UTF-8 普通文件；
- `GateResult.passed=False`，不得继续 HTML 或 Checklist 解析。

非法字节、绝对路径和 Python traceback 不进入 Gate summary。Runner 在模型声明完成、审批恢复和最终 Gate 路径上都只能得到结构化失败结果。

### 7.3 Context artifact summary

实施阶段的 Runner RED 测试进一步发现：最终 Gate 之前，Context artifact summary 仍通过直接 `Path.read_text()` 读取 `index.html`。该路径必须改用 `workspace_fs.read_optional_workspace_text()`；非法 UTF-8 只生成“摘要不可用”的上下文说明，让 Runner 继续到最终 Gate 返回结构化 `invalid_artifact_encoding`。路径安全错误继续 fail closed，不在 Context 层吞掉。

## 8. Provider 异常保密设计

`OpenAICompatibleLLM.complete()` 捕获 `HTTPError` 时不再调用 `exc.read()`，也不把响应 headers 或正文拼入异常。若异常持有响应流，应在不读取内容的前提下关闭。对外消息固定为 `HTTP <status> <reason>`；状态原因缺失时只保留状态码。

`URLError` 和超时继续使用当前稳定消息，但不得包含请求 headers、Authorization、API Key、Prompt 或响应正文。CLI 的 `run-real` 与真实 Provider eval 错误边界统一输出 `redact(str(exc))`，作为纵深防御。

回归测试使用不匹配常见 Key 正则的任意秘密哨兵放入 HTTP 错误正文。测试必须证明该哨兵不出现在：

- `LLMProviderError` 文本；
- CLI 标准输出和标准错误；
- Trace 与生成报告。

测试不访问外部网络，继续使用内存响应或注入 opener。

## 9. Web 运行时单入口

删除 `src/specgate/web_runs.py` 中的 `start_run_background()` 和仅为该函数存在的 `threading` 导入。`execute_run_once()` 保持为协调器 worker 调用的同步单次执行函数。

架构回归测试必须同时验证：

- `specgate.web_runs` 不再导出 `start_run_background`；
- `web_runs.py` 不包含 `threading.Thread(`；
- Web app 创建 run、恢复审批和启动恢复仍调用 `WebRuntimeCoordinator`，既有固定 worker、有界队列、取消和超时测试保持通过。

该扫描只约束 Web run 业务入口，不禁止协调器内部创建固定数量的 worker。

## 10. 错误传播与兼容性

- 安全路径错误保持既有 `rule_family`：`invalid_path`、`path_escape`、`linked_path`、`reparse_point`、`unsafe_file_type` 或 `path_race`。
- 内容编码错误使用新规则族 `invalid_encoding`，与文件系统攻击明确区分。
- Tool/Gate 对用户可修复输入返回结构化结果；Harness 自有审计产物的不安全路径属于基础设施边界错误，直接 fail closed。
- MockLLM 仍为 Web 默认执行方式；没有凭据时不会发起真实 Provider 请求。
- 现有公开函数返回类型、run 状态、Gate 哈希绑定、HITL 审批快照和发布 SHA-256 语义保持不变。

## 11. 测试策略

严格执行 Red-Green-Refactor，每个行为先看到测试因当前缺陷而失败。

### 11.1 安全文件输出

- `tests/test_workspace_fs.py`：安全追加正常工作，并拒绝文件链接、链接父目录和不安全根。
- `tests/test_context.py` 或新增 Trace 专项测试：Trace reset/append 不跟随链接。
- `tests/test_memory.py`：`memory.json` 文件链接不改写外部 sentinel，非法根失败关闭。
- `tests/test_report.py`：`reports` 或最终报告文件链接不改写外部 sentinel；报告 evidence 读取不跟随链接。
- `tests/test_runner.py`：`runs`/audit 链接与 evidence 链接被拒绝，普通 CLI/Web audit 目录行为不变。

POSIX 使用真实 symlink 覆盖攻击路径；Windows 无创建链接权限时按既有测试辅助函数跳过，并通过 reparse point mock/已有 Windows 安全文件测试覆盖稳定规则族。

### 11.2 编码与秘密

- `tests/test_tools.py`：非法 UTF-8 返回 `invalid_encoding` ToolResult。
- `tests/test_gate.py`：artifact 和 checklist 非法 UTF-8 分别返回稳定 issue。
- `tests/test_runner.py`：非法编码不会抛出 traceback，最终结果为结构化失败。
- `tests/test_context.py`：artifact summary 使用安全读取边界，非法编码不在 Context 构造阶段崩溃。
- `tests/test_llm.py`：HTTP 错误正文的秘密哨兵不进入异常。
- `tests/test_cli.py`：CLI Provider 错误脱敏且只显示必要状态。

### 11.3 Web 架构与总回归

- `tests/test_web_runtime.py` 或 `tests/test_web_runs.py`：禁止遗留线程入口。
- `tests/test_web_debug.py`：安全重置写入的空 evidence 对外仍规范化为 `null`，不改变既有 Debug API 语义。
- 运行相关 Web 测试，证明固定 worker、有界队列、恢复、取消、超时和审批续跑不回归。
- 运行全量 `unittest`、`compileall`、前端 JavaScript 语法检查和 Git whitespace 检查。

## 12. 文档与证据同步

- `PLAN.md`：增加本轮安全审计收尾阶段及完成状态。
- `AGENT_LOG.md`：记录设计选择、TDD 证据、测试统计和已知非目标。
- `README.md`、`docs/DEPLOYMENT.md`：说明 Harness 自有产物的安全路径边界、非法编码行为和 Provider 错误保密规则。
- `docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md`：同步 PR #16/#17 后的材料状态，并为本轮 PR/CI 留出最终填写位置；只有获得真实链接和编号后才写入最终值。
- Superpowers 设计与实施计划使用中文描述，提交和 PR 由用户执行。

## 13. 验收标准

- 预置 `memory.json`、`runs/`、`reports/` 文件或目录链接不能导致工作区外写入，外部 sentinel 保持不变。
- Trace、Memory、Report 与 Runner evidence 不再使用绕过安全文件层的直接写入。
- HTTP 错误正文中的任意秘密哨兵不出现在异常、CLI、Trace 或报告。
- 非法 UTF-8 的工具读取和 Gate 检查均返回稳定结构化失败，Runner 不崩溃。
- `start_run_background` 与 `web_runs.py` 中的逐任务线程创建彻底移除。
- MockLLM 默认路径、Gate/HITL、运行恢复、取消、超时、配置快照、产物哈希与 Web 发布行为保持通过。
- 全量测试、Python 编译检查、JavaScript 语法检查和 `git diff --check` 全部通过。
- 项目材料只陈述已验证事实，不宣称已完成真实 LLM Web 接入或生产级安全认证。

## 14. 后续工作

安全修复合并后，在独立的 `feat-real-llm-web-integration` 分支设计并实现真实 LLM Web 接入。第一版继续保持 MockLLM 为默认，仅在用户已经安全保存 API Key 且明确选择真实模式时构造 OpenAI-compatible Provider；所有真实输出仍经过 Action Parser、WorkspacePolicy、HITL、固定 worker、有界队列、超时/取消、最终 Gate、发布哈希和审计脱敏。
