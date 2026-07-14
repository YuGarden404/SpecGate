# SpecGate 后续加固路线设计

日期：2026-07-14

## 1. 背景

SpecGate 已完成三项基础正确性与安全加固：

1. `feat-run-isolation-audit`：每个 run 使用独立 workspace、审批队列、trace、evidence 和 artifact。
2. `feat-workspace-path-hardening`：安全文件接口覆盖符号链接、目录联接、真实路径逃逸、ZIP 链接条目和运行目录切换。
3. `feat-gate-hitl-correctness`：结构化 Checklist、最终 Gate、HITL 真正暂停、审批 revision/CAS 和发布摘要绑定。

上述工作已经合并到 `main`，后续计划不能重复实现这些能力。剩余问题横跨凭据、Web 运行可靠性、配置接线和课程材料，必须拆成独立分支与 PR，不能重新形成一个巨型变更。

## 2. 目标

- 明确剩余阶段的边界、先后关系和验收门槛。
- 让每个阶段都能独立测试、独立审查和独立回滚。
- 先稳定安全与运行基础设施，再接通可调参数，最后同步课程材料。
- 保持 MockLLM 为唯一运行模式，不把真实 LLM、网络成本和非确定性引入核心验收。

## 3. 总体原则

- 每个阶段单独编写设计、实施计划、分支和 PR。
- 所有行为变更使用 TDD，先得到失败测试，再写最小实现。
- 每个阶段合并前运行聚焦测试、全量测试、语法检查和差异检查。
- 每个阶段的 Ubuntu CI 通过后，下一阶段才能开始。
- 文档与实现同步更新，但最终课程材料集中到最后一个阶段统一校对。
- Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作，由用户完成 Git 流程。

## 4. 阶段一：feat-secure-credentials

### 4.1 范围

- CLI 保留进程环境变量作为只读、最高优先级的临时凭据来源。
- CLI 的 `set/status/clear` 使用操作系统 keyring，不再读写 `.env`。
- Web 使用独立主密钥和 AES-256-GCM 加密 `openai-compatible` API key，再把密文存入 SQLite。
- 旧 Web HMAC 占位记录迁移为 `requires_reentry`。
- CLI、HTTP 响应、日志、Trace 和异常不得泄漏明文、密文或 nonce。
- 增加 `keyring` 与 `cryptography` 依赖。

### 4.2 非目标

- 不启用真实 LLM。
- 不让 Web Runner 读取或使用 API key。
- 不实现在线主密钥轮换。
- 不实现多个 Web provider 的界面。

### 4.3 完成门槛

- CLI 日常凭据生命周期不创建或修改 `.env`。
- Web 数据库中没有 API key 明文。
- AES-GCM round trip、篡改、跨用户交换、缺失主密钥和旧数据迁移均有确定性测试。
- MockLLM、项目、审批和审计在主密钥缺失时仍可使用。
- 全量测试与 Ubuntu CI 通过。

## 5. 阶段二：feat-web-runtime-hardening

### 5.1 范围

本阶段先审计 `feat-run-isolation-audit` 与 `feat-workspace-path-hardening` 已有实现，只补真实缺口：

- ZIP 文件数量、单文件展开大小、总展开大小和压缩比限制。
- 有界执行器、全局并发上限、单用户或单项目活动 run 上限。
- `queued`、`running`、`needs_approval` 和 `publishing` 的启动恢复规则。
- 运行超时、取消、异常和进程重启后的稳定数据库状态。
- SQLite WAL、busy timeout、短事务和锁竞争测试。
- 后台线程或执行器的有界关闭流程。

### 5.2 非目标

- 不修改 workspace 路径安全原语。
- 不修改凭据加密格式。
- 不接入真实 LLM 或外部分布式任务队列。
- 不引入 Redis、Celery 或独立数据库服务。

### 5.3 完成门槛

- 恶意或异常 ZIP 不能无界消耗磁盘、内存或文件数量。
- 同时提交大量 run 不会创建无界线程。
- 重启恢复不会重复 promotion、重复应用审批动作或把不确定状态标为 completed。
- SQLite 并发测试没有静默覆盖或长期锁死。
- 全量测试与 Ubuntu CI 通过。

## 6. 阶段三：feat-runtime-config-wiring

### 6.1 范围

- 创建 run 时保存不可变配置快照。
- 将 `max_steps`、上下文字符预算、检索参数、压缩阈值和隔离策略传给真实执行路径。
- resume 使用原 run 的配置快照，不读取用户后来修改的 Settings。
- Trace、Debug API 和 Audit 页面显示实际生效的配置值。
- 为默认值、边界值、非法值和恢复一致性增加测试。

### 6.2 非目标

- 不新增检索、压缩或隔离算法。
- 不重新设计 Settings 页面。
- 不允许配置绕过 WorkspacePolicy、Gate 或 HITL。
- 不启用真实 LLM。

### 6.3 完成门槛

- 修改配置能够确定性改变 Runner 的预算或策略证据。
- run 创建后的 Settings 修改不影响该 run 的 resume。
- 非法配置在进入 Runner 前失败关闭。
- Audit 展示值与 Trace、数据库快照和 Runner 实参一致。
- 全量测试与 Ubuntu CI 通过。

## 7. 阶段四：docs-final-evidence-sync

### 7.1 范围

- 同步 `SPEC.md`、`PLAN.md`、`AGENT_LOG.md`、`README.md` 和课程说明材料。
- 回填各阶段 branch、commit、PR、CI、测试数量和关键截图。
- 删除或修正已过期的 `.env`、HMAC 占位、运行并发和配置接线描述。
- 建立课程要求到实现文件、测试和演示证据的对应表。
- 扫描未勾选但已完成的计划项，以及声称完成但没有证据的条目。

### 7.2 非目标

- 不修改生产代码行为。
- 不在材料阶段补做安全或运行功能。
- 不伪造无法在仓库或 CI 中验证的结果。

### 7.3 完成门槛

- 文档描述与 `main` 的实际代码一致。
- 每个重要能力至少对应一个实现位置和一个测试证据。
- 所有 commit、PR 和 CI 证据可追溯。
- 最终全量测试、CI 和演示步骤可以由课程评审者复现。

## 8. 依赖顺序

```text
feat-secure-credentials
  -> feat-web-runtime-hardening
  -> feat-runtime-config-wiring
  -> docs-final-evidence-sync
```

安全凭据先完成，避免后续 Web runtime 和配置变更继续依赖 HMAC 占位或 `.env`。Web runtime 在配置接线前完成，确保配置快照和 resume 建立在稳定生命周期上。材料同步最后执行，避免每个功能 PR 重复修改最终交付说明。

## 9. 分支与验证约定

每个阶段使用同名分支，提交信息和 PR 标题使用中文 Conventional Commits，例如：

```text
feat: 实现安全凭据存储
feat: 加固 Web 运行时并发与恢复
feat: 接通 Runner 运行配置
docs: 同步最终交付材料与验证证据
```

每个阶段至少执行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

涉及依赖、Docker 或服务器行为的阶段还必须依赖 GitHub Ubuntu CI 验证跨平台结果。

## 10. 路线验收标准

- 四个阶段没有跨范围实现或重复改造。
- 每个阶段都有独立设计、实施计划、TDD 证据和 CI 结果。
- MockLLM 始终是课程自动验收路径。
- 最终文档可以准确解释凭据、Web runtime、运行配置和既有 Gate/HITL 安全边界。

