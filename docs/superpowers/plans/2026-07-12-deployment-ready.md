# WebUI 可部署化实施计划

> **给代理执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务执行本计划。步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 让 SpecGate WebUI 可以通过 Docker 部署到单台云服务器，并具备持久化数据、公网 URL 部署说明和 CI smoke 检查。

**架构：** 不改变现有 mock-first FastAPI WebUI 的运行语义。把当前 Python 项目打包成 Docker 镜像，镜像默认用 `specgate-web` 在 `0.0.0.0:8000` 启动；WebUI 数据统一保存在 `/data/specgate-web`；文档说明如何通过 `http://<服务器公网IP>:8000` 或可选 Nginx 反向代理提供真实访问地址。

**技术栈：** Python 3.11、FastAPI、Uvicorn、SQLite、Docker、GitHub Actions、GitLab CI、Markdown 文档。

---

## 文件结构

- 修改 `Dockerfile`
  - 使用 `python -m pip install -e .` 安装项目及依赖。
  - 设置 `SPECGATE_WEB_DATA=/data/specgate-web`。
  - 暴露 `8000` 端口。
  - 默认启动 `specgate-web --host 0.0.0.0 --port 8000`。

- 新增 `docs/DEPLOYMENT.md`
  - 中文部署指南，覆盖本地 Docker 验证、云服务器部署、公网 IP URL、可选 Nginx/域名反代、运维、备份和安全注意事项。

- 修改 `README.md`
  - 更新 Docker 章节，使其匹配 WebUI 部署，而不是旧的 CLI demo。
  - 链接到 `docs/DEPLOYMENT.md`。
  - 说明作业检查的真实 URL 可以是 `http://公网IP:8000`。

- 修改 `.github/workflows/ci.yml`
  - 保留 `unit-test`。
  - 保留 `docker-build`。
  - 增加 Docker smoke 检查：`docker run --rm specgate:ci specgate-web --help`。

- 修改 `.gitlab-ci.yml`
  - 保留现有 test 和 build job。
  - 在 `docker-build` 中增加相同的 Docker smoke 命令。

---

### 任务 1：更新 Docker 镜像默认启动目标

**文件：**
- 修改：`Dockerfile`

- [ ] **步骤 1：把 Dockerfile 替换为 WebUI 优先的镜像配置**

将 `Dockerfile` 改成以下完整内容：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY examples /app/examples

RUN python -m pip install --no-cache-dir -e .

ENV SPECGATE_WEB_DATA=/data/specgate-web

RUN mkdir -p /data/specgate-web

VOLUME ["/data/specgate-web"]
EXPOSE 8000

CMD ["specgate-web", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **步骤 2：确认 Dockerfile 包含预期的 WebUI 启动命令**

运行：

```powershell
Get-Content -LiteralPath Dockerfile
```

期望：输出包含：

```text
RUN python -m pip install --no-cache-dir -e .
ENV SPECGATE_WEB_DATA=/data/specgate-web
EXPOSE 8000
CMD ["specgate-web", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **步骤 3：提交 Dockerfile 改动**

运行：

```powershell
git add Dockerfile
git commit -m "build: make Docker image start WebUI"
```

期望：提交成功，且只修改 `Dockerfile`。

---

### 任务 2：新增部署指南

**文件：**
- 新增：`docs/DEPLOYMENT.md`

- [ ] **步骤 1：创建部署指南**

创建 `docs/DEPLOYMENT.md`，内容如下：

````markdown
# SpecGate WebUI 部署指南

本文说明如何把 SpecGate WebUI 部署到单台云服务器，并得到一个可供课程检查访问的真实 URL。当前部署仍然是 mock-first：默认使用 MockLLM，不会因为用户在 WebUI 里保存 API key 就自动调用真实模型。

## 1. 推荐部署形态

推荐使用单机 Docker：

```text
浏览器 -> http://服务器公网IP:8000 -> Docker 容器 -> /data/specgate-web 持久化目录
```

老师检查作业时，可以直接使用：

```text
http://<服务器公网IP>:8000
```

如果后续购买域名或使用服务器面板，可以再把域名反向代理到 `127.0.0.1:8000`。

## 2. 本地 Docker 验证

在仓库根目录构建镜像：

```powershell
docker build -t specgate:local .
```

在本机运行 WebUI：

```powershell
docker run --rm -p 8000:8000 `
  -e SPECGATE_WEB_SECRET="local-dev-secret-change-me" `
  -v "${PWD}\var\specgate_web_docker:/data/specgate-web" `
  specgate:local
```

打开：

```text
http://127.0.0.1:8000
```

如果看到登录/注册页面，说明镜像可以启动 WebUI。

## 3. 云服务器部署

以下命令以 Linux 服务器为例。先安装 Docker，并确保当前用户可以运行 `docker`。

拉取或上传项目代码后，进入仓库根目录：

```bash
cd SpecGate
docker build -t specgate:latest .
```

创建持久化数据目录：

```bash
mkdir -p /opt/specgate/data
```

生成一个随机密钥。可以使用：

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

启动容器：

```bash
docker run -d \
  --name specgate-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e SPECGATE_WEB_SECRET="<替换为上一步生成的随机密钥>" \
  -e SPECGATE_WEB_DATA="/data/specgate-web" \
  -v /opt/specgate/data:/data/specgate-web \
  specgate:latest
```

查看日志：

```bash
docker logs -f specgate-web
```

## 4. 获得真实 URL

在云服务器控制台或防火墙中开放 TCP `8000` 端口。

然后访问：

```text
http://<服务器公网IP>:8000
```

这就是课程检查可以使用的真实 URL。检查期间保持服务器和容器运行即可。

## 5. 可选：域名和 Nginx 反向代理

如果已经有域名，可以让 Nginx 代理到本机容器端口：

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

只有在 HTTPS 已经配置完成时，才建议给容器增加：

```bash
-e SPECGATE_WEB_SECURE_COOKIES="1"
```

如果仍然使用 `http://公网IP:8000`，不要开启 secure cookies，否则浏览器不会在 HTTP 下发送登录 cookie。

## 6. 常用运维命令

停止服务：

```bash
docker stop specgate-web
```

重新启动：

```bash
docker start specgate-web
```

删除旧容器：

```bash
docker rm specgate-web
```

更新镜像后重建容器：

```bash
docker stop specgate-web
docker rm specgate-web
docker build -t specgate:latest .
docker run -d \
  --name specgate-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e SPECGATE_WEB_SECRET="<原来的随机密钥>" \
  -e SPECGATE_WEB_DATA="/data/specgate-web" \
  -v /opt/specgate/data:/data/specgate-web \
  specgate:latest
```

备份数据：

```bash
tar -czf specgate-data-backup.tar.gz -C /opt/specgate data
```

## 7. 安全边界

- 不要提交 `.env`、API key 或服务器密钥。
- `SPECGATE_WEB_SECRET` 应使用随机长字符串。
- 当前 WebUI 默认仍使用 MockLLM，不会自动调用真实模型。
- 用户项目会被导入 WebUI 数据目录，SpecGate 不直接修改用户原始目录。
- 生成的 HTML 以下载或源码预览为主，避免在同源认证上下文中直接执行模型生成内容。
````

- [ ] **步骤 2：检查部署指南包含公网 URL 和 Cookie 警告**

运行：

```powershell
rg -n "http://<服务器公网IP>:8000|SPECGATE_WEB_SECURE_COOKIES|MockLLM|/opt/specgate/data" docs\DEPLOYMENT.md
```

期望：输出包含这四类内容。

- [ ] **步骤 3：提交部署指南**

运行：

```powershell
git add docs/DEPLOYMENT.md
git commit -m "docs: add WebUI deployment guide"
```

期望：提交成功，且新增一个文件。

---

### 任务 3：更新 README 部署入口

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：替换当前 Docker 章节**

找到以下章节开头：

```markdown
## Docker
```

从该章节开始，替换到以下段落结束：

```markdown
Mock 模式不需要 API key。真实 LLM 模式尚未作为 MVP 默认能力开放。
```

替换为：

````markdown
## Docker / 服务器部署

SpecGate 的 Docker 镜像默认启动 WebUI，适合部署到单台云服务器并提供课程检查 URL。

本地构建：

```powershell
docker build -t specgate:local .
```

本地运行 WebUI：

```powershell
docker run --rm -p 8000:8000 `
  -e SPECGATE_WEB_SECRET="local-dev-secret-change-me" `
  -v "${PWD}\var\specgate_web_docker:/data/specgate-web" `
  specgate:local
```

打开：

```text
http://127.0.0.1:8000
```

云服务器上可以映射 `8000:8000`，并把宿主机目录挂载到 `/data/specgate-web` 保存用户、项目、运行记录和产物。老师检查作业时，可以使用：

```text
http://<服务器公网IP>:8000
```

完整部署步骤见 `docs/DEPLOYMENT.md`。

Mock 模式不需要 API key。WebUI 当前默认仍然使用 MockLLM，不会因为保存 API key 就自动调用真实模型。
````

- [ ] **步骤 2：确认 README 链接到部署指南**

运行：

```powershell
rg -n "Docker / 服务器部署|docs/DEPLOYMENT.md|http://<服务器公网IP>:8000|MockLLM" README.md
```

期望：输出包含这四类内容。

- [ ] **步骤 3：提交 README 更新**

运行：

```powershell
git add README.md
git commit -m "docs: document Docker WebUI deployment"
```

期望：提交成功，且只修改 `README.md`。

---

### 任务 4：增加 CI Docker smoke 检查

**文件：**
- 修改：`.github/workflows/ci.yml`
- 修改：`.gitlab-ci.yml`

- [ ] **步骤 1：更新 GitHub Actions Docker job**

在 `.github/workflows/ci.yml` 中，找到：

```yaml
      - name: Build Docker image
        run: docker build -t specgate:ci .
```

在其后增加：

```yaml
      - name: Smoke test Docker WebUI entrypoint
        run: docker run --rm specgate:ci specgate-web --help
```

- [ ] **步骤 2：更新 GitLab CI Docker job**

在 `.gitlab-ci.yml` 中，把 `docker-build` 的 script 从：

```yaml
  script:
    - docker build -t specgate:ci .
```

改成：

```yaml
  script:
    - docker build -t specgate:ci .
    - docker run --rm specgate:ci specgate-web --help
```

- [ ] **步骤 3：确认 CI 文件包含 smoke 命令**

运行：

```powershell
rg -n "Smoke test Docker WebUI entrypoint|specgate-web --help" .github\workflows\ci.yml .gitlab-ci.yml
```

期望：输出同时包含两个 CI 文件。

- [ ] **步骤 4：提交 CI smoke 检查**

运行：

```powershell
git add .github/workflows/ci.yml .gitlab-ci.yml
git commit -m "ci: smoke test Docker WebUI entrypoint"
```

期望：提交成功，且修改两个 CI 文件。

---

### 任务 5：最终验证

**文件：**
- 不应产生新的源码改动。

- [ ] **步骤 1：确认验证前工作区状态**

运行：

```powershell
git status --short --branch
```

期望：当前分支为 `feat-deployment-ready`，且没有未提交改动。

- [ ] **步骤 2：运行全量单元测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

期望：所有测试通过。

- [ ] **步骤 3：构建 Docker 镜像**

运行：

```powershell
docker build -t specgate:local .
```

期望：镜像构建成功，并安装项目依赖。

- [ ] **步骤 4：运行 Docker WebUI 入口 smoke 检查**

运行：

```powershell
docker run --rm specgate:local specgate-web --help
```

期望：命令以状态码 0 退出，并输出 `specgate-web` 的 usage/help。

- [ ] **步骤 5：检查最终 diff 范围**

运行：

```powershell
git diff main...HEAD --stat
```

期望：diff 只包含部署规格、部署计划、Dockerfile、README、`docs/DEPLOYMENT.md` 和 CI 文件。

- [ ] **步骤 6：准备 PR 总结**

使用以下中文 PR 内容：

```markdown
## 概述

本 PR 将 SpecGate WebUI 从“本地可运行”推进到“单机服务器可部署”状态，面向课程检查提供真实 URL 的部署路径。

## 主要改动

- Docker 镜像默认启动 WebUI：`specgate-web --host 0.0.0.0 --port 8000`
- 增加 `/data/specgate-web` 持久化数据目录约定
- 新增中文部署文档 `docs/DEPLOYMENT.md`
- README 更新 Docker/服务器部署说明
- GitHub Actions 和 GitLab CI 增加 Docker WebUI entrypoint smoke test

## 安全边界

- 仍然保持 mock-first，不接真实 LLM
- WebUI 保存 API key 状态不会自动触发真实模型调用
- 用户项目导入隔离数据目录，不直接修改原始目录
- HTTP 公网 IP 部署时不启用 secure cookies；HTTPS 反代时才启用

## 验证

- [ ] `python -m unittest discover -s tests -v`
- [ ] `docker build -t specgate:local .`
- [ ] `docker run --rm specgate:local specgate-web --help`
```

期望：最终回复需要告诉用户哪些命令已通过，以及本机 Docker 是否可用。
