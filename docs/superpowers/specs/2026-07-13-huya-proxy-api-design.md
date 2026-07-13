# HuyaLive Proxy API 设计文档

**日期：** 2026-07-13
**状态：** 已批准

## 概述

在 huya_live 项目中新增 FastAPI Web 服务，作为"中间件代理"，将虎牙直播间的动态流地址映射为固定 URL。NS 上的 nxmp 播放器通过访问固定 URL，由中间件实时解析真实流地址并 302 重定向，实现无缝播放。

## 核心方案

**纯 302 重定向** — 服务器仅做"地址翻译"，不代理流量，零带宽消耗。

```
nxmp → GET /huya/123456?key=xxx → FastAPI → HuyaLive.get_stream_url() → 302 → 虎牙CDN
```

## API 接口设计

### 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/huya/{room_id}` | GET | 获取直播流，302 重定向到真实 FLV 地址 |
| `/huya/{room_id}/info` | GET | 获取房间信息（JSON），不重定向 |

### 请求参数

| 参数 | 位置 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `room_id` | path | 是 | - | 房间号（数字或主播昵称） |
| `key` | query | 是 | - | API Key 鉴权 |
| `quality` | query | 否 | 0 | 清晰度：0=原画, 2000=高清, 4000=超清 |
| `cdn` | query | 否 | 自动 | CDN 线路：tx/ali/hw 等 |

### 响应

**成功（直播中）：** HTTP 302 → `Location: https://tx.flv.huya.com/src/xxx.flv?wsSecret=xxx&...`

**失败场景：**

| 状态码 | 场景 | 响应体 |
|--------|------|--------|
| 401 | key 缺失或错误 | `{"error": "Unauthorized", "message": "Invalid or missing API key"}` |
| 404 | 房间不存在 | `{"error": "Not Found", "message": "Room 123456 not found"}` |
| 410 | 主播未开播 | `{"error": "Gone", "message": "Room 123456 is offline"}` |
| 500 | 解析失败 | `{"error": "Internal Error", "message": "Failed to resolve stream URL"}` |
| 504 | 虎牙服务器超时 | `{"error": "Gateway Timeout", "message": "Huya server timeout"}` |

### 示例

```
GET /huya/123456?key=mysecret&quality=0&cdn=tx
→ 302 Location: https://tx.flv.huya.com/src/123456.flv?wsSecret=abc&wsTime=def&...

GET /huya/123456/info?key=mysecret
→ 200 {"room_id": "123456", "status": "online", "stream_name": "xxx", "cdns": ["tx", "ali", "hw"]}
```

## 项目结构与文件变更

### 新增文件

| 文件 | 说明 |
|------|------|
| `api.py` | FastAPI Web 服务入口 |
| `Dockerfile` | Docker 镜像构建 |
| `docker-compose.yml` | Docker Compose 配置 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `requirements.txt` | 新增 fastapi, uvicorn 依赖 |

### 不修改的文件

`huya.py` 及 `huya_wup/`、`tars/` 目录下所有文件保持不变。`api.py` 仅导入和调用 `HuyaLive` 类。

## api.py 核心结构

```python
import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse
from huya import HuyaLive

app = FastAPI(title="HuyaLive Proxy")

API_KEY = os.environ.get("HUYA_API_KEY", "")
HUYA_PORT = int(os.environ.get("HUYA_PORT", "9898"))

def verify_key(key: str):
    if not API_KEY or key != API_KEY:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized", "message": "Invalid or missing API key"})

@app.get("/huya/{room_id}")
async def redirect_stream(room_id: str, key: str = Query(...), quality: int = Query(0), cdn: str = Query("")):
    verify_key(key)
    # 在 executor 中运行同步的 HuyaLive
    huya = HuyaLive(room_id)
    url = huya.get_stream_url(cdn=cdn or None, quality=quality)
    if not url:
        raise HTTPException(status_code=500, detail={"error": "Internal Error", "message": "Failed to resolve stream URL"})
    return RedirectResponse(url=url, status_code=302)

@app.get("/huya/{room_id}/info")
async def room_info(room_id: str, key: str = Query(...)):
    verify_key(key)
    huya = HuyaLive(room_id)
    # 返回房间信息 JSON
```

## 鉴权设计

- API Key 通过环境变量 `HUYA_API_KEY` 配置
- Docker 部署时通过 `docker-compose.yml` 的 `environment` 字段传入
- 若 `HUYA_API_KEY` 未设置或为空，所有请求返回 401
- key 参数为必填，缺失或错误均返回 401

## 错误处理

### HuyaLive 异常映射

| HuyaLive 行为 | api.py 处理 |
|----------------|-------------|
| `get_room_profile()` 返回空/解析失败 | 404 Room not found |
| 房间状态为未开播 | 410 Room is offline |
| `get_cdn_token_info_ex()` 请求失败 | 500 Failed to get CDN token |
| `get_stream_url()` 返回空 URL | 500 Failed to resolve stream URL |
| 指定的 CDN 不存在 | 回退到默认 CDN，不报错 |
| 指定的 quality 不可用 | 回退到原画，不报错 |

### 并发处理

`HuyaLive` 使用同步 `requests` 库，在 FastAPI 异步框架中需通过 `run_in_executor` 将同步调用放入线程池，避免阻塞事件循环。

### 超时

对虎牙服务器的请求设置 10 秒超时，超时返回 504。

## Docker 部署

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9898
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", " , "--port", "9898"]
```

### docker-compose.yml

```yaml
services:
  huya-proxy:
    build: .
    ports:
      - "9898:9898"
    environment:
      - HUYA_API_KEY=your_secret_key_here
    restart: unless-stopped
```

### 部署流程

```bash
# 1. 克隆项目
git clone <repo> && cd huya_live

# 2. 修改 docker-compose.yml 中的 HUYA_API_KEY

# 3. 一键启动
docker compose up -d

# 4. 测试
curl -v "http://服务器IP:9898/huya/123456?key=your_secret_key"
```

## NS 端使用方式

### .strm 文件（单房间）

在 NS SD 卡 nxmp 可访问目录下创建 `.strm` 文件：

```
# 文件名: 虎牙-123456.strm
# 文件内容（单行）:
http://服务器IP:9898/huya/123456?key=your_secret_key
```

### .m3u 播放列表（多房间）

```
#EXTM3U
#EXTINF:-1,虎牙-房间123456
http://服务器IP:9898/huya/123456?key=your_secret_key
#EXTINF:-1,虎牙-房间789012
http://服务器IP:9898/huya/789012?key=your_secret_key&quality=2000
#EXTINF:-1,虎牙-房间345678(阿里CDN)
http://服务器IP:9898/huya/345678?key=your_secret_key&cdn=ali
```

### 参数说明

- 原画：`/huya/123456?key=xxx`（默认）
- 高清：`/huya/123456?key=xxx&quality=2000`
- 超清：`/huya/123456?key=xxx&quality=4000`
- 指定CDN：`/huya/123456?key=xxx&cdn=ali`

## 流格式

仅支持 FLV。当前 huya_live 已完整实现 FLV 流地址构建，mpv/nxmp 对 FLV 网络流支持良好。

## 缓存策略

无缓存，每次请求实时解析。虎牙 Token 有效期较长（wsTime 延长至 24 小时），实际使用中不会频繁请求。

## 约束与限制

1. Token 过期后需重新点击 .strm 文件触发重新解析
2. 仅支持 FLV 格式，不支持 HLS/m3u8
3. API Key 为简单字符串比对，非加密鉴权，适合个人使用场景
4. 服务器需能访问虎牙 CDN（m.huya.com, wup.huya.com 等）
