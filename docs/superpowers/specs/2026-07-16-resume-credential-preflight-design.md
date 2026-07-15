# 审批恢复前凭据预检设计

## 问题

真实模型运行进入 `needs_approval` 后，用户可以在批准审批之前清除 API Key。当前恢复流程先把审批从 `approved` 迁移到 `applying`，再应用获批的文件动作，最后进入 LLM 循环时才通过 `CredentialBoundLLM.complete()` 读取冻结指纹对应的凭据。

隔离复现表明：当首次 LLM 调用抛出 `credential_missing` 时，目标文件已经被修改，审批状态也已经变为 `applied`。这违反了“恢复前撤销”的失败关闭语义。

## 采用的语义

采用“恢复前撤销”：

- 如果用户在点击“恢复运行”之前清除了 API Key，恢复必须失败，任何获批动作都不能应用。
- 恢复已经开始之后发生的并发凭据清除不属于本补丁保证范围。
- 失败运行使用冻结的真实模型配置，不得回退到 MockLLM。

## 设计

在 `WebLLMFactory` 增加只验证本地凭据可用性的恢复预检。对于真实模型快照，预检使用冻结的 credential fingerprint 调用现有安全凭据服务，确认匹配的 API Key 仍存在且可解密，然后立即丢弃临时明文；不创建 Provider 请求，也不把 Key 写入 Trace、错误或返回值。Mock 快照的预检为无操作。

`resume_run_once()` 仍先把已排队的恢复任务标记为 `running`，随后 `_run_resume_agent()` 在创建 `AgentRunner` 和调用 `resume_from_approval()` 之前执行凭据预检。这样：

- 预检失败时，现有异常处理会把运行终结为 `failed` 并记录稳定错误码。
- 审批队列尚未被 Runner 认领，因此保持 `approved`，不会进入 `applying` 或 `applied`。
- 获批的 `replace_file` 尚未分派，目标文件保持原样。
- 不会生成或发布 index/ZIP 产物。

预检只用于审批恢复。普通初始运行在第一次 LLM 调用之前没有待应用的人类批准动作，因此保持现有按调用读取凭据的行为。

## 错误处理

凭据缺失、变化、需要重新录入或不可用时，预检沿用 `CredentialBoundLLM` 的稳定错误映射：

- `credential_missing`
- `credential_changed`
- `credential_requires_reentry`
- `credential_unavailable`

错误中不得包含 API Key、credential fingerprint、密文、nonce 或 Provider 正文。失败后的公开运行状态应为 `failed`，`error_message` 为稳定错误码。

## 测试

- 真实快照在凭据存在时通过恢复预检，且不调用网络 transport。
- 冻结快照对应的凭据被清除后，预检抛出 `credential_missing`，且不调用网络 transport。
- 已批准的 `replace_file` 在凭据缺失时不会修改原始 `index.html`。
- 审批队列状态保持 `approved`，revision 不因 Runner 恢复而增加。
- Trace 不包含 `approval_claimed`、`approval_applied` 或凭据材料。
- 运行终结为 `failed`，无 index/ZIP 产物及 artifact 数据库行。
- 凭据仍有效时，现有 HITL 恢复和发布行为继续通过。

## 非目标

- 不实现恢复开始后的实时强撤销或跨线程凭据租约。
- 不回滚已经开始执行的恢复任务。
- 不改变普通初始运行的凭据读取时机。
- 不把凭据预检扩展为 Provider 网络连通性测试。
