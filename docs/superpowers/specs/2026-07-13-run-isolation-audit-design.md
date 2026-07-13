# Run 隔离与不可变审计设计

日期：2026-07-13

## 1. 背景

当前 Web 运行直接修改项目级 `workspace/`，AgentRunner 把 trace 与 evidence 写入
`workspace/runs/latest/`，审批队列也位于同一个目录，完成产物则覆盖项目级
`artifacts/latest-index.html` 与 `artifacts/result.zip`。因此后一次运行会改变前一次
运行的下载、调试和审批语义，不能支持“按 run 审计”的产品声明。

## 2. 目标

- 每个 Web run 拥有独立 workspace、audit、approval queue 和 artifacts。
- 旧 run 的 trace、evidence、审批记录和下载文件不被后续 run 改写。
- 成功 run 的结果成为项目下一次 run 的起点，保留多轮修改语义。
- 同一项目同一时间最多存在一个 `queued`、`running` 或 `needs_approval` run。
- 不改变 CLI 与 eval 的既有外部接口；本阶段只为 AgentRunner 增加显式运行路径能力。

## 3. 目录模型

```text
projects/<project_id>/
  original/
  workspace/
  runs/
    <run_id>/
      workspace/
      audit/
        trace.jsonl
        retrieval.json
        compression.json
        isolation.json
        security.json
      approvals/
        pending_approvals.json
      artifacts/
        index.html
        result.zip
```

`original/` 始终不可变。`workspace/` 表示最近一次成功且可提升的 run 的当前项目版本。
run workspace 在创建 run 时从项目 workspace 完整复制，Agent 只能修改 run workspace。

## 4. RunPaths

新增集中式 `RunPaths` 数据类，由 `web_run_paths(project_paths, run_id)` 构造。它公开：

- `root`
- `workspace`
- `audit`
- `approval_queue`
- `artifacts`
- `index_artifact`
- `zip_artifact`

Web 执行、恢复、审批和 debug 必须接收或构造同一个 `RunPaths`，禁止再次拼接
`runs/latest`。AgentRunner 新增可选 `audit_dir` 与 `approval_queue_file` 参数；未传入时
保留现有默认路径，保证 CLI/eval 兼容。

## 5. 状态与并发

`create_run` 使用 `BEGIN IMMEDIATE` 获取 SQLite 写锁，在同一事务内检查同项目是否存在
活动 run。存在时抛出稳定的 `ActiveRunConflict`，且不插入 run 或 user message。

run 数据库行创建后，立即创建 run 目录并复制项目 workspace。目录初始化失败时回滚
数据库并删除未发布目录。不同项目可以并行创建和执行。

活动状态为：`queued`、`running`、`needs_approval`。终态为：`completed`、`failed`。

## 6. 执行与提升

AgentRunner 在 run workspace 上执行。trace、evidence 和审批队列写入 run 自己的路径。
执行完成后，artifact 从 run workspace 的 `index.html` 复制到 run artifacts，并在同一目录
打包 zip。数据库 artifact 路径只指向 run artifacts。

只有状态为 `completed` 的 run 才提升项目 workspace。提升采用同一父目录下可恢复的两阶段切换。
跨平台文件系统无法原子替换一个已存在的非空目录，因此本设计不宣称整个目录切换严格原子，
而是保证中断后可恢复，且不会为了清理旧备份而破坏已完整发布的新版本：

1. 将 run workspace 复制为 `workspace.next-<run_id>`。
2. 将当前 workspace 改名为备份。
3. 将临时副本改名为 workspace；若此步失败，立即恢复备份。
4. 新 workspace 发布后即视为切换成功；备份清理失败不得回滚到可能已部分删除的备份。
5. 每次提升前检查同 run 遗留的临时副本与备份，并根据 current 是否存在恢复上次中断状态。

`needs_approval` 在恢复完成前不提升。`failed` 永不提升。

## 7. 审批与恢复

Web approvals 表通过 `run_id` 定位 run，然后只读写该 run 的
`approvals/pending_approvals.json`。恢复继续使用原 run workspace、audit 和 queue，不能从
项目当前 workspace 重新开始。

审批 ID 可以保留 Runner 内部格式，但 run queue 的物理隔离保证不同 run 不串审批。

## 8. Debug 与下载

`build_run_debug` 从数据库 artifact 记录和 `RunPaths.audit` 读取证据。artifact 下载端点读取
数据库记录中的 run 专属路径。不存在共享 `latest` 回退；缺失文件应报告该 run 的 artifact
不可用。

## 9. 错误处理

- 活动 run 冲突：返回业务冲突，不产生数据库或消息副作用。
- run 初始化失败：事务回滚并清理未发布目录。
- Agent 失败：保留 audit，标记 failed，不提升 workspace。
- artifact 发布失败：不写 artifact 数据库行，不提升 workspace。
- workspace 发布前提升失败：恢复旧 workspace，run 标记 failed，并保留 run 自身证据。
- workspace 已发布但备份清理失败：保留完整新 workspace，记录清理错误并允许后续恢复流程清理残留。

## 10. 测试与验收

- 两个顺序 run 产生不同目录和不同 artifact 路径。
- 第二个 run 完成后，第一个 run 的 HTML、zip、trace 和 evidence 字节不变。
- 第二个 run 的 workspace 从第一个成功结果开始。
- 同一项目存在活动 run 时创建下一 run 无副作用地失败；不同项目不受影响。
- needs_approval run 的 queue 与其他 run 隔离，恢复继续使用原 run workspace。
- debug 读取指定 run 的 audit，不读取项目级 `runs/latest`。
- 全量测试通过。

## 11. 非目标

- 本阶段不实现通用后台任务队列、重启恢复或 SQLite WAL。
- 本阶段不改变 Gate、HITL 暂停语义、路径链接策略或凭据存储。
- 本阶段不删除项目级 artifacts 目录，以兼容已有项目数据，但新 run 不再写入它。
