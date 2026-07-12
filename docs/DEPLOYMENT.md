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

生成一个随机 `SPECGATE_WEB_SECRET`。可以使用：

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
