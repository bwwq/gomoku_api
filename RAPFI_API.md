# Rapfi 多棋局本地 API

本服务直接调用 `Rapfi-YixinBoard/engine.exe`，不依赖 Yixin GUI。API 返回结构化 JSON，不返回面向用户的自然语言文案，调用方自行组织展示文本。

## 启动

```powershell
.\start-api.cmd
```

默认地址：

```text
http://127.0.0.1:8787
```

## 鉴权

服务器部署默认要求除 `/health` 外的接口都带 API Key：

```http
Authorization: Bearer <your-api-key>
```

也兼容：

```http
X-API-Key: <your-api-key>
```

未授权响应：

```json
{"ok":false,"error":{"code":"unauthorized","message":"missing or invalid API key"}}
```

配置文件：

```text
api/config.json
```

棋局文本存档：

```text
games/game-*.txt
```

活跃棋局 5 分钟没有访问会自动沉寂：服务停止对应 Rapfi 进程，但保留纯文本棋谱。再次请求该棋局时会按需要唤醒引擎，并用完整棋盘继续计算。

## 坐标

所有响应同时包含：

- `coord`: 人类坐标，例如 `H8`
- `x`, `y`: 0 基坐标，例如 `7, 7`

`A1` 表示左上角，`H8` 在 15 路棋盘上是中心点。也可以直接传 `"coord": "7,7"`。

## 强度五档

```http
GET /levels
```

当前预设：

| level | 名称 | 步时 | 深度 | 结点 | strength |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | beginner | 100ms | 3 | 10,000 | 10 |
| 2 | casual | 300ms | 5 | 50,000 | 30 |
| 3 | standard | 800ms | 8 | 300,000 | 60 |
| 4 | strong | 2000ms | 10 | 1,000,000 | 85 |
| 5 | deep | 5000ms | 14 | 5,000,000 | 100 |

强度实时生效：

- 每次 AI 思考前都会向 Rapfi 发送当前设置。
- 活跃棋局调用 `PATCH /games/{id}/settings` 会立刻向当前引擎进程发送设置。
- 沉寂棋局会保存设置，下次唤醒时应用。

## 创建棋局

```http
POST /games
Content-Type: application/json

{
  "boardSize": 15,
  "rule": "freestyle",
  "aiColor": "white",
  "level": 3
}
```

响应：

```json
{
  "ok": true,
  "game": {
    "id": "game-20260618-061500-a1b2c3",
    "status": "sleeping",
    "boardSize": 15,
    "rule": "freestyle",
    "aiColor": "white",
    "turn": "black",
    "winner": null,
    "moveCount": 0,
    "settings": {},
    "moves": []
  },
  "aiMove": null
}
```

`aiColor` 可用值：

- `"black"`
- `"white"`
- `"none"`

如果 `aiColor` 是 `"black"`，创建后默认会自动请求 AI 先下一手。

## 玩家落子

```http
POST /games/{gameId}/move
Content-Type: application/json

{
  "coord": "H8"
}
```

默认使用当前轮到的颜色。如果下一手轮到 AI，且 `aiColor` 匹配，会自动返回 `aiMove`。

响应：

```json
{
  "ok": true,
  "game": {},
  "move": {
    "color": "black",
    "coord": "H8",
    "x": 7,
    "y": 7,
    "source": "user",
    "at": "2026-06-18T06:15:20+08:00"
  },
  "aiMove": {
    "color": "white",
    "coord": "I8",
    "x": 8,
    "y": 7,
    "source": "ai",
    "at": "2026-06-18T06:15:21+08:00"
  }
}
```

如果不想自动触发 AI：

```json
{
  "coord": "H8",
  "autoAi": false
}
```

## 手动请求 AI

```http
POST /games/{gameId}/ai-move
Content-Type: application/json

{}
```

## 实时改强度

```http
PATCH /games/{gameId}/settings
Content-Type: application/json

{
  "level": 4
}
```

也可以覆盖单项：

```json
{
  "turnTimeMs": 1500,
  "maxDepth": 10,
  "maxNodes": 2000000,
  "strength": 70,
  "cautionFactor": 3
}
```

响应里：

- `applied: true` 表示已发给当前活跃 Rapfi 进程。
- `willApplyOnWake: true` 表示棋局沉寂中，设置已保存，下次唤醒生效。
- `engineApplied.commands` 是实际发给 Rapfi 的 `INFO` 命令。

## 查询和管理

```http
GET /games
GET /games/{gameId}
POST /games/{gameId}/undo
POST /games/{gameId}/sleep
POST /games/{gameId}/wake
DELETE /games/{gameId}
```

悔棋：

```json
{
  "plies": 2
}
```

## 文本命令入口

```http
POST /text
Content-Type: application/json

{
  "text": "game-20260618-061500-a1b2c3 H8"
}
```

也支持：

```text
新开一局 强度3
game-xxx 黑 H8
game-xxx 下一步
```

`/text` 只是兼容文字输入，响应仍然是结构化 JSON。

## 错误格式

```json
{
  "ok": false,
  "error": {
    "code": "occupied",
    "message": "coord is already occupied"
  }
}
```

## 并发模型

- 每个活跃棋局最多一个 Rapfi 子进程。
- 默认最多 3 个活跃引擎，由 `api/config.json` 的 `maxActiveEngines` 控制。
- 超过上限时，服务会优先沉寂最近最久未访问的活跃棋局。
- 每次 AI 计算都发送完整棋盘给 Rapfi，避免多棋局或恢复后状态串线。

## Docker 部署

Docker/VPS 部署看：

```text
DOCKER_DEPLOY.md
```

容器默认使用 Linux AVX2 引擎：

```text
Rapfi-engine/pbrain-rapfi-linux-clang-avx2
```
