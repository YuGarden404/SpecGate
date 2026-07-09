# SpecGate 项目讲解稿

## 1. 一句话介绍

SpecGate 是一个面向静态 HTML 任务的小型 Coding Agent Harness。它让 LLM 只能输出严格 JSON action，由 harness 负责选择上下文、检查权限、调用白名单工具、运行 Gate、记录 trace，并生成静态报告。

## 2. 为什么它属于 A 类 Coding Agent Harness

A 类项目关注的是 agent 工程机制，而不是具体业务页面。SpecGate 的核心贡献在 harness 层：

- 自己实现 agent loop。
- 自己定义 Action JSON 协议。
- 自己实现工具分发和 Tool Registry。
- 自己实现 WorkspacePolicy 和文件快照保护。
- 自己实现 context pack 和 Context Manifest。
- 自己实现 Gate 反馈闭环。
- 自己生成 trace 和静态 Web 报告。

示例 HTML 页面只是演示任务，不是项目主体。项目主体是控制 LLM 如何安全、可测、可追踪地修改代码文件。

## 3. 一次运行的数据流

```text
TASK_SPEC.md + CHECKLIST.md + index.html
        |
        v
Context Selector 选择上下文并生成 Context Manifest
        |
        v
MockLLM 输出严格 JSON action
        |
        v
Action Parser 校验 JSON 协议
        |
        v
Tool Registry + WorkspacePolicy + Snapshot 检查
        |
        v
ToolDispatcher 读写 allowlist 内文件
        |
        v
HTML Gate 检查产物
        |
        v
失败摘要回灌下一轮，或通过后 finish
        |
        v
Trace JSONL + 静态 Web 报告
```

## 4. 主要模块

| 模块 | 文件 | 作用 |
| --- | --- | --- |
| Action 协议 | `src/specgate/actions.py` | 解析和校验 LLM 输出的 JSON action。 |
| 配置读取 | `src/specgate/config.py` | 读取 `specgate.toml`。 |
| 上下文管理 | `src/specgate/context_selector.py`、`src/specgate/context.py` | 选择任务文件，跳过运行产物，构建 context pack。 |
| LLM 抽象 | `src/specgate/llm.py` | 提供 `MockLLM`，后续可扩展真实 provider。 |
| 工具注册 | `src/specgate/tool_registry.py` | 结构化描述可用工具、权限、参数和结果。 |
| 工具执行 | `src/specgate/tools.py` | 执行 read/write/replace/list/finish。 |
| 安全策略 | `src/specgate/policy.py`、`src/specgate/snapshot.py` | 限制路径、动作和外部修改覆盖。 |
| Gate | `src/specgate/gate.py` | 检查静态 HTML 和 checklist。 |
| Runner | `src/specgate/runner.py` | 串联 agent loop。 |
| Trace | `src/specgate/trace.py` | 记录 JSONL 事件并脱敏。 |
| Report | `src/specgate/report.py` | 生成静态 HTML 报告。 |
| CLI | `src/specgate/cli.py` | 提供命令入口和 mock demo。 |

## 5. 三条工程主线

### 上下文管理

SpecGate 不把整个仓库塞给 LLM，而是扫描任务目录，优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`，跳过 `runs/`、`reports/`、`.git/`、缓存和二进制文件，并生成 Context Manifest。

价值：减少噪声，控制上下文规模，让评审能看到“为什么这些文件进入了 LLM 输入”。

### 安全性

SpecGate 使用 `WorkspacePolicy` 阻止路径越界和 allowlist 外写入，使用 `FileSnapshot` 防止运行期间覆盖用户或外部进程刚改过的文件。凭据接口默认 fail-closed，Mock 模式不需要 key。

价值：危险动作不是靠 prompt 约束，而是在代码层被拦截。

### 工具管理

SpecGate 使用 Tool Registry 描述 `read_file`、`write_file`、`replace_file`、`list_files`、`finish`。工具信息会进入 context pack，也会显示在静态报告里。

价值：LLM、runner 和评审者都能看到当前 harness 到底开放了哪些工具。

## 6. 为什么 Mock LLM 足够支撑 MVP

Mock LLM 不是为了证明模型能力，而是为了证明 harness 机制：

- JSON action 是否严格；
- 工具调用是否受控；
- Gate 失败是否能驱动下一轮修复；
- trace 和 report 是否完整；
- 安全边界是否可测试；
- CI 是否能稳定复现。

真实 LLM 后续可以作为可选 provider，但默认路径保持 `mock`，这样课程评审不需要网络、API key 或模型额度。

## 7. 演示脚本

1. 打开 `README.md`，说明项目定位和评审快速入口。
2. 打开 `examples/knowledge_nav/TASK_SPEC.md`，说明这是运行时任务输入。
3. 打开 `examples/knowledge_nav/CHECKLIST.md`，说明 Gate 会检查 checklist。
4. 运行：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

5. 打开 `examples/knowledge_nav/index.html`，展示最终 HTML 页面。
6. 打开 `examples/knowledge_nav/reports/latest/index.html`，展示 trace、actions、Gate、tools 和 final artifact。
7. 运行：

```powershell
python -m unittest discover -s tests -v
```

8. 打开 `docs/AI4SE_Lab_9_12_Alignment.md`，说明 Lab 10 Skill 已接入，Lab 9/11/12 的取舍合理。

## 8. 公开展示地址

- WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`

## 9. 后续方向

当前最终提交不需要继续扩张核心功能。合理后续方向是：

- Lab 11 `hooks/pre-commit.sample`：做密钥和必要文件检查。
- 真实 LLM provider 设计：只做可选 provider，不替代 Mock 默认路径。
- AgentPack 草案：把权限和 max steps 写成可部署元数据。

这些方向都应保持“不开放 shell、不做浏览器自动化、不扩大 MVP 主路径”的边界。
