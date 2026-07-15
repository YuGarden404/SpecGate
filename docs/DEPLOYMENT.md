# SpecGate WebUI 部署指南

本文说明如何把 SpecGate WebUI 部署到单台云服务器，并得到一个可供课程检查访问的真实 URL。

当前部署仍然是 mock-first：默认使用 MockLLM，不会因为用户在 WebUI 里保存 API key 就自动调用真实模型。

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

### Web 运行时与数据库约束

生产部署保持单个 Web 进程，不要给 Uvicorn 增加多个 worker。当前有界调度器和运行恢复由单进程内的固定 worker 池协调；横向扩展需要额外的跨进程任务租约，不属于本阶段范围。

可配置项如下。所有值必须是十进制整数；非法值会让应用启动失败，避免静默回退到不安全配置。

| 环境变量 | 默认值 | 合法范围 | 含义 |
| --- | ---: | ---: | --- |
| `SPECGATE_WEB_WORKERS` | 4 | 1–16 | 同时执行 run 的固定 worker 数 |
| `SPECGATE_WEB_QUEUE_CAPACITY` | 32 | 1–256 | 等待 worker 的最大排队数 |
| `SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER` | 4 | 1–32 | 单用户活动 run 上限，且不得超过 worker 与队列容量之和 |
| `SPECGATE_WEB_RUN_TIMEOUT_SECONDS` | 60 | 1–3600 | worker 认领任务后的执行超时秒数 |

默认配置等价于：

```text
SPECGATE_WEB_WORKERS=4
SPECGATE_WEB_QUEUE_CAPACITY=32
SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER=4
SPECGATE_WEB_RUN_TIMEOUT_SECONDS=60
```

排队和人工审批等待不计入执行超时。取消为协作式：排队任务会直接移出队列，运行任务会收到取消信号，并在当前阻塞调用返回后的安全停止点终止。进程重启时，遗留 `running` 会稳定收敛为失败，`cancel_requested` 收敛为已取消，持久化的 `queued` 按创建顺序重新补入有界队列。

SQLite 连接启用 WAL、`synchronous=NORMAL` 和 5 秒 `busy_timeout`，用于缩短读写互斥并为短写锁竞争提供等待窗口。这些设置不替代单 Web 进程约束。课程验收和 Web 运行仍只使用 `MockLLM`，不会访问真实 LLM。

## 2. 本地 Docker 验证

在仓库根目录构建镜像：

```powershell
docker build -t specgate:local .
```

在本机运行 WebUI：

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $rng.GetBytes($bytes)
} finally {
  $rng.Dispose()
}
$credentialKey = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")

docker run --rm -p 8000:8000 `
  -e SPECGATE_WEB_CREDENTIAL_KEY="$credentialKey" `
  -e SPECGATE_WEB_WORKERS="4" `
  -e SPECGATE_WEB_QUEUE_CAPACITY="32" `
  -e SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER="4" `
  -e SPECGATE_WEB_RUN_TIMEOUT_SECONDS="60" `
  -v "${PWD}\var\specgate_web_docker:/data/specgate-web" `
  specgate:local
```

`SPECGATE_WEB_CREDENTIAL_KEY` 必须是 32 个随机字节的 URL-safe Base64 编码。主密钥缺失时，WebUI 的 MockLLM、项目和运行功能仍可使用，但保存 API key 会失败关闭。

打开：

```text
http://127.0.0.1:8000
```

如果看到登录或注册页面，说明镜像可以启动 WebUI。

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

生成一个随机 `SPECGATE_WEB_CREDENTIAL_KEY`：

```bash
python - <<'PY'
import base64
import os
print(base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"))
PY
```

启动容器：

```bash
docker run -d \
  --name specgate-web \
  --restart unless-stopped \
  -p 8000:8000 \
  -e SPECGATE_WEB_CREDENTIAL_KEY="<替换为上一步生成的主密钥>" \
  -e SPECGATE_WEB_DATA="/data/specgate-web" \
  -e SPECGATE_WEB_WORKERS="4" \
  -e SPECGATE_WEB_QUEUE_CAPACITY="32" \
  -e SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER="4" \
  -e SPECGATE_WEB_RUN_TIMEOUT_SECONDS="60" \
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

查看日志：

```bash
docker logs -f specgate-web
```

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
  -e SPECGATE_WEB_CREDENTIAL_KEY="<原来的主密钥>" \
  -e SPECGATE_WEB_DATA="/data/specgate-web" \
  -v /opt/specgate/data:/data/specgate-web \
  specgate:latest
```

备份数据：

```bash
tar -czf specgate-data-backup.tar.gz -C /opt/specgate data
```

## 7. 安全边界

- 不要把 `.env`、API key 或 `SPECGATE_WEB_CREDENTIAL_KEY` 提交到 Git。
- 主密钥必须与 SQLite 备份分开保存；只有同时持有数据库和主密钥才能恢复已加密凭据。
- 更换或丢失主密钥后，已有 API key 会进入“需要重新录入”状态，不能在线轮换或自动恢复。
- 当前 WebUI 仍只运行 MockLLM；保存 API key 不会启用或调用真实模型。
- 用户项目会被导入 WebUI 数据目录，SpecGate 不直接修改用户原始目录。
- 生成的 HTML 以下载或源码预览为主，避免在同源认证上下文中直接执行模型生成内容。
