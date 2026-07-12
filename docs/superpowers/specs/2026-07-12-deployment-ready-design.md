# SpecGate 服务器部署准备设计

日期：2026-07-12

## 1. 背景

SpecGate 已经完成 CLI harness、治理指标、HITL 审批、Prompt Injection Benchmark、多代理隔离和 WebUI 产品壳。WebUI PR 合并后，项目已经可以在本地通过 `python -m specgate.web --host 127.0.0.1 --port 8000` 启动，并支持注册登录、项目创建、MockLLM 运行、产物下载、审批和审计查看。

课程后续要求需要一个真实可访问的 URL。老师检查作业时只需要短期开放几天，因此本阶段目标不是构建复杂生产平台，而是把当前 WebUI 打包成可以在单台云服务器上稳定运行的交付形态。

## 2. 目标

- 更新 Docker 镜像，使默认启动目标从 CLI demo 切换为 WebUI 服务。
- WebUI 在容器内监听 `0.0.0.0:8000`，便于通过服务器公网 IP 或反向代理访问。
- 提供持久化数据目录约定，避免容器重启后用户、项目、运行记录和产物丢失。
- 明确部署所需环境变量：数据目录、密钥、Cookie 安全选项。
- 提供面向课程检查的部署文档：本地验证、服务器启动、公网访问、安全组、可选 Nginx/域名反代。
- 在 CI 中保留 Docker 构建检查，并新增轻量级 WebUI 启动 smoke test，证明镜像至少能导入依赖并启动服务入口。
- 保持 mock-first：部署完成后仍默认使用 MockLLM，不因为用户设置 API key 就自动调用真实模型。

## 3. 非目标

- 不接入真实 LLM。
- 不购买服务器、域名或配置真实云厂商资源。
- 不强制引入 docker compose。
- 不内置 Nginx、HTTPS 证书或自动续期逻辑。
- 不引入数据库服务；继续使用当前 SQLite 文件和本地文件系统产物目录。
- 不改变 WebUI 的执行语义、权限边界、HITL 审批逻辑或 MockLLM 输出。
- 不把生成 HTML 直接嵌入同源页面执行；继续保持下载或源码预览的安全边界。

## 4. 推荐部署形态

采用“单机 Docker + 宿主机数据目录挂载”的最小可上线形态：

```text
浏览器
  -> http://服务器公网IP:8000
  -> Docker 容器 specgate-web
  -> /data/specgate-web 持久化目录
       -> web.sqlite3
       -> users/<user_id>/projects/<project_id>/
       -> run artifacts
```

部署时可以先直接开放 `8000` 端口，形成真实 URL：

```text
http://<服务器公网IP>:8000
```

如果后续购买域名或使用服务器面板，再加一层 Nginx/宝塔反向代理：

```text
https://<域名>
  -> Nginx / 面板反代
  -> 127.0.0.1:8000
  -> Docker 容器
```

这种形态满足课程短期开站检查，同时避免为三天展示引入过多运维复杂度。

## 5. Docker 设计

现有 `Dockerfile` 仍以 CLI demo 为默认命令。本阶段将其调整为 WebUI 镜像：

- 安装项目依赖：`python -m pip install -e .`
- 设置默认数据目录：`SPECGATE_WEB_DATA=/data/specgate-web`
- 创建并声明 `/data/specgate-web` 为持久化目录。
- 暴露端口 `8000`。
- 默认命令启动：

```text
specgate-web --host 0.0.0.0 --port 8000
```

仍保留 CLI 能力，因为镜像内安装的是完整 `specgate` 包；需要时可以覆盖容器命令运行 CLI。

## 6. 环境变量

部署文档需要明确以下变量：

- `SPECGATE_WEB_DATA`
  - WebUI 数据根目录。
  - 容器内推荐为 `/data/specgate-web`。
  - 宿主机通过 volume 挂载保存。

- `SPECGATE_WEB_SECRET`
  - 用于 API key 配置状态保护摘要。
  - 当前不驱动真实 LLM 调用。
  - 服务器部署必须设置为随机长字符串。

- `SPECGATE_WEB_SECURE_COOKIES`
  - 直接用 `http://公网IP:8000` 时应保持 `0` 或不设置，否则浏览器不会在 HTTP 下发送 secure cookie。
  - 使用 HTTPS 反向代理时设置为 `1`。

- `SPECGATE_WEB_DB_PATH`
  - 可选覆盖 SQLite 数据库位置。
  - 默认位于 `SPECGATE_WEB_DATA/web.sqlite3`，常规部署不需要单独设置。

## 7. 部署文档设计

新增 `docs/DEPLOYMENT.md`，使用中文写清楚：

1. 本地 Docker 验证
   - 构建镜像。
   - 挂载本地数据目录。
   - 打开 `http://127.0.0.1:8000`。

2. 云服务器部署
   - 安装 Docker。
   - 拉取或上传代码。
   - 构建镜像。
   - 创建宿主机数据目录。
   - 设置随机 `SPECGATE_WEB_SECRET`。
   - 运行容器并映射 `8000:8000`。

3. 获得真实 URL
   - 打开云服务器安全组或防火墙的 8000 端口。
   - 使用 `http://<公网IP>:8000` 作为检查 URL。

4. 可选域名/Nginx 反代
   - 给出最小 Nginx location 示例。
   - 说明 HTTPS 下才设置 `SPECGATE_WEB_SECURE_COOKIES=1`。

5. 运行维护
   - 查看日志。
   - 停止容器。
   - 重启容器。
   - 备份数据目录。
   - 更新镜像。

6. 安全边界
   - 不提交 `.env`。
   - 不把 API key 写入文档或截图。
   - 当前默认 MockLLM。
   - 用户项目在 WebUI 数据目录隔离保存。

## 8. CI 设计

现有 CI 已有：

- unit-test
- docker-build

本阶段保持这两个 job，并增强 Docker 检查：

- Docker 构建后执行一个轻量命令，验证镜像里的 WebUI 入口可用。
- 优先使用不会长期占用端口的 smoke 命令，例如：

```text
docker run --rm specgate:ci specgate-web --help
```

如果需要进一步验证导入 FastAPI app，可执行 Python 一行命令导入 `specgate.web_app:create_app`。不在 CI 中启动长驻服务，避免 workflow 卡住。

GitLab CI 同步保持构建检查，确保课程可能要求的 `.gitlab-ci.yml` 也能体现部署交付能力。

## 9. README 更新设计

README 当前已有 WebUI 和 Docker 简短说明。本阶段只做聚焦更新：

- WebUI 段落保留本地运行命令。
- Docker 段落改为 WebUI 部署默认命令，而不是 CLI demo。
- 增加指向 `docs/DEPLOYMENT.md` 的链接。
- 说明课程检查 URL 可以使用 `http://公网IP:8000`，域名和 HTTPS 是可选增强。

## 10. 测试策略

本阶段主要是部署配置和文档，但仍要做回归验证：

- `python -m unittest discover -s tests -v`
- `docker build -t specgate:local .`
- `docker run --rm specgate:local specgate-web --help`

如果本机 Docker 环境不可用，需要在最终说明中明确“Docker 本机未验证”，并依赖 CI 的 docker-build job 作为验证依据。

## 11. 验收标准

- 新镜像默认启动 WebUI，而不是只运行 CLI demo。
- 文档中能清楚说明如何得到一个真实可访问的课程检查 URL。
- 数据目录通过 volume 挂载后，重启容器不会丢失 WebUI 用户和项目数据。
- CI 能证明包依赖安装、单元测试和 Docker 镜像构建仍然正常。
- 所有改动不改变 MockLLM/harness 核心逻辑，不影响已有 WebUI、CLI、benchmark、HITL 和多代理测试。
