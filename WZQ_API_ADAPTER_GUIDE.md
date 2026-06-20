# 五子棋 Rapfi API 适配器开发说明

这份文档给另一个 AI 或程序员使用，用来编写调用五子棋 Rapfi API 的客户端、机器人适配器或聊天式对弈程序。

## 当前部署

```text
BASE_URL = http://your-server:8787
API_KEY  = <your-api-key>
```

除 `GET /health` 外，所有接口都需要鉴权：

```http
Authorization: Bearer <your-api-key>
```

也兼容：

```http
X-API-Key: <your-api-key>
```

所有请求和响应默认使用 JSON，编码为 UTF-8。API 只返回结构化数据，不返回聊天文案；调用方负责把棋局、落子、胜负和错误组织成用户可读文本。

## 核心概念

- 一盘棋由 `game.id` 唯一标识，调用方必须保存它。
- 每盘棋可以独立进行，支持多棋局并发。
- 服务器会在一段时间无访问后让棋局沉寂，只保留文本棋谱；再次请求该棋局时会自动按棋谱继续。
- 当前 VPS 配置的沉寂时间是 `180` 秒。
- 坐标同时支持人类坐标和 0 基坐标。
- `A1` 是左上角，15 路棋盘中心是 `H8`，对应 `x=7,y=7`。

## 推荐交互流程

1. 程序启动时调用 `GET /health` 检查服务。
2. 新用户或新对局时调用 `POST /games` 创建棋局。
3. 保存返回的 `game.id`，后续每步都带上这个 id。
4. 用户输入坐标后调用 `POST /games/{gameId}/move`。
5. 如果响应里的 `aiMove` 不为 `null`，把该 AI 落子展示给用户。
6. 每次响应都以 `game` 对象为准更新本地状态。
7. 如果 `game.winner` 不为 `null`，该局结束。

## 通用错误格式

错误响应也是 JSON：

```json
{
  "ok": false,
  "error": {
    "code": "unauthorized",
    "message": "missing or invalid API key"
  }
}
```

调用方应按 HTTP 状态码和 `error.code` 处理：

| HTTP | 常见 code | 含义 |
| --- | --- | --- |
| 400 | `invalid_json`, `missing_coord`, `invalid_coord`, `coord_out_of_range`, `invalid_level` | 请求参数错误 |
| 401 | `unauthorized` | 未带 API Key 或 API Key 错误 |
| 404 | `not_found`, `game_not_found` | 路由或棋局不存在 |
| 409 | `occupied`, `wrong_turn`, `game_finished`, `game_exists` | 棋局状态冲突 |
| 500 | `engine_failed`, `internal_error` | 引擎或服务内部错误 |

AI 落子可能需要等待，客户端建议给落子和 AI 计算请求设置 `60` 秒左右超时。

## 数据结构

### Game

典型 `game`：

```json
{
  "id": "game-20260618-092119-d9d9f6",
  "status": "active",
  "boardSize": 15,
  "rule": "freestyle",
  "aiColor": "white",
  "turn": "black",
  "winner": null,
  "moveCount": 2,
  "settings": {
    "level": 2,
    "name": "casual",
    "turnTimeMs": 300,
    "matchTimeMs": 300000,
    "maxDepth": 5,
    "maxNodes": 50000,
    "strength": 30,
    "cautionFactor": 1,
    "threadNum": 1
  },
  "moves": []
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 棋局 id |
| `status` | string | `active` 或 `sleeping` |
| `boardSize` | number | 棋盘大小，默认 15 |
| `rule` | string | 规则，常用 `freestyle` |
| `aiColor` | string/null | AI 执棋，`black`、`white` 或 `null` |
| `turn` | string | 当前轮到谁，`black` 或 `white` |
| `winner` | string/null | 胜者，`black`、`white`、`draw` 或 `null` |
| `moveCount` | number | 已落子数 |
| `settings` | object | 当前强度和引擎设置 |
| `moves` | array | 完整落子列表；列表接口不带该字段 |

### Move

```json
{
  "color": "black",
  "coord": "H8",
  "x": 7,
  "y": 7,
  "source": "user",
  "at": "2026-06-18T17:21:19+08:00"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `color` | string | `black` 或 `white` |
| `coord` | string | 人类坐标，如 `H8` |
| `x` | number | 0 基横坐标 |
| `y` | number | 0 基纵坐标 |
| `source` | string | `user` 或 `ai` |
| `at` | string | ISO 时间 |

## 接口

### 健康检查

不需要鉴权。

```http
GET /health
```

响应：

```json
{"ok":true,"status":"up","time":"2026-06-18T17:18:42+08:00"}
```

### 查询强度档位

```http
GET /levels
Authorization: Bearer <your-api-key>
```

响应：

```json
{
  "ok": true,
  "levels": [
    {"level":1,"name":"beginner","turnTimeMs":100,"maxDepth":3,"maxNodes":10000,"strength":10},
    {"level":2,"name":"casual","turnTimeMs":300,"maxDepth":5,"maxNodes":50000,"strength":30},
    {"level":3,"name":"standard","turnTimeMs":800,"maxDepth":8,"maxNodes":300000,"strength":60},
    {"level":4,"name":"strong","turnTimeMs":2000,"maxDepth":10,"maxNodes":1000000,"strength":85},
    {"level":5,"name":"deep","turnTimeMs":5000,"maxDepth":14,"maxNodes":5000000,"strength":100}
  ]
}
```

### 创建棋局

```http
POST /games
Authorization: Bearer <your-api-key>
Content-Type: application/json

{
  "boardSize": 15,
  "rule": "freestyle",
  "aiColor": "white",
  "level": 2
}
```

参数：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 否 | 自定义 id，必须以 `game-` 开头 |
| `boardSize` | 否 | 默认 15，允许 5 到 22 |
| `rule` | 否 | 默认 `freestyle` |
| `aiColor` | 否 | `black`、`white`、`none`；默认 `white` |
| `level` | 否 | 1 到 5，默认 2 |
| `settings` | 否 | 覆盖具体引擎参数 |
| `autoAi` | 否 | 当 `aiColor=black` 时是否让 AI 先手，默认 true |

响应重点：

```json
{
  "ok": true,
  "game": {
    "id": "game-20260618-092119-d9d9f6",
    "turn": "black",
    "aiColor": "white",
    "moveCount": 0,
    "winner": null,
    "moves": []
  },
  "aiMove": null
}
```

如果 `aiColor` 是 `black` 且 `autoAi` 为 true，创建响应里可能直接带 `aiMove`。

### 查询棋局列表

```http
GET /games
Authorization: Bearer <your-api-key>
```

响应：

```json
{
  "ok": true,
  "games": [
    {
      "id": "game-20260618-092119-d9d9f6",
      "status": "sleeping",
      "boardSize": 15,
      "turn": "black",
      "winner": null,
      "moveCount": 2
    }
  ]
}
```

列表里的 `game` 不包含完整 `moves`。要完整棋谱请查单局。

### 查询单局

```http
GET /games/{gameId}
Authorization: Bearer <your-api-key>
```

响应：

```json
{
  "ok": true,
  "game": {
    "id": "game-20260618-092119-d9d9f6",
    "moves": []
  }
}
```

### 玩家落子

```http
POST /games/{gameId}/move
Authorization: Bearer <your-api-key>
Content-Type: application/json

{
  "coord": "H8"
}
```

也可以传 0 基坐标：

```json
{"x":7,"y":7}
```

可选参数：

| 字段 | 说明 |
| --- | --- |
| `color` | 通常不传；不传则使用当前 `game.turn` |
| `autoAi` | 默认 true；如果落子后轮到 AI，会自动请求 AI 回合 |

典型响应：

```json
{
  "ok": true,
  "game": {
    "id": "game-20260618-092119-d9d9f6",
    "turn": "black",
    "moveCount": 2,
    "winner": null
  },
  "move": {
    "color": "black",
    "coord": "H8",
    "x": 7,
    "y": 7,
    "source": "user"
  },
  "aiMove": {
    "color": "white",
    "coord": "H5",
    "x": 7,
    "y": 4,
    "source": "ai"
  }
}
```

调用方应展示 `move` 和 `aiMove`，但必须以响应里的 `game` 作为最终状态。`aiMove` 可能为 `null`，例如 `autoAi=false`、AI 未执当前颜色、或棋局已经结束。

### 手动请求 AI 落子

```http
POST /games/{gameId}/ai-move
Authorization: Bearer <your-api-key>
Content-Type: application/json

{}
```

适用于：

- `autoAi=false` 后手动控制 AI 时机。
- `aiColor=none`，但仍希望请求引擎给当前方走一步。
- 聊天程序收到“让 AI 下”“继续思考”等指令。

响应：

```json
{
  "ok": true,
  "game": {},
  "aiMove": {}
}
```

### 悔棋

```http
POST /games/{gameId}/undo
Authorization: Bearer <your-api-key>
Content-Type: application/json

{
  "plies": 2
}
```

`plies` 表示撤销半步数。人机对局里常用 `2`，表示撤销玩家和 AI 各一步。

响应：

```json
{
  "ok": true,
  "game": {},
  "removed": []
}
```

### 修改强度

```http
PATCH /games/{gameId}/settings
Authorization: Bearer <your-api-key>
Content-Type: application/json

{
  "level": 3
}
```

也可以覆盖具体参数：

```json
{
  "turnTimeMs": 800,
  "maxDepth": 8,
  "maxNodes": 300000,
  "strength": 60,
  "cautionFactor": 3,
  "threadNum": 1
}
```

响应：

```json
{
  "ok": true,
  "gameId": "game-20260618-092119-d9d9f6",
  "settings": {},
  "applied": true,
  "willApplyOnWake": false,
  "engineApplied": {
    "commands": []
  }
}
```

`applied=true` 表示已对当前活跃引擎实时生效；`willApplyOnWake=true` 表示棋局当前沉寂，设置已保存，下次唤醒时应用。

### 沉寂和唤醒

通常调用方不需要手动调用，服务会自动处理。

```http
POST /games/{gameId}/sleep
POST /games/{gameId}/wake
Authorization: Bearer <your-api-key>
```

### 删除棋局

```http
DELETE /games/{gameId}
Authorization: Bearer <your-api-key>
```

响应：

```json
{"ok":true,"gameId":"game-xxx","deleted":true}
```

## 文本命令入口

结构化接口更适合程序调用，但也提供一个文本入口：

```http
POST /text
Authorization: Bearer <your-api-key>
Content-Type: application/json

{
  "text": "新游戏 level 2"
}
```

支持示例：

```text
新游戏 level 2
new level 3 ai black
game-20260618-092119-d9d9f6 H8
game-20260618-092119-d9d9f6 黑 H8
game-20260618-092119-d9d9f6 下一步
game-20260618-092119-d9d9f6 ai
```

响应仍然是结构化 JSON，并会额外带 `action` 字段，例如 `create_game`、`move`、`ai_move`。

## Curl 示例

```bash
BASE_URL="http://your-server:8787"
API_KEY="<your-api-key>"

curl "$BASE_URL/health"

curl -H "Authorization: Bearer $API_KEY" "$BASE_URL/levels"

curl -X POST "$BASE_URL/games" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"level":2,"aiColor":"white","rule":"freestyle","boardSize":15}'

curl -X POST "$BASE_URL/games/game-xxx/move" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"coord":"H8"}'
```

## Python 最小客户端示例

```python
import requests

BASE_URL = "http://your-server:8787"
API_KEY = "<your-api-key>"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def api(method, path, json_body=None, timeout=60):
    resp = requests.request(
        method,
        BASE_URL + path,
        headers=HEADERS,
        json=json_body,
        timeout=timeout,
    )
    data = resp.json()
    if not resp.ok or not data.get("ok"):
        raise RuntimeError(data.get("error", data))
    return data


def new_game(level=2, ai_color="white"):
    return api("POST", "/games", {
        "boardSize": 15,
        "rule": "freestyle",
        "aiColor": ai_color,
        "level": level,
    })


def play_user_move(game_id, coord):
    return api("POST", f"/games/{game_id}/move", {"coord": coord})


created = new_game()
game_id = created["game"]["id"]
result = play_user_move(game_id, "H8")

print("玩家:", result["move"]["coord"])
if result["aiMove"]:
    print("AI:", result["aiMove"]["coord"])
print("胜者:", result["game"]["winner"])
```

## 给聊天式适配器的建议

- 为每个用户或每个会话保存一个当前 `gameId`。
- 如果用户没有当前棋局，先调用 `POST /games` 创建。
- 用户说坐标时，调用 `POST /games/{gameId}/move`。
- 用户说“悔棋”时，调用 `POST /games/{gameId}/undo`，人机对局默认 `plies=2`。
- 用户说“调强度到 3 档”时，调用 `PATCH /games/{gameId}/settings`，body 为 `{"level":3}`。
- 用户说“继续”“AI 下”时，调用 `POST /games/{gameId}/ai-move`。
- 展示棋盘时，根据 `game.moves` 自行渲染，不要猜测服务端状态。
- 遇到 `wrong_turn`、`occupied`、`game_finished` 等 409 错误，应把错误转成用户可理解的话，并调用 `GET /games/{gameId}` 同步状态。

## 可直接交给另一个 AI 的任务描述

请写一个客户端程序调用五子棋 Rapfi API。服务地址是 `http://your-server:8787`，除 `/health` 外所有接口都要带 `Authorization: Bearer <your-api-key>`。程序应保存每盘棋的 `game.id`，创建棋局用 `POST /games`，玩家落子用 `POST /games/{gameId}/move`，读取响应里的 `move`、`aiMove` 和 `game` 更新状态。坐标可传 `coord` 如 `H8`，也可传 `x/y` 0 基坐标。API 不返回聊天文案，只返回 JSON；程序负责生成用户可读文本和棋盘显示。错误时按 `error.code` 处理，特别是 `unauthorized`、`occupied`、`wrong_turn`、`game_finished`、`game_not_found`。请求 AI 计算建议超时设置为 60 秒。
