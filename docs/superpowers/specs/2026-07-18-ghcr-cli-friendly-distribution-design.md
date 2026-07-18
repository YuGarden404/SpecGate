# SpecGate CLI 易用性与 GHCR 公开镜像分发设计

日期：2026-07-18

## 1. 背景

SpecGate 是 CLI-first Coding Agent Harness。当前 `specgate run` 要求用户每次提供 `--model` 与 `--base-url`，Docker 镜像则默认启动 WebUI；这两点都增加了 CLI 用户的记忆负担，也弱化了核心产品定位。仓库已有 Docker 构建验证，但尚未把镜像发布到公开容器 registry。

本阶段同时改善本机 CLI 首次配置体验，并将 CLI-first 镜像发布到 GHCR。公开镜像分发不等同于公网服务器部署；本阶段不部署交互式 Web 后端。

## 2. 目标

- 提供一次性的 `specgate configure` 交互式配置流程。
- 让日常使用收敛为 `specgate run <工作区>`。
- 保留现有显式参数和 `credentials` 子命令的兼容性。
- 将 Docker 镜像默认入口改为 `specgate` CLI。
- 通过 GitHub 版本标签发布可追溯的公开 GHCR 镜像。
- 用确定性测试、容器 smoke 和公开页面证据证明分发路径有效。

## 3. 非目标

- 不部署公网交互式 Web 后端。
- 不删除 WebUI 或 `specgate-web` 命令。
- 不实现 PowerShell 与 Bash 两套包装脚本。
- 不接受把 API key 直接写在日常命令行参数中的新接口。
- 不增加新的 LLM provider；本阶段继续使用 `openai-compatible`。
- 不引入 VS Code 文件夹选择器、TUI、shell 工具或通用多文件 coding agent。
- 不在本阶段构建 ARM 多架构镜像。

## 4. 用户体验

### 4.1 本机首次配置

用户运行：

```powershell
specgate configure
```

CLI 依次询问 Base URL、Model 和 API key。API key 使用隐藏输入，不回显，也不进入终端历史。已有配置作为默认值展示；已有凭据时，空输入表示保留原凭据。

配置成功后，用户运行：

```powershell
specgate run D:\Projects\my-page
```

工作区继续采用单目录模型，并包含：

- `TASK_SPEC.md`
- `CHECKLIST.md`
- 可选的现有 `index.html`

CLI 在发起模型请求前检查目录和两个必需文件。缺失输入、模型、Base URL 或凭据时，命令失败关闭，并输出一条可执行的修复提示。运行结束后输出通过状态、步骤数以及 `index.html`、report 和 trace 的位置。

### 4.2 临时覆盖

现有高级参数继续有效：

```powershell
specgate run D:\Projects\my-page `
  --model another-model `
  --base-url https://another.example.com/v1
```

工作区只使用现有位置参数，不新增 `--workspace` 或 `-v`：`specgate run <工作区>` 已是最短的清晰形式，而且 Docker 已使用 `-v` 表示目录挂载，重复含义会增加混淆。

## 5. 配置与凭据

### 5.1 非敏感用户配置

新增用户级 JSON 配置，只保存：

- 配置 schema version
- provider，固定为 `openai-compatible`
- Base URL
- Model

默认路径：

- Windows：`%APPDATA%\SpecGate\config.json`
- Linux：`$XDG_CONFIG_HOME/specgate/config.json`
- Linux 未设置 `XDG_CONFIG_HOME`：`~/.config/specgate/config.json`

测试可通过专用配置目录覆盖隔离真实用户目录。写入采用临时文件替换，避免中断时留下半写配置。配置文件不得包含 API key。

### 5.2 凭据

本机 API key 继续复用现有系统 keyring。若 keyring 不可用，`configure` 必须失败关闭并提示改用环境变量，不得回退到明文凭据文件。

凭据解析顺序保持为：

1. `OPENAI_COMPATIBLE_API_KEY`
2. 操作系统 keyring

`credentials set/status/clear` 继续兼容。

### 5.3 运行配置优先级

Model 和 Base URL 的解析优先级为：

1. `--model` / `--base-url`
2. `SPECGATE_LLM_MODEL` / `SPECGATE_LLM_BASE_URL`
3. 用户级 `config.json`

该顺序既允许本机一次配置长期复用，也允许 CI、Docker 和单次实验显式覆盖。

## 6. 组件边界

### 6.1 用户配置模块

新增独立模块负责：

- 计算跨平台配置路径；
- 校验 JSON schema、provider、Base URL 和 Model；
- 原子读取与写入非敏感配置；
- 合并命令行、环境变量和用户配置。

该模块不读取或写入 API key。凭据职责继续由 `credentials.py` 与 credential store 承担。

### 6.2 CLI 编排

`cli.py` 只负责参数解析、交互提示、工作区预检和调用现有 `run_real_llm`。真实运行仍复用现有 `OpenAICompatibleLLM`、`AgentRunner`、WorkspacePolicy、Gate、trace 与 report 链路。

配置解析完成前不得创建 LLM client 或启动 runner。错误输出不得包含 API key，也不得回显任何潜在敏感环境变量值。

### 6.3 Docker 镜像

Dockerfile 默认行为改为：

```dockerfile
ENTRYPOINT ["specgate"]
CMD ["--help"]
```

镜像的默认工作目录为 `/workspace`，用户以读写挂载提供工作区。WebUI 仍可通过 `--entrypoint specgate-web` 显式启动，但不再是默认入口。

容器不依赖桌面 keyring。真实模型运行通过以下环境变量注入：

- `OPENAI_COMPATIBLE_API_KEY`
- `SPECGATE_LLM_BASE_URL`
- `SPECGATE_LLM_MODEL`

文档可展示 Docker `--env-file`，但必须说明该文件由 Docker 读取，不代表 SpecGate 恢复 `.env` 文件支持；该文件应位于仓库外且不得提交。

## 7. GHCR 发布

公开镜像名称固定为：

```text
ghcr.io/yugarden404/specgate
```

### 7.1 触发条件

正常发布由语义版本标签触发，例如 `v0.1.0`。工作流读取 `pyproject.toml` 的项目版本并校验标签，版本不一致时失败，不推送镜像。

保留 `workflow_dispatch` 作为同版本故障恢复入口；手动输入版本必须与项目版本一致。每次 `main` push 继续只做 CI 构建，不自动覆盖公开镜像。

### 7.2 标签

`v0.1.0` 发布生成：

- `0.1.0`
- `0.1`
- `latest`
- `sha-<短提交号>`

不发布无版本约束的 `main` 标签。初期平台固定为 `linux/amd64`。

### 7.3 权限与供应链边界

发布工作流使用 GitHub 内置 `GITHUB_TOKEN`，最小权限为：

```yaml
contents: read
packages: write
```

不创建个人访问令牌，不读取用户 LLM API key，不在 CI 中调用真实 LLM。镜像写入 OCI source、version、revision 和 description 标签，便于从镜像追溯仓库版本。

首次发布后由仓库所有者在 GitHub Packages 页面把容器包设置为 Public。公开性必须通过未登录页面和匿名 `docker pull` 验证，不能只依据已登录页面判断。

## 8. 容器使用流程

帮助信息：

```powershell
docker run --rm ghcr.io/yugarden404/specgate:0.1.0 --help
```

真实工作区：

```powershell
docker run --rm `
  --env-file "$HOME\.specgate.env" `
  -v "D:\Projects\my-page:/workspace" `
  ghcr.io/yugarden404/specgate:0.1.0 `
  run /workspace
```

确定性 Mock Demo：

```powershell
docker run --rm `
  -v "D:\Projects\mock-demo:/workspace" `
  ghcr.io/yugarden404/specgate:0.1.0 `
  run-mock-demo /workspace
```

显式启动 WebUI：

```powershell
docker run --rm -p 8000:8000 `
  --entrypoint specgate-web `
  ghcr.io/yugarden404/specgate:0.1.0 `
  --host 0.0.0.0 --port 8000
```

## 9. 错误处理

- 用户配置不存在：若命令行或环境变量提供完整配置则继续，否则提示运行 `specgate configure`。
- 用户配置损坏或 schema 不支持：失败关闭，报告配置路径和修复命令，不猜测字段。
- keyring 不可用：不写明文 key，提示使用 `OPENAI_COMPATIBLE_API_KEY`。
- 工作区不存在或缺少必需文件：在网络调用前失败，并列出缺失路径。
- GHCR 标签与项目版本不一致：工作流失败且不登录推送步骤。
- GHCR 推送失败：保留 Actions 日志，通过同 commit 的手动入口重试，不修改版本标签指向。
- 匿名拉取失败：不得把 registry 标为完成，先检查 Package visibility 是否为 Public。

## 10. 测试策略

采用 TDD，至少覆盖：

- Windows、XDG 和 home fallback 的配置路径选择；
- 配置 JSON 的读取、校验、原子写入和无 API key 边界；
- 命令行、环境变量、用户配置的优先级；
- `configure` 隐藏输入、保留已有凭据和 keyring 失败关闭；
- `run <工作区>` 的成功解析和缺失配置/工作区输入预检；
- 旧 `--model`、`--base-url` 与 `credentials` 命令兼容；
- Dockerfile 的 CLI `ENTRYPOINT` 与默认 `--help`；
- GHCR 工作流的触发条件、最小权限、版本校验、标签和 smoke；
- 最终证据文档不再声称公开 registry 待完成，同时仍明确公网交互式后端未部署。

本地完整 Python 测试继续使用 Mock/Fake/Stub，不访问真实模型。若本机 Docker 可用，额外执行本地 build、`--help` 和 Mock Demo；最终匿名 pull 必须在远端发布并设为 Public 后执行。

## 11. 证据与完成条件

代码阶段完成不等于公开分发完成。公开 registry 只有在以下条件全部满足后才能标记为已完成：

1. 发布 PR 已合并到 GitHub `main`。
2. 对应 GitHub CI 和 Pages 均通过。
3. `v0.1.0` 指向发布 commit。
4. GHCR publish workflow 成功。
5. Package visibility 显示 Public。
6. 未登录浏览器可访问 Package 页面。
7. 匿名 `docker pull` 成功。
8. 拉取后的镜像通过 `--help` 与 Mock Demo smoke。
9. GitHub `main` 与 NJU GitLab `main` 最终同步到同一发布快照。

需要保存的证据：

- GHCR Actions 成功详情页截图和地址栏 URL；
- GitHub Package 页面显示 Public 与版本标签的截图和 URL；
- 本地匿名 `docker pull`、`--help` 和 Mock Demo 成功截图；
- 镜像 digest；
- 对应 PR、commit、CI、Pages 和 NJU GitLab Pipeline URL。

最终更新 `README.md`、`PLAN.md`、`AGENT_LOG.md`、`docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md` 与事实核对文档。措辞固定区分：公开 GHCR 镜像已发布；公网交互式 Web 后端未部署。

## 12. 后续边界

本阶段完成后，普通本机用户只需一次 `specgate configure`，随后对每个单目录工作区运行 `specgate run <工作区>`。容器用户以环境变量和挂载目录运行同一 CLI。公网服务器部署、ARM 多架构镜像和更多 provider 仍是独立后续任务，不作为本设计完成条件。
