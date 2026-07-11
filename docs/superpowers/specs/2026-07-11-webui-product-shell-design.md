# SpecGate WebUI 产品壳设计规格

日期：2026-07-11

## 1. 背景

SpecGate 当前已经具备较完整的 Coding Agent Harness 后端能力：MockLLM 驱动的确定性运行、上下文选择与压缩、注入安全、Gate 校验、快照保护、治理指标、HITL 审批恢复、Prompt Injection Benchmark，以及多代理隔离。下一阶段目标不是继续扩展命令行能力，而是补齐课程项目和产品展示所需的 WebUI，让 SpecGate 从“后端 harness 原型”推进为“可使用的小型 Codex 产品”。

WebUI 必须服务于 SpecGate 的核心创新：用户不是直接让模型随意改文件，而是在规约、清单、安全门禁、审批和可追踪报告约束下，生成或修改 HTML 页面。

## 2. 产品定位

SpecGate WebUI 是一个受治理的网页生成/修改工作台。

用户注册登录后，可以创建项目：上传 zip 包，或手动填写 `SPEC`、`CHECKLIST`、可选 `index.html`。项目创建后进入 Codex-like 工作区：用户在底部输入任务，例如“根据规格生成页面”或“把现有页面改成仪表盘”；后端创建一次 run，使用 MockLLM 调用 SpecGate harness 执行。运行过程和结果在对话区展示，右侧同步显示 HTML 预览、Gate 结果、治理指标、安全检查和待审批操作。若进入 HITL，用户在 WebUI 里批准或拒绝，再点击恢复运行。

第一版是准产品型 MVP：

- 有真实但轻量的注册、登录、session。
- 有项目空间、项目历史和运行历史。
- 有 API Key 设置页，但默认不调用真实 LLM。
- 有 Codex-like 对话工作台。
- 有 zip 上传和手动创建两种项目输入方式。
- 有 HTML 预览、下载和结果 zip。
- 有完整 HITL approve / deny / resume 操作闭环。
- 能本地运行，也为后续部署到云服务器保留清晰入口。

## 3. 明确不做

第一版不做以下内容：

- 不接真实 LLM 作为默认执行路径。
- 不让 WebUI 直接修改用户电脑原始项目路径。
- 不做 MCP、浏览器控制、电脑控制、Git 集成等 Codex 高级能力。
- 不引入完整 SaaS 权限体系、团队空间、账单系统。
- 不引入 Redis、Celery、PostgreSQL 等重型部署依赖。
- 不开放任意 agent 自由工具调用；所有运行仍围绕当前项目的 HTML 生成/修改任务。

## 4. 用户项目与文件安全边界

WebUI 不直接修改用户原始上传文件。项目输入进入后端后，会分为只读原始快照、可写工作副本和输出工件。

目录结构：

```text
var/specgate_web/
  specgate_web.sqlite3
  users/
    <user_id>/
      projects/
        <project_id>/
          original/
            ... 用户上传或手动创建的原始快照
          workspace/
            SPEC.md / TASK_SPEC.md
            CHECKLIST.md
            index.html
            ... SpecGate 可读取的项目文件
          artifacts/
            latest-index.html
            result.zip
            report.html
            trace.json
          runs/
            <run_id>/
              report.html
              trace.json
              artifacts.json
```

规则：

- `original/` 只读保存用户输入，不被 agent 直接修改。
- `workspace/` 是 SpecGate 运行时可写副本。
- `artifacts/` 是用户最终下载和预览的结果。
- HITL 审批只允许影响 `workspace/` 内的操作。
- 任何路径逃逸、`.env` 写入、用户空间外写入都必须失败关闭。
- 结果以 `latest-index.html` 和 `result.zip` 的形式返回给用户，不提供“回写到用户电脑原路径”功能。

这条边界是 WebUI 的核心安全设计：SpecGate 输出的是受治理的结果工件，而不是直接改用户原项目。

## 5. 技术路线

采用 Python 单体 Web 应用：

- 后端：FastAPI。
- 数据：SQLite。
- 前端：FastAPI 托管的静态 HTML/CSS/JS。
- 运行模式：MockLLM 默认。
- 任务执行：SQLite 记录状态，后端用轻量后台任务执行，前端轮询。
- 部署入口：本地和服务器使用同一套启动方式。

建议入口：

```text
python -m specgate.web
```

后续服务器部署也可以使用：

```text
uvicorn specgate.web_app:create_app --factory
```

## 6. 后端模块划分

新增 Web 相关模块应保持薄封装，复用现有 harness 核心。

- `src/specgate/web_app.py`：创建 FastAPI app，挂载静态前端，注册 API 路由。
- `src/specgate/web_db.py`：SQLite 初始化和数据访问。
- `src/specgate/web_auth.py`：注册、登录、退出、session 校验、密码哈希。
- `src/specgate/web_projects.py`：项目创建、zip 上传解压、手动创建、文件读取、HTML 预览。
- `src/specgate/web_runs.py`：创建 run、后台执行 Mock Agent、轮询状态、读取报告和工件。
- `src/specgate/web_approvals.py`：Web 版 approve / deny / resume。
- `src/specgate/web_settings.py`：用户设置、API Key 状态、治理默认值。
- `src/specgate/web_static/`：前端页面资源。

WebUI 不重新实现 agent、policy、snapshot、gate、metrics、report。它必须调用已有模块：

- `runner.py`
- `approvals.py`
- `metrics.py`
- `report.py`
- `security_eval.py`
- `config.py`
- `snapshot.py`
- `policy.py`

## 7. 登录与账户

登录注册采用真实但轻量的实现：

- 用户名唯一。
- 密码使用哈希保存。
- 登录后设置 cookie session。
- session 存入 SQLite，支持退出登录。
- 未登录访问 API 返回 401。

第一版不要求邮箱验证、找回密码、OAuth、多因素认证。

## 8. API Key 设置

设置页提供 API Key 保存、清除、状态展示，但默认 WebUI 不调用真实 LLM。

安全约束：

- 如果未配置 `SPECGATE_WEB_SECRET`，不允许持久化保存 API Key 明文或可逆密文，只能保存“已配置/未配置”的占位状态。
- 如果后续支持加密保存，密钥必须通过服务器环境变量提供。
- UI 必须明确提示：当前默认运行模式为 MockLLM，API Key 是后续真实 LLM 接入预留。
- 报告、trace、错误消息不得泄露 API Key。

## 9. 项目创建

第一版支持两种创建方式。

### 9.1 上传 zip

用户上传项目 zip，后端执行：

1. 校验文件大小和后缀。
2. 安全解压，禁止 zip slip 路径逃逸。
3. 识别 `SPEC.md` / `TASK_SPEC.md` / `SPEC` 等规格文件。
4. 识别 `CHECKLIST.md` / `CHECKLIST` 等清单文件。
5. 可选识别 `index.html`。
6. 保存原始快照到 `original/`。
7. 复制一份到 `workspace/`。

缺少 spec 或 checklist 时，项目创建失败，并给出明确提示。

### 9.2 手动创建

用户在页面中填写：

- 项目名。
- SPEC 内容。
- CHECKLIST 内容。
- 可选 index.html 内容。

后端生成同样的 `original/` 和 `workspace/` 目录。

## 10. 对话与运行模型

WebUI 采用任务型对话 + 轻量多轮修改。

用户每轮输入必须围绕当前项目：

- 根据 SPEC 和 CHECKLIST 生成 HTML。
- 修改已有 HTML。
- 调整页面结构、文案、样式。
- 修复 Gate 反馈指出的问题。

每轮输入创建一条 run：

```text
queued -> running -> completed
queued -> running -> needs_approval
queued -> running -> failed
needs_approval -> resumed -> running -> completed
needs_approval -> denied -> failed 或 stopped
```

前端轮询 run 状态。完成后展示：

- assistant 摘要消息。
- HTML 预览。
- Gate 结果。
- 治理信任等级。
- 安全评测摘要。
- 报告链接。
- 下载按钮。

如果需要审批，run 停在 `needs_approval`，不会假装成功。

## 11. HITL 审批闭环

WebUI 第一版必须支持完整 HITL 操作。

审批面板显示：

- 待审批操作 ID。
- 动作类型。
- 目标路径。
- 风险原因。
- 参数预览，敏感值脱敏。
- 创建时间。
- 所属 run。

用户操作：

- `Approve`：批准该操作。
- `Deny`：拒绝该操作。
- `Resume`：在审批后恢复运行。

审批必须复用现有 `approvals.py` 和 runner resume 语义。审批不能扩大权限边界，不能允许写出项目 `workspace/`。

## 12. 页面结构

整体视觉参考 Codex：安静、克制、工具型，强调信息密度和可扫描性，不做营销式首页。

### 12.1 登录页

- 居中登录/注册表单。
- 简短产品名：SpecGate。
- 表单切换：登录 / 注册。
- 错误提示：用户名已存在、密码错误、session 失效。

### 12.2 主工作台

三栏布局：

- 左侧：项目列表、最近对话、创建项目按钮、设置入口。
- 中间：当前项目的对话流，用户消息、运行中状态、agent 摘要、审批提醒。
- 底部：任务输入框，发送按钮，运行配置入口。
- 右侧：详情面板，支持切换 HTML 预览、文件、报告、审批、指标。

右侧面板的默认 tab 是 HTML 预览。没有结果时显示项目创建后的初始状态。

### 12.3 项目创建弹窗/页面

- 上传 zip。
- 手动填写 SPEC、CHECKLIST、可选 index.html。
- 创建前校验必填项。
- 创建后自动进入项目工作台。

### 12.4 设置页

设置页参考 Codex 设置页：左侧分类，右侧分组表单。

分类：

- 常规
- 账户
- 模型与 API
- 权限与审批
- 项目
- 关于

常规：

- 工作模式：MockLLM 默认、真实 LLM 预留。
- 默认治理配置：`strict` / `review` / `demo`。
- 默认上下文策略：`baseline` / `compressed` / `injection-safe`。

账户：

- 用户名。
- 注册时间。
- 修改密码。
- 退出登录。

模型与 API：

- Provider：OpenAI-compatible 预留。
- API Key 保存 / 清除 / 状态。
- 当前默认不调用真实 LLM 的提示。

权限与审批：

- 默认是否启用 HITL。
- 审批路径规则展示。
- blocked paths 展示，例如 `.env`、外部路径、路径逃逸。

项目：

- 默认创建方式。
- 上传文件大小限制。
- 结果工件保留策略。

关于：

- 当前版本。
- Mock-first 说明。
- 安全边界说明。

## 13. SQLite 数据模型

建议表：

- `users`：用户账户、密码哈希、创建时间。
- `sessions`：登录 session、过期时间。
- `user_settings`：默认治理配置、上下文策略、API Key 状态。
- `projects`：项目名、创建方式、路径、创建时间、最后运行状态。
- `messages`：项目对话消息，区分 `user` / `assistant` / `system`。
- `runs`：运行状态、输入任务、开始/结束时间、信任等级、报告路径、结果文件路径。
- `approvals`：待审批项、审批状态、审批人、审批时间、resume 关联 run。
- `artifacts`：`latest-index.html`、`result.zip`、`report.html`、`trace.json` 等产物索引。

所有数据查询必须按当前用户过滤。用户 A 不能访问用户 B 的项目、run、artifact 或 approval。

## 14. API 设计

认证：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`

项目：

- `GET /api/projects`
- `POST /api/projects`
- `POST /api/projects/upload`
- `GET /api/projects/{id}`
- `GET /api/projects/{id}/files`
- `GET /api/projects/{id}/preview`

对话与运行：

- `GET /api/projects/{id}/messages`
- `POST /api/projects/{id}/messages`
- `POST /api/projects/{id}/runs`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/report`
- `GET /api/runs/{id}/artifact/index.html`
- `GET /api/runs/{id}/artifact/result.zip`

审批：

- `GET /api/approvals`
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/deny`
- `POST /api/runs/{id}/resume`

设置：

- `GET /api/settings`
- `PUT /api/settings`
- `PUT /api/settings/api-key`
- `DELETE /api/settings/api-key`

所有修改类 API 都需要 session。所有路径参数必须校验资源所有权。

## 15. 错误处理

WebUI 必须把错误转成用户可理解的信息，同时保留工程可调试性。

- zip 缺少 spec/checklist：项目创建失败，页面提示缺少哪个文件。
- zip 解压路径逃逸：项目创建失败，提示压缩包包含不安全路径。
- run 执行失败：对话区显示简短原因，右侧报告面板显示详细 trace。
- Gate 失败：对话区说明未通过，右侧展示 repair hint。
- 审批未完成：run 状态停在 `needs_approval`。
- session 失效：跳回登录页。
- 无权限访问资源：返回 404 或 403，不泄露资源存在性。
- API Key 或 secret 相关错误：不输出敏感值。

## 16. 测试策略

实现阶段必须按 TDD 推进。

后端测试：

- 注册、登录、退出、session 校验。
- 密码哈希不明文保存。
- 项目上传 zip 成功。
- zip slip 被拒绝。
- 缺少 spec/checklist 被拒绝。
- 手动创建项目成功。
- run 创建和状态轮询。
- MockLLM 运行后生成 artifact。
- Web HITL approve / deny / resume。
- 用户隔离：不能访问其他用户项目和工件。
- API Key 不泄露。

前端可做轻量测试或集成验证：

- 登录后进入工作台。
- 创建项目后出现在左侧列表。
- 发送任务后显示运行状态。
- 完成后预览 HTML。
- 需要审批时显示审批面板。
- 设置页能保存默认治理配置。

回归测试：

- 现有 CLI 和 eval 测试必须继续通过。
- Web 层不能改变 runner、approval、metrics 的既有语义。

## 17. 部署要求

第一版部署目标：

- 本地开发可一条命令启动。
- 服务器上可用 uvicorn 启动。
- SQLite 和用户文件默认放在 `var/specgate_web/`。
- 支持通过环境变量修改数据目录。
- 支持通过环境变量设置 session secret 和 API key encryption secret。
- README 要增加 WebUI 本地启动和服务器部署说明。

后续服务器部署时建议：

- 反向代理用 Nginx。
- HTTPS 由服务器或平台提供。
- `var/specgate_web/` 做持久化备份。
- 禁止 debug 模式暴露到公网。

## 18. 验收标准

第一版完成后，应该能演示以下闭环：

1. 新用户注册并登录。
2. 用户上传包含 SPEC 和 CHECKLIST 的 zip。
3. WebUI 创建隔离项目空间。
4. 用户在对话框输入“根据规格生成页面”。
5. 后端创建 run，MockLLM 驱动 SpecGate harness。
6. 页面显示运行中和完成状态。
7. 用户看到生成后的 HTML 预览。
8. 用户下载 `index.html` 或 `result.zip`。
9. 用户打开报告，看到 Gate、治理指标、安全摘要。
10. 对需要审批的案例，用户能在 WebUI approve / deny / resume。
11. 原始上传快照不被修改，所有输出都在 artifact 中。

## 19. 创新点表达

这个 WebUI 不是普通 AI 网页生成器，而是把 SpecGate 的 HE 治理能力产品化：

- 用 spec/checklist 约束模型目标。
- 用 MockLLM 保障课程评测和演示的确定性。
- 用隔离工作副本保护用户原始项目。
- 用 Gate、Snapshot、Policy 防止危险写入和错误交付。
- 用 HITL 把权限决策交还给用户。
- 用报告和指标让每次生成可追踪、可解释、可复现。

最终效果应当是：老师看到的不只是一个“能生成 HTML 的聊天页面”，而是一个有规约、有门禁、有审批、有审计、有隔离边界的小型 Coding Agent Harness 产品。
