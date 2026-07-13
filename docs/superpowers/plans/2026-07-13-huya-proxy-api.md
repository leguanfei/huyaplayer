# HuyaLive Proxy API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 huya_live 项目中新增 FastAPI Web 服务，通过 302 重定向将固定 URL 映射到虎牙直播真实流地址，供 NS 上的 nxmp 播放器使用。

**Architecture:** FastAPI 应用 (`api.py`) 导入现有 `HuyaLive` 类，对外暴露 `/huya/{room_id}` 端点。请求到达后，服务端调用 `HuyaLive` 解析真实流地址，返回 302 重定向。同步的 `HuyaLive` 调用通过 `run_in_executor` 在线程池中执行，避免阻塞异步事件循环。

**Tech Stack:** Python 3.11, FastAPI, uvicorn, requests, huya_live 现有模块 (huya_wup, tars)

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 新增 | `api.py` | FastAPI 应用：路由、鉴权、错误映射、302 重定向 |
| 新增 | `Dockerfile` | Docker 镜像构建 |
| 新增 | `docker-compose.yml` | Docker Compose 一键部署 |
| 修改 | `requirements.txt` | 新增 fastapi, uvicorn 依赖 |
| 不变 | `huya.py` | 现有 CLI 工具，不修改 |
| 不变 | `huya_wup/` | WUP 协议模块，不修改 |
| 不变 | `tars/` | Tars 协议模块，不修改 |

---

### Task 1: 更新 requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加 fastapi 和 uvicorn 依赖**

将 `requirements.txt` 修改为：

```
requests>=2.28.0
fastapi>=0.104.0
uvicorn>=0.24.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore: add fastapi and uvicorn dependencies"
```

---

### Task 2: 创建 api.py — 鉴权与基础框架

**Files:**
- Create: `api.py`

- [ ] **Step 1: 编写 api.py 基础框架和鉴权逻辑**

创建 `api.py`，内容如下：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
HuyaLive Proxy API
将虎牙直播间动态流地址映射为固定 URL，通过 302 重定向实现无缝播放

使用方法:
    HUYA_API_KEY=your_secret uvicorn api:app --host 0.0.0.0 --port 9898
"""

import os
import asyncio
from functools import partial

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from huya import HuyaLive

app = FastAPI(title="HuyaLive Proxy")

API_KEY = os.environ.get("HUYA_API_KEY", "")


def verify_key(key: str):
    """验证 API Key"""
    if not API_KEY or key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": "Unauthorized", "message": "Invalid or missing API key"},
        )


async def run_sync(func, *args, **kwargs):
    """在线程池中运行同步函数，避免阻塞事件循环"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))
```

- [ ] **Step 2: Commit**

```bash
git add api.py
git commit -m "feat: add api.py base framework with auth and async helper"
```

---

### Task 3: 创建 api.py — /huya/{room_id} 重定向端点

**Files:**
- Modify: `api.py`

- [ ] **Step 1: 在 api.py 末尾添加重定向端点**

在 `api.py` 的 `run_sync` 函数之后追加：

```python
def _resolve_stream_url(room_id: str, quality: int, cdn: str) -> dict:
    """同步解析直播流地址，返回结果字典供异步端点使用

    Returns:
        {"type": "redirect", "url": "..."}  — 成功，302 重定向
        {"type": "error", "status": 410, "error": "...", "message": "..."}  — 错误
    """
    try:
        huya = HuyaLive(room_id)
        room_profile = huya.get_room_profile()
    except Exception as e:
        err_msg = str(e)
        if "找不到这个主播" in err_msg or "涉嫌违规" in err_msg:
            return {"type": "error", "status": 404, "error": "Not Found", "message": f"Room {room_id} not found"}
        if "无法解析页面数据" in err_msg or "JSON解析错误" in err_msg:
            return {"type": "error", "status": 404, "error": "Not Found", "message": f"Room {room_id} not found"}
        return {"type": "error", "status": 504, "error": "Gateway Timeout", "message": "Huya server error"}

    if not room_profile.get("live"):
        return {"type": "error", "status": 410, "error": "Gone", "message": f"Room {room_id} is offline"}

    try:
        url = huya.get_stream_url(cdn=cdn or None)
    except Exception as e:
        err_msg = str(e)
        if "getCdnTokenInfoEx" in err_msg or "token" in err_msg.lower():
            return {"type": "error", "status": 500, "error": "Internal Error", "message": "Failed to get CDN token"}
        return {"type": "error", "status": 500, "error": "Internal Error", "message": "Failed to resolve stream URL"}

    if not url:
        return {"type": "error", "status": 500, "error": "Internal Error", "message": "Failed to resolve stream URL"}

    # 添加清晰度参数（与 huya.py CLI 行为一致）
    if quality > 0:
        url += f"&ratio={quality}"

    return {"type": "redirect", "url": url}


@app.get("/huya/{room_id}")
async def redirect_stream(
    room_id: str,
    key: str = Query(..., description="API Key"),
    quality: int = Query(0, description="清晰度: 0=原画, 2000=高清, 4000=超清"),
    cdn: str = Query("", description="CDN 线路: tx/ali/hw 等"),
):
    """获取直播流，302 重定向到真实 FLV 地址"""
    verify_key(key)
    result = await run_sync(_resolve_stream_url, room_id, quality, cdn)

    if result["type"] == "error":
        raise HTTPException(
            status_code=result["status"],
            detail={"error": result["error"], "message": result["message"]},
        )

    return RedirectResponse(url=result["url"], status_code=302)
```

- [ ] **Step 2: Commit**

```bash
git add api.py
git commit -m "feat: add /huya/{room_id} redirect endpoint"
```

---

### Task 4: 创建 api.py — /huya/{room_id}/info 端点

**Files:**
- Modify: `api.py`

- [ ] **Step 1: 在 api.py 末尾添加 info 端点**

在 `redirect_stream` 函数之后追加：

```python
def _get_room_info(room_id: str) -> dict:
    """同步获取房间信息，返回结果字典"""
    try:
        huya = HuyaLive(room_id)
        room_profile = huya.get_room_profile()
    except Exception as e:
        err_msg = str(e)
        if "找不到这个主播" in err_msg or "涉嫌违规" in err_msg:
            return {"type": "error", "status": 404, "error": "Not Found", "message": f"Room {room_id} not found"}
        return {"type": "error", "status": 504, "error": "Gateway Timeout", "message": "Huya server error"}

    if not room_profile.get("live"):
        return {
            "type": "info",
            "data": {
                "room_id": room_id,
                "status": "offline",
                "artist": room_profile.get("message", ""),
            },
        }

    cdns = [s["sCdnType"].lower() for s in room_profile.get("streams_info", [])]
    stream_name = room_profile.get("streams_info", [{}])[0].get("sStreamName", "") if room_profile.get("streams_info") else ""

    return {
        "type": "info",
        "data": {
            "room_id": room_id,
            "status": "online",
            "artist": room_profile.get("artist", ""),
            "room_title": room_profile.get("room_title", ""),
            "stream_name": stream_name,
            "cdns": cdns,
            "bitrate_info": room_profile.get("bitrate_info", []),
        },
    }


@app.get("/huya/{room_id}/info")
async def room_info(
    room_id: str,
    key: str = Query(..., description="API Key"),
):
    """获取房间信息（JSON）"""
    verify_key(key)
    result = await run_sync(_get_room_info, room_id)

    if result["type"] == "error":
        raise HTTPException(
            status_code=result["status"],
            detail={"error": result["error"], "message": result["message"]},
        )

    return JSONResponse(content=result["data"])
```

- [ ] **Step 2: Commit**

```bash
git add api.py
git commit -m "feat: add /huya/{room_id}/info endpoint"
```

---

### Task 5: 创建 Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: 编写 Dockerfile**

创建 `Dockerfile`，内容如下：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9898

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "9898"]
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "docker: add Dockerfile for HuyaLive Proxy API"
```

---

### Task 6: 创建 docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: 编写 docker-compose.yml**

创建 `docker-compose.yml`，内容如下：

```yaml
services:
  huya-proxy:
    build: .
    ports:
      - "9898:9898"
    environment:
      - HUYA_API_KEY=change_me_to_your_secret_key
    restart: unless-stopped
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "docker: add docker-compose.yml for one-click deployment"
```

---

### Task 7: 本地冒烟测试

**Files:**
- 无文件变更

- [ ] **Step 1: 安装依赖**

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: 启动服务（设置 API Key）**

```bash
HUYA_API_KEY=testkey uvicorn api:app --host 127.0.0.1 --port 9898
```

- [ ] **Step 3: 测试无 key 请求（应返回 401）**

```bash
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:9898/huya/123456"
```

预期输出: `401`

- [ ] **Step 4: 测试错误 key（应返回 401）**

```bash
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:9898/huya/123456?key=wrong"
```

预期输出: `401`

- [ ] **Step 5: 测试正确 key + 不存在的房间（应返回 404）**

```bash
curl -s "http://127.0.0.1:9898/huya/999999999?key=testkey"
```

预期: 返回 404 JSON `{"error": "Not Found", "message": "Room 999999999 not found"}`

- [ ] **Step 6: 测试正确 key + 真实房间（应返回 302）**

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}" "http://127.0.0.1:9898/huya/123456?key=testkey"
```

预期: `302 https://...flv.huya.com/...`

- [ ] **Step 7: 测试 info 端点**

```bash
curl -s "http://127.0.0.1:9898/huya/123456/info?key=testkey"
```

预期: 返回 JSON `{"room_id": "123456", "status": "online", ...}`

- [ ] **Step 8: 测试 quality 和 cdn 参数**

```bash
curl -s -o /dev/null -w "%{redirect_url}" "http://127.0.0.1:9898/huya/123456?key=testkey&quality=2000&cdn=tx"
```

预期: 重定向 URL 中包含 `&ratio=2000`

- [ ] **Step 9: 停止服务**

按 `Ctrl+C` 停止 uvicorn 进程

---

### Task 8: 更新 README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README.md 中添加 Proxy API 使用说明**

在现有 README 内容末尾追加以下章节：

```markdown
## Proxy API 模式

通过 FastAPI Web 服务将虎牙直播流地址映射为固定 URL，适合在 nxmp 等播放器中使用。

### 快速部署（Docker）

```bash
# 修改 docker-compose.yml 中的 HUYA_API_KEY
docker compose up -d
```

### 手动运行

```bash
pip install -r requirements.txt
HUYA_API_KEY=your_secret uvicorn api:app --host 0.0.0.0 --port 9898
```

### API 端点

| 端点 | 说明 |
|------|------|
| `GET /huya/{room_id}?key=xxx` | 302 重定向到真实 FLV 地址 |
| `GET /huya/{room_id}/info?key=xxx` | 返回房间信息 JSON |

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `key` | 必填 | API Key（环境变量 HUYA_API_KEY） |
| `quality` | 0 | 清晰度: 0=原画, 2000=高清, 4000=超清 |
| `cdn` | 自动 | CDN 线路: tx/ali/hw 等 |

### NS 端使用

在 SD 卡创建 `.strm` 文件：

```
http://服务器IP:9898/huya/123456?key=your_secret
```

或创建 `.m3u` 播放列表：

```
#EXTM3U
#EXTINF:-1,虎牙-房间123456
http://服务器IP:9898/huya/123456?key=your_secret
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Proxy API usage instructions to README"
```
