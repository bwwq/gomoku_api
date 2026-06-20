# Gomoku Rapfi API

一个基于 Rapfi 引擎的五子棋 HTTP API，支持多棋局、自动沉寂/唤醒、强度档位和 Docker 部署。

## 快速开始

本地启动：

```powershell
python api\server.py
```

默认监听：

```text
http://127.0.0.1:8787
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

## Docker

```bash
docker compose -p rapfi-api up -d --build
```

`RAPFI_API_KEY` 通过环境变量或 `.env` 配置；为空时关闭鉴权。

```env
RAPFI_API_KEY=<your-api-key>
```

## 文档

- API 使用说明：`RAPFI_API.md`
- Docker 部署说明：`DOCKER_DEPLOY.md`
- 客户端/机器人适配说明：`WZQ_API_ADAPTER_GUIDE.md`

## 仓库内容

仓库保留 API 服务代码、部署文件、文档，以及 Docker 部署需要的 Linux Rapfi 引擎文件。运行时日志、棋局存档、本地环境变量、下载包、GUI 版 YixinBoard 和不需要的跨平台引擎二进制不会提交。
