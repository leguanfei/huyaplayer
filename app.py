#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
虎牙直播桌面播放器（内嵌 mpv）
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chat_layout import (
    CHAT_WIDTH_STEP,
    DEFAULT_CHAT_WIDTH,
    DEFAULT_FONT_SIZE,
    clamp_chat_width,
    step_font_size,
)
from huya import HuyaLive, WUP_UA
from huya_danmaku import HuyaDanmaku

APP_TITLE = "虎牙直播"
BG = "#14151a"
PANEL = "#1e2027"
ENTRY_BG = "#2a2d37"
FG = "#e8e8ea"
FG_DIM = "#9a9da8"
ACCENT = "#f5a623"
ACCENT_DARK = "#c98212"
VIDEO_BG = "#000000"
CHAT_BG = "#15171d"
CHAT_ALT_BG = "#191c23"
CHAT_HOVER_BG = "#242938"
DIVIDER = "#2a2d37"
GRIP_WIDTH = 14
GRIP_MARK = "#565b69"
DRAG_EPSILON = 4
CHAT_DOT_ON = "#4ec97a"
CHAT_DOT_OFF = "#e08585"
CHAT_DOT_IDLE = "#5f626c"
MAX_CHAT_LINES = 600
KEEP_CHAT_LINES = 300

QUALITIES = {"原画": 0, "高清": 2000, "超清": 4000}
CDNS = {"自动": "", "腾讯": "tx", "阿里": "al", "华为": "hw", "网宿": "ws"}
NICK_COLORS = [
    "#e6b667", "#7fc4f0", "#f0938f", "#8fd39a",
    "#c09ae8", "#e8d67a", "#6fd0c4", "#ef9ac4",
    "#a8bcf0", "#d9a877", "#85d9b6", "#d98fb8",
]

CREATE_NO_WINDOW = 0x08000000

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HuyaLive")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def find_mpv() -> str:
    candidates = [
        resource_path("mpv", "mpv.exe"),
        resource_path("vendor", "mpv", "mpv.exe"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "mpv", "mpv.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "mpv", "mpv.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    found = shutil.which("mpv")
    if found:
        return found
    raise FileNotFoundError("未找到 mpv.exe，请确认程序目录中包含 mpv 播放器")


def normalize_room_id(text: str) -> str:
    text = text.strip()
    match = re.search(r"huya\.com/(?:.*/)?([^/?#\s]+)", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    return text.strip().strip("/")


class MpvIPC:
    """通过命名管道向 mpv 发送命令"""

    def __init__(self, pipe_name: str):
        self.pipe_name = pipe_name
        self._lock = threading.Lock()

    def command(self, *args) -> None:
        def send():
            with self._lock:
                try:
                    with open(self.pipe_name, "r+b", buffering=0) as pipe:
                        payload = json.dumps({"command": list(args)}) + "\n"
                        pipe.write(payload.encode("utf-8"))
                        pipe.flush()
                except OSError:
                    pass

        threading.Thread(target=send, daemon=True).start()


class HuyaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x680")
        self.root.minsize(720, 480)
        self.root.configure(bg=BG)

        self.mpv_path = find_mpv()
        self.mpv_proc = None
        self.mpv_ipc = None
        self.mpv_pipe = None
        self.fetching = False
        self.stopping = False
        self.is_fullscreen = False
        self.fetch_token = 0
        self._pipe_counter = 0
        self._result_queue = queue.Queue()
        self.danmaku = None
        self.danmaku_queue = queue.Queue()
        self.current_room = ""
        self._chat_alt = False
        self._chat_count = 0
        self._new_msg_count = 0
        self._hover_line = None
        self._last_system = ""
        self._drag_start_x = 0
        self._drag_start_w = 0
        self._drag_pending = 0
        self._dragging = False
        self._grip_hot = False

        config = load_config()
        self.danmaku_visible = bool(config.get("danmaku_visible", True))
        self._chat_wanted = int(config.get("chat_width", DEFAULT_CHAT_WIDTH))
        self.chat_width = clamp_chat_width(1280, self._chat_wanted)
        self.chat_font_size = step_font_size(
            int(config.get("chat_font_size", DEFAULT_FONT_SIZE)), 0)

        self.room_var = tk.StringVar(value=config.get("last_room", ""))
        self.quality_var = tk.StringVar(value=config.get("quality", "原画"))
        self.cdn_var = tk.StringVar(value=config.get("cdn", "自动"))
        self.status_var = tk.StringVar(value="输入房间号，按回车开始观看")
        self.info_var = tk.StringVar(value="")
        self.chat_count_var = tk.StringVar(value="0")
        if self.quality_var.get() not in QUALITIES:
            self.quality_var.set("原画")
        if self.cdn_var.get() not in CDNS:
            self.cdn_var.set("自动")

        self._build_ui()
        self._set_icon()
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_results)
        self.root.after(1500, self._poll_mpv)
        self.room_entry.focus_set()

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self.top = tk.Frame(self.root, bg=PANEL, padx=14, pady=10)
        self.top.grid(row=0, column=0, sticky="ew")

        tk.Label(self.top, text=APP_TITLE, bg=PANEL, fg=ACCENT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side="left", padx=(0, 18))

        tk.Label(self.top, text="房间号", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 10)).pack(side="left")

        self.room_entry = tk.Entry(
            self.top, textvariable=self.room_var, width=14, bg=ENTRY_BG, fg=FG,
            insertbackground=FG, relief="flat", font=("Microsoft YaHei UI", 11),
        )
        self.room_entry.pack(side="left", padx=(6, 10), ipady=5)
        self.room_entry.bind("<Return>", lambda _e: self.play())

        self.play_btn = self._button(self.top, "观看", self.play, accent=True)
        self.play_btn.pack(side="left")

        self.stop_btn = self._button(self.top, "停止", self.stop)
        self.stop_btn.pack(side="left", padx=(8, 0))

        self._option_menu(self.top, "清晰度", self.quality_var, list(QUALITIES)).pack(
            side="left", padx=(18, 0))
        self._option_menu(self.top, "线路", self.cdn_var, list(CDNS)).pack(
            side="left", padx=(12, 0))

        self.pause_btn = self._button(self.top, "暂停", self.toggle_pause)
        self.pause_btn.pack(side="right", padx=(8, 0))

        self.mute_btn = self._button(self.top, "静音", self.toggle_mute)
        self.mute_btn.pack(side="right", padx=(8, 0))

        self.full_btn = self._button(self.top, "全屏", self.toggle_fullscreen)
        self.full_btn.pack(side="right")

        self.danmaku_btn = self._button(self.top, "弹幕", self.toggle_danmaku, accent=True)
        self.danmaku_btn.pack(side="right", padx=(0, 8))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)

        self.video_frame = tk.Frame(self.body, bg=VIDEO_BG)
        self.video_frame.grid(row=0, column=0, sticky="nsew")

        self.divider = tk.Canvas(
            self.body, width=GRIP_WIDTH, bg=BG,
            highlightthickness=0, cursor="sb_h_double_arrow",
        )
        self.divider.grid(row=0, column=1, sticky="ns")
        self.divider.bind("<Configure>", lambda _e: self._redraw_grip())
        self.divider.bind("<Enter>", self._grip_enter)
        self.divider.bind("<Leave>", self._grip_leave)
        self.divider.bind("<ButtonPress-1>", self._start_resize)
        self.divider.bind("<B1-Motion>", self._on_resize)
        self.divider.bind("<ButtonRelease-1>", self._end_resize)
        self.divider.bind("<Double-ButtonPress-1>", self._reset_chat_width)

        self.chat_frame = tk.Frame(self.body, bg=PANEL, width=self.chat_width)
        self.chat_frame.grid(row=0, column=2, sticky="ns")
        # 面板内子控件走 pack，两级 propagate 都要关掉，否则栏宽被 Text 的默认 80 字撑开
        self.chat_frame.grid_propagate(False)
        self.chat_frame.pack_propagate(False)

        self._build_chat_panel()

        self.hint = tk.Label(
            self.video_frame, text="虎牙直播\n输入房间号开始观看",
            bg=VIDEO_BG, fg="#4a4d57", font=("Microsoft YaHei UI", 18),
            justify="center",
        )
        self.hint.place(relx=0.5, rely=0.5, anchor="center")

        self.status = tk.Frame(self.root, bg=PANEL, padx=14, pady=6)
        self.status.grid(row=2, column=0, sticky="ew")
        tk.Label(self.status, textvariable=self.status_var, bg=PANEL, fg=FG_DIM,
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(self.status, textvariable=self.info_var, bg=PANEL, fg=FG_DIM,
                 anchor="e", font=("Microsoft YaHei UI", 9)).pack(side="right")

        self.root.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _e: self.exit_fullscreen())
        self.root.bind("<Control-f>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<Control-d>", lambda _e: self._shortcut(self.toggle_danmaku))
        self.root.bind("<Control-Left>",
                       lambda _e: self._shortcut(lambda: self._step_chat_width(-CHAT_WIDTH_STEP)))
        self.root.bind("<Control-Right>",
                       lambda _e: self._shortcut(lambda: self._step_chat_width(CHAT_WIDTH_STEP)))

    def _build_chat_panel(self) -> None:
        header = tk.Frame(self.chat_frame, bg=PANEL)
        header.pack(fill="x")

        self.chat_dot = tk.Label(header, text="●", bg=PANEL, fg=CHAT_DOT_IDLE,
                                 font=("Microsoft YaHei UI", 9))
        self.chat_dot.pack(side="left", padx=(12, 4), pady=9)

        tk.Label(header, text="弹幕", bg=PANEL, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Label(header, textvariable=self.chat_count_var, bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(6, 0))

        tk.Button(
            header, text="清屏", command=self._clear_chat, relief="flat", bd=0,
            bg=PANEL, fg=FG_DIM, activebackground=PANEL, activeforeground=ACCENT,
            font=("Microsoft YaHei UI", 9), cursor="hand2", padx=6,
        ).pack(side="right", padx=10)

        tk.Frame(self.chat_frame, bg=DIVIDER, height=1).pack(fill="x")

        wrap = tk.Frame(self.chat_frame, bg=CHAT_BG)
        wrap.pack(fill="both", expand=True)

        self.chat_text = tk.Text(
            wrap, bg=CHAT_BG, fg=FG, bd=0, highlightthickness=0,
            wrap="word", state="disabled", padx=6, pady=6,
            font=("Microsoft YaHei UI", self.chat_font_size), cursor="arrow",
            selectbackground="#33415c", selectforeground=FG,
        )
        scroll = tk.Scrollbar(
            wrap, command=self.chat_text.yview, width=8, bd=0,
            highlightthickness=0, troughcolor=CHAT_BG, bg=ENTRY_BG,
            activebackground=ACCENT_DARK, relief="flat",
        )
        self.chat_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.chat_text.pack(side="left", fill="both", expand=True)

        self.new_msg_btn = tk.Button(
            wrap, text="↓ 新消息", command=self._jump_to_bottom,
            relief="flat", bd=0, bg=ACCENT, fg="#1a1a1a",
            activebackground=ACCENT_DARK, activeforeground="#1a1a1a",
            font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=10, pady=3,
        )

        self.chat_text.tag_configure("row", background=CHAT_BG, spacing1=2, spacing3=2)
        self.chat_text.tag_configure("row_alt", background=CHAT_ALT_BG, spacing1=2, spacing3=2)
        self.chat_text.tag_configure("current", background=CHAT_HOVER_BG)
        self._apply_chat_fonts()

        self.chat_text.bind("<Motion>", self._on_chat_motion)
        self.chat_text.bind("<Leave>", lambda _e: self._clear_hover())
        self.chat_text.bind("<Control-MouseWheel>", self._on_font_wheel)
        self.chat_text.bind("<Button-3>", self._open_chat_menu)
        self._build_chat_menu()

        if self.danmaku_visible:
            self.danmaku_btn.configure(bg=ACCENT, fg="#1a1a1a")
        else:
            self.danmaku_btn.configure(bg=ENTRY_BG, fg=FG)
            self.divider.grid_remove()
            self.chat_frame.grid_remove()

    def _build_chat_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=ENTRY_BG, fg=FG, bd=0,
                       activebackground=ACCENT, activeforeground="#1a1a1a",
                       font=("Microsoft YaHei UI", 10))
        menu.add_command(label="复制选中", command=self._copy_selection)
        menu.add_command(label="复制全部弹幕", command=self._copy_all)
        menu.add_separator()
        menu.add_command(label="放大字号", command=lambda: self._change_font_size(1))
        menu.add_command(label="缩小字号", command=lambda: self._change_font_size(-1))
        menu.add_command(label="复位栏宽", command=lambda: self._reset_chat_width(None))
        menu.add_separator()
        menu.add_command(label="隐藏弹幕栏", command=self.toggle_danmaku)
        self.chat_menu = menu

    def _open_chat_menu(self, event) -> None:
        has_selection = bool(self.chat_text.tag_ranges("sel"))
        self.chat_menu.entryconfigure("复制选中", state=("normal" if has_selection else "disabled"))
        self.chat_menu.tk_popup(event.x_root, event.y_root)

    def _apply_chat_fonts(self) -> None:
        size = self.chat_font_size
        text = self.chat_text
        text.configure(font=("Microsoft YaHei UI", size))
        for index, color in enumerate(NICK_COLORS):
            text.tag_configure(
                f"nick{index}", foreground=color,
                font=("Microsoft YaHei UI", size, "bold"),
            )
        text.tag_configure("time", foreground="#5f626c",
                           font=("Microsoft YaHei UI", max(8, size - 2)))
        text.tag_configure("content", foreground=FG)
        text.tag_configure("system", foreground="#7a7f8d",
                           font=("Microsoft YaHei UI", max(8, size - 1), "italic"),
                           spacing1=5, spacing3=5)

    def _change_font_size(self, delta: int) -> None:
        size = step_font_size(self.chat_font_size, delta)
        if size == self.chat_font_size:
            return
        self.chat_font_size = size
        self._clear_hover()
        self._apply_chat_fonts()
        self._save_settings()
        self._set_status(f"弹幕字号 {size}")

    def _on_font_wheel(self, event) -> str:
        self._change_font_size(1 if event.delta > 0 else -1)
        return "break"

    def _copy_selection(self) -> None:
        try:
            selected = self.chat_text.get("sel.first", "sel.last")
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        self._set_status("已复制选中弹幕")

    def _copy_all(self) -> None:
        content = self.chat_text.get("1.0", "end-1c")
        if not content.strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._set_status(f"已复制 {self._chat_count} 条弹幕")

    def _shortcut(self, action) -> None:
        """焦点在房间输入框时不抢走 Ctrl+方向键 / Ctrl+D 的原生行为。"""
        if self.root.focus_get() is self.room_entry:
            return
        action()

    def _redraw_grip(self) -> None:
        canvas = self.divider
        canvas.delete("all")
        width = canvas.winfo_width() or GRIP_WIDTH
        height = canvas.winfo_height()
        if height <= 1:
            return
        center = width // 2
        middle = height // 2
        active = self._dragging or self._grip_hot
        canvas.create_line(center, 0, center, height,
                           fill=(ACCENT if self._dragging else DIVIDER))
        if active:
            canvas.create_rectangle(center - 5, middle - 11, center + 5, middle + 11,
                                    fill=ACCENT, outline="", width=0)
            mark = "#1a1a1a"
        else:
            mark = GRIP_MARK
        for offset in (-6, 0, 6):
            canvas.create_line(center - 3, middle + offset, center + 3, middle + offset,
                               fill=mark, width=2)

    def _grip_enter(self, _event) -> None:
        self._grip_hot = True
        self._redraw_grip()

    def _grip_leave(self, _event) -> None:
        if not self._dragging:
            self._grip_hot = False
            self._redraw_grip()

    def _start_resize(self, event) -> None:
        self._dragging = True
        self._drag_start_x = event.x_root
        self._drag_start_w = self.chat_frame.winfo_width()
        self._drag_pending = self._drag_start_w
        self._redraw_grip()

    def _on_resize(self, event) -> None:
        target = self._drag_start_w + (self._drag_start_x - event.x_root)
        if abs(target - self._drag_pending) < DRAG_EPSILON:
            return
        self._apply_chat_width(target)
        # 顶到边界时按实际宽度重新锚定，否则反向拖动要先穿过死区才有反应
        self._drag_pending = self.chat_width if self.chat_width != target else target

    def _end_resize(self, _event) -> None:
        self._dragging = False
        self._redraw_grip()
        self._save_settings()

    def _reset_chat_width(self, _event) -> None:
        self._dragging = False
        self._apply_chat_width(DEFAULT_CHAT_WIDTH)
        self._redraw_grip()
        self._save_settings()
        self._set_status(f"弹幕栏宽度已复位为 {self.chat_width}px")

    def _step_chat_width(self, delta: int) -> None:
        if not self.danmaku_visible or self.is_fullscreen:
            return
        self._apply_chat_width(self._chat_wanted + delta)
        self._save_settings()

    def _apply_chat_width(self, width: int, remember: bool = True) -> None:
        if remember:
            self._chat_wanted = width
        body_width = self.body.winfo_width()
        wanted = self._chat_wanted
        # 窗口尚未 realize 时 winfo_width() 返回 1，此时先按期望值摆放
        shown = clamp_chat_width(body_width, wanted) if body_width > 1 else wanted
        if shown == self.chat_width:
            return
        self.chat_width = shown
        self.chat_frame.configure(width=shown)

    def _on_root_configure(self, event) -> None:
        if event.widget is not self.root or self.is_fullscreen or not self.danmaku_visible:
            return
        # Configure 到达时子控件尚未重新排布，直接读 body 会拿到旧宽度
        self.root.after_idle(lambda: self._apply_chat_width(self._chat_wanted, remember=False))

    def _save_settings(self) -> None:
        save_config({
            "chat_width": self._chat_wanted,
            "chat_font_size": self.chat_font_size,
            "danmaku_visible": self.danmaku_visible,
            "quality": self.quality_var.get(),
            "cdn": self.cdn_var.get(),
            "last_room": self.room_var.get(),
        })

    def _button(self, parent, text, command, accent=False):
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=ACCENT if accent else ENTRY_BG, fg="#1a1a1a" if accent else FG,
            activebackground=ACCENT_DARK if accent else "#3a3e4a",
            activeforeground="#1a1a1a" if accent else FG,
            font=("Microsoft YaHei UI", 10), padx=16, pady=5,
            cursor="hand2",
        )

    def _option_menu(self, parent, label, var, values):
        frame = tk.Frame(parent, bg=PANEL)
        tk.Label(frame, text=label, bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 5))
        menu = tk.OptionMenu(frame, var, *values)
        menu.configure(
            bg=ENTRY_BG, fg=FG, activebackground="#3a3e4a", activeforeground=FG,
            relief="flat", bd=0, highlightthickness=0,
            font=("Microsoft YaHei UI", 10), padx=8, pady=3, cursor="hand2",
        )
        menu["menu"].configure(
            bg=ENTRY_BG, fg=FG, activebackground=ACCENT, activeforeground="#1a1a1a",
            font=("Microsoft YaHei UI", 10),
        )
        menu.pack(side="left")
        return frame

    def _set_icon(self) -> None:
        icon = resource_path("assets", "icon.ico")
        if os.path.isfile(icon):
            try:
                self.root.iconbitmap(icon)
            except tk.TclError:
                pass

    def _set_status(self, text: str, info: str = "") -> None:
        self.status_var.set(text)
        self.info_var.set(info)

    def play(self) -> None:
        if self.fetching:
            return

        room_id = normalize_room_id(self.room_var.get())
        if not room_id:
            self._set_status("请输入房间号")
            self.room_entry.focus_set()
            return

        self.room_var.set(room_id)
        self._save_settings()
        self.fetching = True
        self.fetch_token += 1
        token = self.fetch_token
        self.play_btn.configure(state="disabled", text="获取中…")
        self._set_status(f"正在获取房间 {room_id} 的直播流…")
        self.hint.configure(text="正在获取直播流…")

        quality = QUALITIES.get(self.quality_var.get(), 0)
        cdn = CDNS.get(self.cdn_var.get(), "")

        threading.Thread(
            target=self._resolve_worker,
            args=(token, room_id, quality, cdn),
            daemon=True,
        ).start()

    def _resolve_worker(self, token: int, room_id: str, quality: int, cdn: str) -> None:
        try:
            api = HuyaLive(room_id)
            profile = api.get_room_profile()
            if not profile.get("live"):
                raise RuntimeError(profile.get("message", "直播间未开播"))

            urls = api.get_stream_urls(profile)
            if not urls:
                raise RuntimeError("没有可用的直播流")

            if cdn:
                matched = [u for u in urls if u["cdn"] == cdn]
                urls = matched or urls

            urls.sort(key=lambda u: u["priority"], reverse=True)
            url = urls[0]["url"]
            if quality > 0:
                url += f"&ratio={quality}"

            self._result_queue.put(("ok", token, room_id, url, profile))
        except Exception as exc:
            self._result_queue.put(("error", token, str(exc)))

    def _poll_results(self) -> None:
        self._drain_danmaku()
        try:
            while True:
                result = self._result_queue.get_nowait()
                if result[1] != self.fetch_token:
                    continue

                self.fetching = False
                if result[0] == "ok":
                    _, _, room_id, url, profile = result
                    try:
                        self._start_mpv(url)
                    except Exception as exc:
                        self._set_status(f"播放器启动失败：{exc}")
                        messagebox.showerror(APP_TITLE, f"播放器启动失败：{exc}", parent=self.root)
                        continue
                    artist = profile.get("artist") or room_id
                    title = profile.get("room_title") or ""
                    self._set_status(f"正在播放：{artist}", title)
                    self.hint.place_forget()
                    self.current_room = room_id
                    self._clear_chat()
                    self._start_danmaku(room_id)
                else:
                    _, _, message = result
                    self._set_status(f"错误：{message}")
                    self.hint.place(relx=0.5, rely=0.5, anchor="center")
                    self.hint.configure(text="虎牙直播\n输入房间号开始观看")
                    messagebox.showerror(APP_TITLE, message, parent=self.root)
        except queue.Empty:
            pass

        if not self.fetching:
            self.play_btn.configure(state="normal", text="观看")
        self.root.after(100, self._poll_results)

    def _start_mpv(self, url: str) -> None:
        self._stop_mpv()
        self.root.update_idletasks()

        self._pipe_counter += 1
        self.mpv_pipe = rf"\\.\pipe\huya_live_{os.getpid()}_{self._pipe_counter}"
        self.mpv_ipc = MpvIPC(self.mpv_pipe)

        wid = self.video_frame.winfo_id()
        args = [
            self.mpv_path,
            f"--wid={wid}",
            "--force-window=yes",
            "--no-border",
            "--no-config",
            "--no-osc",
            "--no-osd-bar",
            "--osd-level=0",
            "--hwdec=auto-safe",
            "--cache=yes",
            "--cache-secs=30",
            "--demuxer-readahead-secs=10",
            "--demuxer-max-bytes=64MiB",
            "--demuxer-max-back-bytes=32MiB",
            "--network-timeout=10",
            "--keep-open=no",
            "--no-input-terminal",
            "--input-ipc-server=" + self.mpv_pipe,
            "--user-agent=" + WUP_UA,
            "--referrer=https://www.huya.com/",
            "--audio-client-name=HuyaLive",
            "--title=" + APP_TITLE,
            "--msg-level=all=error",
            url,
        ]

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.stopping = False
        self.mpv_proc = subprocess.Popen(
            args,
            cwd=os.path.dirname(self.mpv_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.pause_btn.configure(text="暂停")
        self.mute_btn.configure(text="静音")

    def _poll_mpv(self) -> None:
        if self.mpv_proc is not None and not self.stopping:
            code = self.mpv_proc.poll()
            if code is not None:
                self.mpv_proc = None
                self._set_status("播放已结束，可重新点击「观看」")
        self.root.after(1500, self._poll_mpv)

    def _stop_mpv(self) -> None:
        proc = self.mpv_proc
        if proc is None:
            return

        self.stopping = True
        self.mpv_proc = None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
        self.stopping = False

    def _start_danmaku(self, room_id: str) -> None:
        self._stop_danmaku()
        client = HuyaDanmaku(room_id)
        client.on_message = lambda name, content: self.danmaku_queue.put((name, content))
        client.on_status = lambda text: self.danmaku_queue.put(("__status__", text))
        self.danmaku = client
        client.start()

    def _stop_danmaku(self) -> None:
        client = self.danmaku
        self.danmaku = None
        if client is not None:
            client.stop()

    def _clear_chat(self) -> None:
        self._chat_count = 0
        self._chat_alt = False
        self._last_system = ""
        self.chat_count_var.set("0")
        self._set_dot(CHAT_DOT_IDLE)
        self._hide_new_msg()
        self._clear_hover()
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")

    def _drain_danmaku(self) -> None:
        try:
            for _ in range(50):
                name, content = self.danmaku_queue.get_nowait()
                if name == "__status__":
                    self._append_status(content)
                    continue
                self._append_danmaku(name, content)
        except queue.Empty:
            pass

    def _append_status(self, message: str) -> None:
        connected = "已连接" in message
        self._set_dot(CHAT_DOT_ON if connected else CHAT_DOT_OFF)
        if not connected:
            self.info_var.set(message)
        if message == self._last_system:
            return
        self._last_system = message
        self._append_segments([(f"{message}\n", ("system",))])

    def _append_danmaku(self, name: str, content: str) -> None:
        nick = f"nick{sum(map(ord, name)) % len(NICK_COLORS)}"
        stamp = time.strftime("%H:%M")
        self._append_segments([
            (f"{stamp}  ", ("time",)),
            ("● ", (nick,)),
            (f"{name}  ", (nick,)),
            (f"{content}\n", ("content",)),
        ])
        self._chat_count += 1
        self.chat_count_var.set(str(self._chat_count))

    def _append_segments(self, segments) -> None:
        """插入一条消息：负责斑马底色、贴底才跟随、超长裁剪。"""
        text = self.chat_text
        at_bottom = self._is_at_bottom()
        anchor = self._top_visible_line()
        row = "row_alt" if self._chat_alt else "row"
        self._chat_alt = not self._chat_alt

        text.configure(state="normal")
        for content, tags in segments:
            text.insert("end", content, (row,) + tuple(tags))
        cut = self._trim_history()
        text.configure(state="disabled")

        if at_bottom:
            text.see("end")
            return
        # yview 按比例锚定，追加与裁剪都会让画面漂移，按像素复位可见首行
        self._restore_top_line(anchor - cut)
        self._count_new_message()

    def _set_dot(self, color: str) -> None:
        self.chat_dot.configure(fg=color)

    def _is_at_bottom(self) -> bool:
        text = self.chat_text
        # 尚未布局（或面板被隐藏）时 yview 是未初始化的小数，不能当成用户上翻
        if not text.winfo_ismapped() or text.winfo_height() <= 1:
            return True
        return text.yview()[1] >= 0.995

    def _display_line_count(self) -> int:
        return int(self.chat_text.index("end-1c").split(".")[0])

    def _top_visible_line(self) -> int:
        return int(self.chat_text.index("@0,0").split(".")[0])

    def _restore_top_line(self, line: int) -> None:
        line = max(1, line)
        text = self.chat_text
        if self._top_visible_line() == line:
            return
        info = text.dlineinfo(f"{line}.0")
        if info is None:
            return
        text.yview_scroll(info[1], "pixels")

    def _trim_history(self) -> int:
        total = self._display_line_count()
        if total <= MAX_CHAT_LINES:
            return 0
        cut = total - KEEP_CHAT_LINES
        self.chat_text.delete("1.0", f"{cut + 1}.0")
        self._clear_hover()
        return cut

    def _count_new_message(self) -> None:
        self._new_msg_count += 1
        self.new_msg_btn.configure(text=f"↓ 新消息 {self._new_msg_count} 条")
        self.new_msg_btn.place(relx=0.5, rely=1.0, anchor="s", y=-12)

    def _hide_new_msg(self) -> None:
        self._new_msg_count = 0
        self.new_msg_btn.place_forget()

    def _jump_to_bottom(self) -> None:
        self._hide_new_msg()
        self.chat_text.see("end")

    def _on_chat_motion(self, event) -> None:
        line = self.chat_text.index(f"@{event.x},{event.y}").split(".")[0]
        if line == self._hover_line:
            return
        self._clear_hover()
        self._hover_line = line
        self.chat_text.tag_add("current", f"{line}.0", f"{line}.end")
        self.chat_text.tag_raise("current")

    def _clear_hover(self) -> None:
        if self._hover_line is None:
            return
        line = self._hover_line
        self._hover_line = None
        self.chat_text.tag_remove("current", f"{line}.0", f"{line}.end")

    def toggle_danmaku(self) -> None:
        self.danmaku_visible = not self.danmaku_visible
        if self.danmaku_visible:
            self._show_chat_panel()
            self.danmaku_btn.configure(bg=ACCENT, fg="#1a1a1a")
        else:
            self._hide_chat_panel()
            self.danmaku_btn.configure(bg=ENTRY_BG, fg=FG)
        self._save_settings()

    def _show_chat_panel(self) -> None:
        self.divider.grid()
        self.chat_frame.grid()
        # 隐藏期间窗口可能被缩放过，按当前宽度重新收敛
        self._apply_chat_width(self._chat_wanted, remember=False)
        self._redraw_grip()

    def _hide_chat_panel(self) -> None:
        self.divider.grid_remove()
        self.chat_frame.grid_remove()

    def stop(self) -> None:
        self.fetch_token += 1
        self.fetching = False
        self.play_btn.configure(state="normal", text="观看")
        self._stop_mpv()
        self._stop_danmaku()
        self._clear_chat()
        self._set_status("已停止")
        self.pause_btn.configure(text="暂停")
        self.mute_btn.configure(text="静音")
        self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.hint.configure(text="虎牙直播\n输入房间号开始观看")

    def toggle_pause(self) -> None:
        if self.mpv_ipc is None or self.mpv_proc is None:
            return
        self.mpv_ipc.command("cycle", "pause")
        self.pause_btn.configure(
            text="继续" if self.pause_btn.cget("text") == "暂停" else "暂停"
        )

    def toggle_mute(self) -> None:
        if self.mpv_ipc is None or self.mpv_proc is None:
            return
        self.mpv_ipc.command("cycle", "mute")
        self.mute_btn.configure(
            text="取消静音" if self.mute_btn.cget("text") == "静音" else "静音"
        )

    def toggle_fullscreen(self) -> None:
        if self.is_fullscreen:
            self.exit_fullscreen()
            return

        self.is_fullscreen = True
        self.top.grid_remove()
        self.status.grid_remove()
        self._hide_chat_panel()
        self.root.attributes("-fullscreen", True)
        self.root.focus_force()

    def exit_fullscreen(self) -> None:
        if not self.is_fullscreen:
            return
        self.is_fullscreen = False
        self.root.attributes("-fullscreen", False)
        self.top.grid()
        self.status.grid()
        if self.danmaku_visible:
            self._show_chat_panel()
        self.root.focus_force()

    def _on_close(self) -> None:
        self._save_settings()
        self._stop_danmaku()
        self._stop_mpv()
        self.root.destroy()


def main() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"无法启动图形界面: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        app = HuyaApp(root)
        if len(sys.argv) > 1:
            app.room_var.set(normalize_room_id(sys.argv[1]))
            root.after(300, app.play)
    except FileNotFoundError as exc:
        messagebox.showerror(APP_TITLE, str(exc))
        root.destroy()
        sys.exit(1)

    root.mainloop()


if __name__ == "__main__":
    main()
