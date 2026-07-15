# SpecGate Web 运行时加固设计

日期：2026-07-14

## 1. 背景

当前 Web 运行路径已经具备 ZIP 解压限制、每项目单活动 run、独立运行目录、`initializing` 清理恢复和 `publishing` 幂等恢复，但后台执行仍由 `start_run_background()` 为每个 run 直接创建线程。该结构没有全局 worker 上限和有界待执行队列，也缺少每用户活动 run 上限、完整的启动恢复、运行超时、取消接口以及 SQLite 并发治理。

本阶段只加固单进程 Web MockLLM 运行时。目标是把外层运行循环变为可限流、可恢复、可取消、可审计的基础设施，并保留既有 Gate、HITL、运行目录、发布和产物语义。

## 2. 已确认决策

- 使用独立的 `WebRuntimeCoordinator`，不继续采用“每个 run 创建一个线程”的结构。
- 默认使用 4 个固定 worker 和容量为 32 的待执行队列。
- 每用户最多 4 个活动 run，每项目继续最多 1 个活动 run。
- 容量超限返回 HTTP 429，且不得创建 run 数据库记录、运行目录或其他半成品。
- 采用协作式取消，不强杀 Python 线程。
- 默认运行超时为 60 秒，不包含排队和人工审批等待时间。
- 提供取消 API 和 Web 最小取消按钮。
- SQLite 使用 WAL、5 秒忙等待和 `synchronous=NORMAL`。
- 数据库升级到 schema v3，保存 `cancel_requested_at` 和 `deadline_at`。
- 容量和超时具有安全默认值，允许环境变量覆盖和 `create_app` 测试注入，非法配置启动即失败。
- 启动时重新调度 `queued`，遗留 `running` 标记为进程重启中断失败，`needs_approval` 原样保留。
- 本阶段仍只使用 MockLLM，不接入真实 LLM。

## 3. 目标

- 确保 Web 进程内同时运行和等待执行的任务数量严格有界。
- 防止单个用户占满全局运行容量。
- 在并发请求下原子执行全局、用户和项目级准入。
- 允许用户安全取消排队中、运行中和等待审批的 run。
- 在运行超过 deadline 后阻止继续执行和发布。
- 为应用重启提供明确、不会重复副作用的恢复规则。
- 改善 SQLite 多连接并发读写的稳定性。
- 保持现有运行隔离、路径安全、Gate、HITL、发布恢复和产物不可变语义。

## 4. 非目标

- 不接入真实 LLM 或外部模型网络请求。
- 不实现多进程、跨主机或分布式任务调度。
- 不实现租约、心跳、消息代理或持久化分布式 worker。
- 不强杀 Python 线程，也不新增子进程沙箱。
- 不在本阶段接通预算、检索、压缩和隔离等 Runner 配置；这些工作属于 `feat-runtime-config-wiring`。
- 不在本阶段完成最终课程材料和证据汇总；这些工作属于 `docs-final-evidence-sync`。
- 不重复实现已经存在的 ZIP 安全限制、运行目录隔离和 `publishing` 幂等恢复。

## 5. 运行模型与部署边界

运行协调器是单 Web 进程内的执行设施。一个应用实例只创建一个协调器，并由该协调器拥有固定 worker、待执行队列、停止信号和关闭过程。

SQLite WAL 解决同一数据库的多连接并发和短事务竞争，但不把内存队列升级为跨进程队列。因此部署文档必须明确：启用 Web 后台 run 执行时只运行一个 Web 应用进程。若未来需要多个 Web 进程，应另行设计数据库租约或外部任务队列。

## 6. 模块边界

### 6.1 `src/specgate/web_runtime.py`

新增运行时模块，负责：

- 解析和校验 `WebRuntimeConfig`；
- 创建固定数量的 worker；
- 管理容量明确的待执行队列；
- 预留、提交和释放全局执行容量；
- 为运行中的 run 保存取消事件和 deadline；
- 调度首次执行与审批恢复执行；
- 在 worker 完成后补入启动恢复时尚未进入内存队列的旧 `queued` run；
- 处理启动恢复和安全关闭。

该模块不处理 HTTP、项目权限、页面渲染、工作区复制或发布算法。

### 6.2 `src/specgate/web_runs.py`

继续负责 run 的数据库操作、运行目录初始化、Runner 调用和发布，但做以下调整：

- 移除直接创建后台线程的职责；
- 提供可由协调器调用的单次执行入口；
- 首次执行和审批恢复都通过相同的停止检查协议；
- 在 Runner 步骤边界、工具调用返回后和发布前检查取消或超时；
- 为准入、认领、取消和终态转换提供短事务函数；
- 明确区分取消、超时、普通失败和进程重启中断。

### 6.3 `src/specgate/web_app.py`

负责：

- 在应用启动时构造配置和唯一协调器；
- 完成恢复后启动 worker；
- 将新 run 和审批恢复提交给协调器；
- 注册取消 API；
- 在应用关闭时调用协调器的统一关闭流程。

### 6.4 `src/specgate/runner.py`

Runner 接收一个轻量停止检查接口。该接口不依赖 FastAPI、SQLite 或 Web 类型；非 Web 调用方不传入时保持现有行为。

停止检查只放在稳定边界：步骤开始前、步骤完成后、工具调用返回后、Gate 前和完成返回前。检查到取消或超时时抛出专用控制异常，由 Web 运行层转换为对应终态。

## 7. 配置

配置优先级固定为：

```text
create_app 显式注入 > 环境变量 > 默认值
```

| 环境变量 | 默认值 | 合法范围 |
| --- | ---: | ---: |
| `SPECGATE_WEB_WORKERS` | 4 | 1–16 |
| `SPECGATE_WEB_QUEUE_CAPACITY` | 32 | 1–256 |
| `SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER` | 4 | 1–32 |
| `SPECGATE_WEB_RUN_TIMEOUT_SECONDS` | 60 | 1–3600 |

每用户上限还必须小于或等于 worker 数与队列容量之和。环境变量只接受十进制整数，不接受空值、浮点数、布尔文本或自动截断。非法配置在应用启动阶段抛出可读异常，不回退到默认值。

测试通过注入配置对象、时钟和同步原语验证边界，不依赖极短真实 sleep。

## 8. 有界执行器

协调器使用固定 worker 与显式有界队列，不使用具有无界内部队列的默认 `ThreadPoolExecutor`。

- `worker_count` 表示最多同时执行的 run 数。
- `queue_capacity` 表示最多驻留在内存待执行队列中的 run 数。
- 默认情况下最多有 4 个执行中的 run 和 32 个内存排队 run。
- worker 从队列取出任务后，待执行槽位立即可供下一个合格任务使用。
- 每个 run 在任何时刻最多存在一个队列项或一个执行控制对象。

协调器使用可按 `run_id` 移除任务的受锁有界队列，而不是无法删除任意元素的黑盒队列。全局容量令牌覆盖一个执行段从准入预留、进入队列、被 worker 认领到离开 worker 的完整生命周期；进入 `needs_approval` 或任一终态时释放。排队取消会原子移除队列项并立即释放令牌。需要审批恢复时必须重新取得令牌。

启动恢复可能遇到旧版本遗留的 `queued` 数量超过当前内存队列容量。协调器先按 `created_at, id` 顺序装入可容纳的任务，其余仍保持数据库 `queued` 状态；每次 worker 释放槽位后继续按相同顺序补入。在恢复积压清空前，新任务准入必须把数据库中的恢复积压计入全局容量，不能越过旧任务制造饥饿。

## 9. 任务准入

活动状态定义为：

```text
initializing, queued, running, needs_approval, cancel_requested, publishing
```

终态定义为：

```text
completed, failed, cancelled, timed_out
```

新任务按以下顺序准入：

1. 校验登录身份、项目所有权、请求字段和 prompt。
2. 向协调器预留一个全局执行容量令牌。
3. 保持全局预留令牌，在短 `BEGIN IMMEDIATE` 事务中检查：
   - 当前用户的活动 run 少于配置上限；
   - 当前项目不存在活动 run。
4. 只有全部检查通过后才插入 `initializing` run 和关联消息。
5. 创建并验证独立运行目录，完成快照后把状态转换为 `queued`。
6. 使用预留令牌提交任务；该步骤不得再因队列已满失败。

全局限制由协调器锁保护的预留操作保证，用户与项目限制由数据库写事务保证；数据库限制失败时回滚并释放全局令牌，组合协议对外表现为一次原子准入。任何限制失败时返回 HTTP 429。限制失败发生在插入 run 和创建目录之前，因此不会留下数据库记录、消息、运行目录、trace、evidence 或 artifact。

初始化过程出现异常时沿用现有安全清理与诊断规则；预留令牌必须在异常路径释放。

## 10. 状态机

主要状态转换为：

```text
initializing -> queued
queued -> running
queued -> cancelled
running -> needs_approval
running -> publishing
running -> failed
running -> cancel_requested -> cancelled
running -> timed_out
needs_approval -> queued
needs_approval -> cancelled
publishing -> completed
publishing -> failed 或保持 publishing 等待既有恢复逻辑
```

状态转换必须带旧状态条件，例如 `queued -> running` 只能更新仍为 `queued` 的行。worker 认领失败时不得执行 Runner。

`publishing` 是不可取消状态。进入发布前必须最后检查停止信号和 deadline；进入 `publishing` 后继续使用现有幂等发布与恢复规则，避免出现工作区已经切换但数据库显示已取消的矛盾。

审批决定与恢复运行继续保持为两个独立动作：approve / deny 只记录人工决定，不自动恢复 Runner。用户调用现有 `/api/runs/{run_id}/resume` 时，接口先预留新的全局容量令牌，再用条件更新把 run 从 `needs_approval` 转换为 `queued`，随后向协调器提交恢复任务。容量不足时返回 HTTP 429，审批决定保持不变，run 仍为 `needs_approval`，用户可以重试。人工等待时间不计入运行超时。

协调器和启动恢复通过该 run 的独立审批队列判断 `queued` 是首次执行还是审批恢复：存在 `next_resume_candidate()` 时执行恢复入口，否则执行首次入口。这样不新增第二个任务类型数据库字段，进程在 `/resume` 排队后重启也不会把恢复任务误当作首次执行。

## 11. 取消语义

新增：

```text
POST /api/runs/{run_id}/cancel
```

接口只允许 run 所有者调用，并沿用现有资源防枚举规则。

- `queued`：以条件更新转换为 `cancelled`，协调器原子移除内存队列项并释放容量；若它属于尚未装入内存的启动恢复积压，则只需更新数据库状态。
- `running`：记录 `cancel_requested_at`，转换为 `cancel_requested`，并设置内存取消事件。
- `needs_approval`：没有活跃执行线程，直接转换为 `cancelled`。
- `cancel_requested`：返回当前状态，不重复创建取消动作。
- `publishing` 和所有终态：返回 HTTP 409。

成功响应返回 run 的最新公开状态，不返回内部线程、事件、deadline 计算细节或其他用户信息。

进入 `cancelled` 或 `timed_out` 时必须写入 `finished_at`、稳定错误摘要并更新项目的 `last_run_status`；`cancel_requested` 仍是非终态，不写入 `finished_at`。

协作式取消不承诺中断正在执行的单个 Python 调用。若一个步骤阻塞，状态保持 `cancel_requested`，直到该步骤返回并到达停止检查边界。MockLLM 和本项目内置工具必须保持有界，且取消确认后不得进入后续步骤或发布。

## 12. 超时语义

worker 成功把 `queued` 认领为 `running` 时，以 UTC 时间写入：

```text
deadline_at = 当前时间 + run_timeout_seconds
```

排队时间不计入超时。run 进入 `needs_approval` 后不继续消耗运行时间；审批恢复被再次认领为 `running` 时写入新的执行段 deadline。

停止检查同时读取单调时钟 deadline 和取消事件：

- 用户取消优先落为 `cancelled`；
- deadline 到达且没有更早的用户取消时落为 `timed_out`；
- 两者都未触发时继续执行。

数据库中的 `deadline_at` 用于审计和恢复判断，进程内超时比较使用单调时钟，避免系统时间回拨影响执行。超时只在步骤边界协作式生效；一旦确认超时，必须阻止发布并写入稳定的中文错误摘要。

## 13. 启动恢复

应用启动时，在接收新 run 前执行恢复：

| 原状态 | 恢复动作 |
| --- | --- |
| `initializing` | 沿用现有安全清理；只删除可证明由该 run 拥有的存储，无法安全清理时标记失败并保留诊断 |
| `queued` | 按 `created_at, id` 重新提交到协调器；超出内存容量的保持数据库 `queued`，worker 释放容量后继续按顺序调度 |
| `running` | 标记为 `failed`，错误明确为“进程重启中断”，不得自动重跑 |
| `cancel_requested` | 转换为 `cancelled`，保留 `cancel_requested_at` |
| `needs_approval` | 原样保留，等待用户决定 |
| `publishing` | 沿用现有幂等发布恢复 |
| 终态 | 保持不变 |

恢复函数必须使用条件更新，防止恢复扫描和并发状态变化互相覆盖。`running` 不自动重跑是为了避免重复工具副作用；`queued` 尚未开始执行，可以安全重提。

## 14. 安全关闭

关闭顺序固定为：

1. 协调器停止接受新任务。
2. 尚未运行的内存排队任务转换为 `cancelled`。
3. 运行中的任务转换为或保持 `cancel_requested`，并设置取消事件。
4. 发送 worker 停止哨兵。
5. 使用单个 5 秒绝对 deadline 等待全部 worker。

等待时间是所有 worker 共享的总预算，不为每个线程分别等待 5 秒。超过 deadline 后应用关闭流程返回；遗留 `cancel_requested` 会在下次启动时恢复为 `cancelled`。

## 15. SQLite 并发治理与 schema v3

`connect_db()` 创建的每个连接统一设置：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
```

数据库版本升级到 3。`runs` 表新增可空字段：

```sql
cancel_requested_at TEXT;
deadline_at TEXT;
```

v2 到 v3 的迁移在短 `BEGIN IMMEDIATE` 事务内执行，必须保留已有用户、项目、run、审批和产物。迁移可安全地由 `init_db()` 重复调用，但同一数据库版本不得重复添加列。

准入、任务认领、取消和终态写入使用短事务，不在事务中执行以下操作：

- 文件系统复制、删除、压缩或重命名；
- Runner、MockLLM 或工具调用；
- 发布或恢复发布；
- 等待线程、事件或 sleep。

数据库锁竞争由 5 秒 busy timeout 有界处理，不增加无界应用层重试。

## 16. API 与 Web UI

容量限制统一返回 HTTP 429。响应使用稳定错误 code，并提供可读中文说明，区分：

- 全局执行容量已满；
- 当前用户活动 run 已达上限；
- 当前项目已有活动 run。

取消接口的状态冲突返回 HTTP 409；未登录、资源不存在和越权访问沿用现有认证与防枚举行为。

Web 页面只做最小交互增强：

- 对 `queued`、`running` 和 `needs_approval` 显示“取消运行”按钮；对 `cancel_requested` 只显示“正在取消”状态，不再显示可点击按钮；
- 点击“取消运行”后立即禁用按钮，避免重复请求；
- 接口完成后刷新 run 状态；
- 补齐“排队中”“正在运行”“等待审批”“正在取消”“已取消”“已超时”“发布中”等中文状态映射；
- 不重构现有页面布局和轮询机制。

## 17. 错误处理与不变量

必须保持以下不变量：

- 一个 run 不能同时出现在待执行队列和运行控制表中。
- 一个 run 不得被两个 worker 同时认领。
- 任意异常路径都必须释放协调器容量令牌。
- 取消或超时确认后不得进入 `publishing`。
- `publishing` 后不得被取消覆盖。
- HTTP 429 不得留下 run、消息或存储。
- 单个 run 的异常不得导致 worker 永久退出。
- 错误响应和日志不得包含凭据、工作区敏感内容或内部事件对象。

取消和超时使用专用控制异常，与普通失败分开处理。普通异常继续通过现有安全摘要落库；发布期间的异常继续遵守现有 `publishing` 恢复不变量。

## 18. 测试策略

实现严格遵循 TDD，每项行为先写失败测试，再写最小实现。

### 18.1 配置测试

- 默认值正确。
- `create_app` 注入优先于环境变量。
- 环境变量优先于默认值。
- 边界值接受，越界值、空值和非整数拒绝。
- 每用户上限不得超过总执行容量。

### 18.2 协调器测试

- 同时执行数不超过 worker 数。
- 内存待执行数不超过队列容量。
- worker 完成后释放槽位并补入恢复积压。
- 同一 run 不重复排队或执行。
- 单个任务异常不会杀死 worker。
- 关闭使用统一 5 秒 deadline。

### 18.3 准入与并发测试

- 全局容量、每用户上限和每项目上限分别返回 429。
- 429 时数据库、消息表和运行目录均无新增。
- 两个并发请求不能绕过每用户或每项目限制。
- 初始化失败释放全部容量并执行既有安全清理。

### 18.4 取消与超时测试

- 排队任务立即取消且不会执行。
- 运行任务先进入 `cancel_requested`，在边界确认后进入 `cancelled`。
- 等待审批任务可直接取消。
- `publishing` 和终态拒绝取消。
- 重复取消 `cancel_requested` 不产生第二个动作。
- deadline 从实际认领开始，排队和人工审批时间不计入。
- 超时、取消和异常都不能绕过发布前检查。
- 使用假时钟、事件和 barrier 测试，不使用易波动的长 sleep。

### 18.5 恢复与数据库测试

- schema v2 正确迁移到 v3 并保留全部数据。
- 每个连接启用 WAL、NORMAL、foreign keys 和 5000 ms busy timeout。
- `initializing`、`queued`、`running`、`cancel_requested`、`needs_approval`、`publishing` 和终态逐一验证恢复规则。
- 超过内存队列容量的旧 `queued` 最终按稳定顺序执行。

### 18.6 API 与静态页面测试

- 取消接口验证登录、所有权、成功状态和 409 冲突。
- 429 响应具有稳定 code 和中文说明。
- 页面包含取消按钮、禁用逻辑和新增中文状态映射。
- 现有轮询、审批、产物下载和项目隔离测试继续通过。

### 18.7 回归验证

完成后运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall -q src tests
git diff --check
```

既有 ZIP 解压安全、运行目录隔离、路径安全、Gate、HITL、安全凭据和发布恢复测试必须全部继续通过。

## 19. 文档与交付

本分支同步与功能直接相关的：

- `README.md`：说明 Web 运行限制、取消和超时行为；
- `docs/DEPLOYMENT.md`：说明环境变量、单 Web 进程约束和 SQLite WAL；
- `PLAN.md`：记录本阶段范围和完成状态；
- `AGENT_LOG.md`：记录设计决策、TDD 证据和验证结果。

最终课程证据、截图、演示口径和材料一致性检查留给 `docs-final-evidence-sync`。

## 20. 验收标准

本阶段完成必须同时满足：

1. Web run 不再按任务直接创建无界线程。
2. worker、待执行队列、每用户和每项目容量限制均有确定性测试。
3. 任何 429 路径都不会创建 run 或运行目录。
4. 用户可通过 API 和页面取消允许取消的 run。
5. 取消或超时后不会进入发布。
6. 启动恢复覆盖所有非终态，且 `running` 不会自动重跑。
7. SQLite schema v3 迁移和 WAL 配置通过测试。
8. 关闭流程主动发送停止信号并使用统一 5 秒 deadline。
9. 全量单元测试、编译检查和 diff 检查通过。
10. 运行模式仍为 MockLLM，未引入真实 LLM 或分布式调度。
