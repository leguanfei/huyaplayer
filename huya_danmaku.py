#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
虎牙直播弹幕客户端

通过 wss://cdnws.api.huya.com 使用 TARS 协议订阅直播间弹幕，无需开发者账号。
"""

import os
import re
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tars import tarscore
from websockets.sync.client import connect

DANMAKU_WSS_URL = "wss://cdnws.api.huya.com/"
HEARTBEAT_INTERVAL = 60
RECONNECT_DELAY = 3

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/79.0.3945.88 Mobile Safari/537.36"
)

HEARTBEAT = (
    b'\x00\x03\x1d\x00\x00\x69\x00\x00\x00\x69\x10\x03\x2c\x3c\x4c\x56\x08\x6f\x6e\x6c\x69\x6e\x65\x75'
    b'\x69\x66\x0f\x4f\x6e\x55\x73\x65\x72\x48\x65\x61\x72\x74\x42\x65\x61\x74\x7d\x00\x00\x3c\x08\x00'
    b'\x01\x06\x04\x74\x52\x65\x71\x1d\x00\x00\x2f\x0a\x0a\x0c\x16\x00\x26\x00\x36\x07\x61\x64\x72\x5f'
    b'\x77\x61\x70\x46\x00\x0b\x12\x03\xae\xf0\x0f\x22\x03\xae\xf0\x0f\x3c\x42\x6d\x52\x02\x60\x5c\x60'
    b'\x01\x7c\x82\x00\x0b\xb0\x1f\x9c\xac\x0b\x8c\x98\x0c\xa8\x0c '
)


class _User(tarscore.struct):
    @staticmethod
    def writeTo(oos, value):
        pass

    @staticmethod
    def readFrom(ios):
        name = ios.read(tarscore.string, 2, False)
        if isinstance(name, bytes):
            name = name.decode("utf-8", "ignore")
        return name


class HuyaDanmaku:
    """虎牙弹幕客户端，后台线程运行，通过回调返回弹幕"""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.on_message = None
        self.on_status = None
        self._stop = threading.Event()
        self._thread = None
        self._ws = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _emit(self, callback, *args) -> None:
        if callback is not None:
            try:
                callback(*args)
            except Exception:
                pass

    def _fetch_ids(self) -> tuple:
        resp = requests.get(
            f"https://m.huya.com/{self.room_id}",
            headers={"User-Agent": MOBILE_UA},
            timeout=10,
        )
        resp.raise_for_status()
        page = resp.text

        yyid = re.search(r'lYyid":([0-9]+)', page)
        channel = re.search(r'lChannelId":([0-9]+)', page)
        sub_channel = re.search(r'lSubChannelId":([0-9]+)', page)
        if not yyid or not channel or not sub_channel:
            raise RuntimeError("无法获取弹幕参数，可能未开播")
        return int(yyid.group(1)), int(channel.group(1)), int(sub_channel.group(1))

    @staticmethod
    def _build_join(ayyuid: int, tid: int, sid: int) -> bytes:
        oos = tarscore.TarsOutputStream()
        oos.write(tarscore.int64, 0, ayyuid)
        oos.write(tarscore.boolean, 1, True)
        oos.write(tarscore.string, 2, "")
        oos.write(tarscore.string, 3, "")
        oos.write(tarscore.int64, 4, tid)
        oos.write(tarscore.int64, 5, sid)
        oos.write(tarscore.int64, 6, 0)
        oos.write(tarscore.int64, 7, 0)

        wscmd = tarscore.TarsOutputStream()
        wscmd.write(tarscore.int32, 0, 1)
        wscmd.write(tarscore.bytes, 1, oos.getBuffer())
        return bytes(wscmd.getBuffer())

    @staticmethod
    def _decode(data: bytes):
        ios = tarscore.TarsInputStream(data)
        if ios.read(tarscore.int32, 0, False) != 7:
            return None

        push = tarscore.TarsInputStream(ios.read(tarscore.bytes, 1, False))
        if push.read(tarscore.int64, 1, False) != 1400:
            return None

        msg = tarscore.TarsInputStream(push.read(tarscore.bytes, 2, False))
        name = msg.read(_User, 0, False)
        content = msg.read(tarscore.string, 3, False)
        if isinstance(content, bytes):
            content = content.decode("utf-8", "ignore")
        return name, content

    def _run(self) -> None:
        ayyuid = channel = sub_channel = None
        while not self._stop.is_set():
            if ayyuid is None:
                try:
                    ayyuid, channel, sub_channel = self._fetch_ids()
                except Exception as exc:
                    self._emit(self.on_status, f"弹幕连接失败：{exc}")
                    if self._stop.wait(5):
                        break
                    continue

            try:
                self._connect_once(ayyuid, channel, sub_channel)
            except Exception as exc:
                if not self._stop.is_set():
                    self._emit(self.on_status, f"弹幕已断开：{exc}")
            if self._stop.wait(RECONNECT_DELAY):
                break

    def _connect_once(self, ayyuid: int, tid: int, sid: int) -> None:
        with connect(DANMAKU_WSS_URL, max_size=None, open_timeout=10) as ws:
            self._ws = ws
            ws.send(self._build_join(ayyuid, tid, sid))
            self._emit(self.on_status, "弹幕已连接")

            last_heartbeat = time.time()
            while not self._stop.is_set():
                if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                    ws.send(HEARTBEAT)
                    last_heartbeat = time.time()
                try:
                    frame = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if isinstance(frame, bytes):
                    decoded = self._decode(frame)
                    if decoded:
                        self._emit(self.on_message, decoded[0], decoded[1])
        self._ws = None
