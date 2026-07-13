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
