# Docker 部署说明

这个镜像面向 Linux 服务器，默认使用官方 Rapfi Linux AVX2 引擎：

```text
Rapfi-engine/pbrain-rapfi-linux-clang-avx2
```

如果服务器 CPU 不支持 AVX2，可把 `RAPFI_ENGINE_EXE` 改成：

```text
Rapfi-engine/pbrain-rapfi-linux-clang-sse
```

## 当前服务器默认值

```text
maxActiveEngines: 3
defaultLevel: 2
idleSleepSeconds: 180
threadNum: 1 / engine
```

最坏情况下同时 3 个 Rapfi 进程计算，每个进程 1 个搜索线程。这个设置优先保证 VPS 稳定，不追求极限棋力。

五档强度：

| level | 名称 | 步时 | 深度 | 结点 |
| --- | --- | ---: | ---: | ---: |
| 1 | beginner | 100ms | 3 | 10,000 |
| 2 | casual | 300ms | 5 | 50,000 |
| 3 | standard | 800ms | 8 | 300,000 |
| 4 | strong | 2000ms | 10 | 1,000,000 |
| 5 | deep | 5000ms | 14 | 5,000,000 |

## 构建并启动

在项目根目录执行：

```bash
docker compose -p rapfi-api up -d --build
```

检查状态：

```bash
docker compose -p rapfi-api ps
docker compose -p rapfi-api logs -f rapfi-api
```

测试：

```bash
curl http://127.0.0.1:8787/health
curl -H "Authorization: Bearer $RAPFI_API_KEY" http://127.0.0.1:8787/levels
```

## 数据持久化

棋局文本存档挂载到宿主机：

```text
./games:/app/games
```

容器重建不会丢棋局。活跃棋局 180 秒没有访问会沉寂，停止对应引擎进程，只保留文本。

## 常用环境变量

这些变量可以在 `docker-compose.yml` 里改：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RAPFI_PORT` | `8787` | 容器内监听端口 |
| `RAPFI_IDLE_SLEEP_SECONDS` | `180` | 沉寂秒数 |
| `RAPFI_MAX_ACTIVE_ENGINES` | `3` | 最大活跃引擎数 |
| `RAPFI_DEFAULT_LEVEL` | `2` | 新棋局默认强度 |
| `RAPFI_ENGINE_EXE` | `Rapfi-engine/pbrain-rapfi-linux-clang-avx2` | 引擎可执行文件 |
| `RAPFI_API_KEY` | 空 | API Key；为空时关闭鉴权 |

如果只给自己用，可以把 `RAPFI_MAX_ACTIVE_ENGINES` 调到 `4`。如果开放公网多人使用，建议保持 `3`，甚至改成 `2`。

## API 文档

调用接口看：

```text
RAPFI_API.md
```
