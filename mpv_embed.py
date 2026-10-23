#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mpv 进程与 JSON IPC 封装。

不 import PySide6：进程、传输层、调度器都可注入，重连退避因此能脱离 GUI 单测。
"""

import json
import os
import queue
import subprocess
import threading
import time

BACKOFF_MS = (2000, 4000, 8000, 16000, 30000)
CREATE_NO_WINDOW = 0x08000000


class PipeTransport:
    """命名管道传输。

    Windows 命名管道上「同一条句柄既被读线程 readline 又被写方 write」会写失败
    （EINVAL），所以命令每次开新句柄（旧版验证过的做法），get_property 用独立
    句柄写+读响应，事件单独走一条常驻读句柄。
    """

    def __init__(self, pipe_name: str):
        self.pipe_name = pipe_name
        self._lines: "queue.Queue[bytes]" = queue.Queue()
        self._reader = None
        self._reader_conn = None
        self._closed = False

    def _open(self):
        for _ in range(50):
            if self._closed:
                raise OSError("transport closed")
            try:
                return open(self.pipe_name, "r+b", buffering=0)
            except OSError:
                time.sleep(0.1)
        raise OSError(f"无法连接 mpv 管道 {self.pipe_name}")

    def _ensure_reader(self) -> None:
        if self._reader is not None:
            return
        self._reader_conn = self._open()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                line = self._reader_conn.readline()
            except (OSError, ValueError):
                return
            if not line:
                time.sleep(0.2)
                continue
            self._lines.put(line)

    def write(self, data: bytes) -> None:
        if self._closed:
            return
        conn = self._open()
        try:
            conn.write(data)
            conn.flush()
        except OSError:
            pass
        finally:
            conn.close()

    def request(self, data: bytes) -> bytes:
        if self._closed:
            return b""
        conn = self._open()
        try:
            conn.write(data)
            conn.flush()
            return conn.readline()
        except OSError:
            return b""
        finally:
            conn.close()

    def ready(self) -> bool:
        if self._reader is None:
            try:
                self._ensure_reader()
            except OSError:
                return False
        return not self._lines.empty()

    def readline(self) -> bytes:
        try:
            return self._lines.get_nowait()
        except queue.Empty:
            return b""

    def close(self) -> None:
        self._closed = True
        conn, self._reader_conn = self._reader_conn, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


class MpvController:
    def __init__(self, mpv_path, spawner=None, transport_factory=None,
                 scheduler=None, on_event=None):
        self.mpv_path = mpv_path
        self._spawner = spawner or self._default_spawn
        self._transport_factory = transport_factory or PipeTransport
        self._scheduler = scheduler or self._default_schedule
        self._on_event = on_event or (lambda _event: None)
        self._proc = None
        self._transport = None
        self._hwnd = None
        self._extra_args = ()
        self._last_url = None
        self._last_headers = {}
        self._attempt = 0
        self._stopped = True

    @staticmethod
    def _default_spawn(args):
        return subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)

    @staticmethod
    def _default_schedule(delay_ms, fn):
        threading.Timer(delay_ms / 1000.0, fn).start()

    def start(self, hwnd: int, extra_args=()) -> None:
        self._kill()
        self._hwnd = hwnd
        self._extra_args = tuple(extra_args)
        self._stopped = False
        self._spawn()

    def _kill(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _spawn(self) -> None:
        pipe = rf"\\.\pipe\huya_live_{os.getpid()}_{id(self) % 100000}"
        args = [
            self.mpv_path,
            f"--wid={self._hwnd}",
            f"--input-ipc-server={pipe}",
            "--hwdec=auto-safe",
            "--osc=no",
            "--osd-bar=no",
            "--idle=yes",
            "--really-quiet",
            *self._extra_args,
        ]
        if self._transport is not None:
            self._transport.close()
        self._transport = self._transport_factory(pipe)
        self._proc = self._spawner(args)

    def command(self, *args) -> None:
        if self._transport is None:
            return
        payload = json.dumps({"command": list(args)}) + "\n"
        self._transport.write(payload.encode("utf-8"))

    def set_property(self, name: str, value) -> None:
        self.command("set", name, value)

    def get_property(self, name: str):
        if self._transport is None:
            return None
        payload = json.dumps({"command": ["get_property", name]}) + "\n"
        line = self._transport.request(payload.encode("utf-8"))
        try:
            return json.loads(line.decode("utf-8")).get("data")
        except ValueError:
            return None

    def load(self, url: str, headers=None) -> None:
        self._last_url = url
        self._last_headers = dict(headers or {})
        fields = [f"{key}: {value}" for key, value in self._last_headers.items()]
        self.command("set", "http-header-fields", fields)
        self.command("loadfile", url, "replace")

    def set_volume(self, volume: int) -> None:
        self.command("set", "volume", volume)

    def set_mute(self, muted: bool) -> None:
        self.command("set", "mute", muted)

    def set_pause(self, paused: bool) -> None:
        self.command("set", "pause", paused)

    def pump_events(self) -> None:
        if self._transport is None:
            return
        while self._transport.ready():
            line = self._transport.readline()
            if not line:
                break
            try:
                event = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if "event" not in event:
                continue
            if event["event"] == "playback-restart":
                self._attempt = 0
            self._on_event(event)

    def poll(self) -> None:
        if self._stopped or self._proc is None:
            return
        if self._proc.poll() is None:
            return
        delay = BACKOFF_MS[min(self._attempt, len(BACKOFF_MS) - 1)]
        self._attempt += 1
        self._scheduler(delay, self._reconnect)

    def _reconnect(self) -> None:
        if self._stopped:
            return
        self._spawn()
        if self._last_url:
            self.load(self._last_url, self._last_headers)

    def stop(self) -> None:
        self._stopped = True
        if self._transport is not None:
            self.command("quit")
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
        if self._transport is not None:
            self._transport.close()
            self._transport = None
