# Deployment-Ready WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SpecGate WebUI deployable on a single cloud server with Docker, persistent data, public URL guidance, and CI smoke coverage.

**Architecture:** Keep the current mock-first FastAPI WebUI unchanged. Package the existing Python project into a Docker image whose default command starts `specgate-web` on `0.0.0.0:8000`, persist WebUI state under `/data/specgate-web`, and document how to expose it via `http://<server-ip>:8000` or optional Nginx reverse proxy.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, SQLite, Docker, GitHub Actions, GitLab CI, Markdown docs.

---

## File Structure

- Modify `Dockerfile`
  - Install the package with dependencies using `python -m pip install -e .`.
  - Set `SPECGATE_WEB_DATA=/data/specgate-web`.
  - Expose `8000`.
  - Default to `specgate-web --host 0.0.0.0 --port 8000`.

- Create `docs/DEPLOYMENT.md`
  - Chinese deployment guide for local Docker verification, cloud server deployment, public IP URL, optional Nginx/domain reverse proxy, operations, backup, and security notes.

- Modify `README.md`
  - Update Docker section so it matches WebUI deployment instead of CLI demo.
  - Link to `docs/DEPLOYMENT.md`.
  - Mention that a real homework-check URL can be `http://公网IP:8000`.

- Modify `.github/workflows/ci.yml`
  - Keep `unit-test`.
  - Keep `docker-build`.
  - Add a Docker smoke step: `docker run --rm specgate:ci specgate-web --help`.

- Modify `.gitlab-ci.yml`
  - Keep existing test and build jobs.
  - Add the same Docker smoke command after build in `docker-build`.

---

### Task 1: Update Docker Image Defaults

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Replace the Dockerfile with WebUI-first packaging**

Edit `Dockerfile` to exactly this content:

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

- [ ] **Step 2: Verify the Dockerfile contains the expected WebUI command**

Run:

```powershell
Get-Content -LiteralPath Dockerfile
```

Expected: output includes:

```text
RUN python -m pip install --no-cache-dir -e .
ENV SPECGATE_WEB_DATA=/data/specgate-web
EXPOSE 8000
CMD ["specgate-web", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Commit Dockerfile change**

Run:

```powershell
git add Dockerfile
git commit -m "build: make Docker image start WebUI"
```

Expected: commit succeeds with one modified file.

---

### Task 2: Add Deployment Guide

**Files:**
- Create: `docs/DEPLOYMENT.md`

- [ ] **Step 1: Create the deployment guide**

Create `docs/DEPLOYMENT.md` with this content:

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

- [ ] **Step 2: Check the guide includes the public URL and cookie warning**

Run:

```powershell
rg -n "http://<服务器公网IP>:8000|SPECGATE_WEB_SECURE_COOKIES|MockLLM|/opt/specgate/data" docs\DEPLOYMENT.md
```

Expected: output includes all four patterns.

- [ ] **Step 3: Commit deployment guide**

Run:

```powershell
git add docs/DEPLOYMENT.md
git commit -m "docs: add WebUI deployment guide"
```

Expected: commit succeeds with one new file.

---

### Task 3: Update README Deployment Pointers

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the current Docker section**

Find the section beginning with:

```markdown
## Docker
```

Replace that section through the paragraph ending with:

```markdown
Mock 模式不需要 API key。真实 LLM 模式尚未作为 MVP 默认能力开放。
```

with:

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

- [ ] **Step 2: Verify README links to deployment guide**

Run:

```powershell
rg -n "Docker / 服务器部署|docs/DEPLOYMENT.md|http://<服务器公网IP>:8000|MockLLM" README.md
```

Expected: output includes all four patterns.

- [ ] **Step 3: Commit README update**

Run:

```powershell
git add README.md
git commit -m "docs: document Docker WebUI deployment"
```

Expected: commit succeeds with one modified file.

---

### Task 4: Add CI Docker Smoke Checks

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitlab-ci.yml`

- [ ] **Step 1: Update GitHub Actions Docker job**

In `.github/workflows/ci.yml`, after:

```yaml
      - name: Build Docker image
        run: docker build -t specgate:ci .
```

add:

```yaml
      - name: Smoke test Docker WebUI entrypoint
        run: docker run --rm specgate:ci specgate-web --help
```

- [ ] **Step 2: Update GitLab CI Docker job**

In `.gitlab-ci.yml`, update the `docker-build` script from:

```yaml
  script:
    - docker build -t specgate:ci .
```

to:

```yaml
  script:
    - docker build -t specgate:ci .
    - docker run --rm specgate:ci specgate-web --help
```

- [ ] **Step 3: Verify CI files contain the smoke command**

Run:

```powershell
rg -n "Smoke test Docker WebUI entrypoint|specgate-web --help" .github\workflows\ci.yml .gitlab-ci.yml
```

Expected: output includes both CI files.

- [ ] **Step 4: Commit CI smoke checks**

Run:

```powershell
git add .github/workflows/ci.yml .gitlab-ci.yml
git commit -m "ci: smoke test Docker WebUI entrypoint"
```

Expected: commit succeeds with two modified files.

---

### Task 5: Final Verification

**Files:**
- No intended source changes.

- [ ] **Step 1: Confirm working tree before verification**

Run:

```powershell
git status --short --branch
```

Expected: branch is `feat-deployment-ready`; no uncommitted changes.

- [ ] **Step 2: Run full unit tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Build Docker image**

Run:

```powershell
docker build -t specgate:local .
```

Expected: image builds successfully and installs package dependencies.

- [ ] **Step 4: Run Docker WebUI entrypoint smoke test**

Run:

```powershell
docker run --rm specgate:local specgate-web --help
```

Expected: command exits with status 0 and prints usage for `specgate-web`.

- [ ] **Step 5: Review final diff against main**

Run:

```powershell
git diff main...HEAD --stat
```

Expected: diff includes the deployment spec, deployment plan, Dockerfile, README, `docs/DEPLOYMENT.md`, and CI files only.

- [ ] **Step 6: Prepare PR summary**

Use this Chinese PR summary:

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

Expected: final response can tell the user which commands passed and whether Docker was available locally.
