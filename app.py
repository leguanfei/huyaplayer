#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""虎牙直播桌面播放器（PySide6 外壳 + 内嵌 mpv）。

取流协议在 huya.py，弹幕在 huya_danmaku.py，mpv 进程与 IPC 在 mpv_embed.py，
设计令牌在 theme.py，侧栏宽度数学在 chat_layout.py。本文件只做组装。
"""

import json
import os
import queue
import re
import shutil
import sys
import threading

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtCore import QPropertyAnimation
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QMenu, QMessageBox,
                               QPushButton, QSlider, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chat_layout import (CHAT_WIDTH_STEP, DEFAULT_CHAT_WIDTH, DEFAULT_FONT_SIZE,
                         clamp_chat_width, step_font_size)
from chat_model import ChatModel
from chat_panel import ChatDelegate, ChatDock
from huya import HuyaLive, WUP_UA
from huya_danmaku import HuyaDanmaku
from mpv_embed import MpvController
from theme import THEMES, qss

APP_TITLE = "虎牙直播"
QUALITIES = {"原画": 0, "高清": 2000, "超清": 4000}
CDNS = {"自动": "", "腾讯": "tx", "阿里": "al", "华为": "hw", "网宿": "ws"}

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HuyaLive")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

MPV_EXTRA_ARGS = (
    "--force-window=yes", "--no-border", "--no-config", "--osd-level=0",
    # flip-model 交换链会被 DWM 放到独立平面，盖住我们的 owned 浮层；关掉它
    # 才能让控制条压在画面上（spike 只验证了 idle 黑窗，真播放时才暴露）。
    "--d3d11-flip=no", "--angle-flip=no",
    "--cache=yes", "--cache-secs=30", "--demuxer-readahead-secs=10",
    "--demuxer-max-bytes=64MiB", "--demuxer-max-back-bytes=32MiB",
    "--network-timeout=10", "--keep-open=no", "--no-input-terminal",
    "--audio-client-name=HuyaLive", "--msg-level=all=error",
)

TITLEBAR_H = 26
OVERLAY_H = 56
RESIZE_EDGE = 6


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


def normalize_room_id(text: str) -> str:
    text = text.strip()
    match = re.search(r"huya\.com/(?:.*/)?([^/?#\s]+)", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    return text.strip().strip("/")


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


class OwnedPopup(QWidget):
    """owner 为主窗的无边框透明浮层。

    mpv 用 --wid 挂进来的是一个带 WS_EX_TOPMOST 的外来子窗口，普通 Qt 子控件
    画不过它（spike 已验证 Z 序与 ex-style 都压不住）；owned 弹出窗口合成在
    owner 整棵子树之上，是唯一稳的叠放方式。
    """

    def __init__(self, host: QWidget):
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self._host = host
        self.wanted = False
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = None

    def target_rect(self) -> QRect:
        return self._host.rect()

    def sync(self) -> None:
        rect = self.target_rect()
        origin = self._host.mapToGlobal(rect.topLeft())
        self.setGeometry(origin.x(), origin.y(), rect.width(), rect.height())

    def reveal(self, ms_in: int) -> None:
        self.wanted = True
        self.sync()
        if not self.isVisible():
            self.show()
        self.fade_to(1.0, ms_in)

    def vanish(self, ms_out: int) -> None:
        self.wanted = False
        if not self.isVisible():
            return
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(ms_out)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.hide)
        self._fade = anim
        anim.start()

    def fade_to(self, value: float, ms: int) -> None:
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(value)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade = anim
        anim.start()


class TitleBar(QWidget):
    def __init__(self, window: "PlayerWindow"):
        super().__init__(window)
        self.setObjectName("titlebar")
        self.setFixedHeight(TITLEBAR_H)
        self._window = window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(8)

        dot = QLabel(self)
        dot.setObjectName("logoDot")
        dot.setFixedSize(10, 10)
        layout.addWidget(dot)

        self.title = QLabel(APP_TITLE, self)
        layout.addWidget(self.title, 1)

        for name, glyph, slot in (
            ("themeBtn", "◐", window.toggle_theme),
            ("minBtn", "–", window.showMinimized),
            ("maxBtn", "□", window.toggle_maximize),
            ("closeBtn", "×", window.close),
        ):
            btn = QPushButton(glyph, self)
            btn.setObjectName("iconBtn")
            btn.setFixedSize(34, TITLEBAR_H - 4)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.window().isMaximized():
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._window.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class VideoHost(QWidget):
    def __init__(self, window: "PlayerWindow"):
        super().__init__(window)
        self.setObjectName("videoHost")
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMouseTracking(True)
        self._window = window

    def mouseMoveEvent(self, event):
        if self._window.current_room:
            self._window.overlay.reveal()
        super().mouseMoveEvent(event)


class IdlePage(OwnedPopup):
    def __init__(self, host: QWidget, window: "PlayerWindow"):
        super().__init__(host)
        self.setObjectName("idlePage")
        self._window = window

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(24, 24, 24, 24)
        wrap.addStretch(3)

        title = QLabel("虎牙直播", self)
        title.setObjectName("idleTitle")
        title.setAlignment(Qt.AlignCenter)
        wrap.addWidget(title)

        self.room = QLineEdit(self)
        self.room.setObjectName("idleRoom")
        self.room.setPlaceholderText("输入房间号或直播间链接")
        self.room.setAlignment(Qt.AlignCenter)
        self.room.setFixedWidth(420)
        self.room.returnPressed.connect(window.play)
        wrap.addWidget(self.room, 0, Qt.AlignCenter)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        play = QPushButton("观看", self)
        play.setProperty("accent", True)
        play.setFixedSize(120, 40)
        play.clicked.connect(window.play)
        row.addWidget(play)
        self.quality = QComboBox(self)
        self.quality.addItems(list(QUALITIES))
        self.cdn = QComboBox(self)
        self.cdn.addItems(list(CDNS))
        for combo in (self.quality, self.cdn):
            combo.setFixedHeight(40)
            row.addWidget(combo)
        row.addStretch(1)
        wrap.addLayout(row)

        self.last_room = QPushButton(self)
        self.last_room.setObjectName("iconBtn")
        self.last_room.clicked.connect(self._use_last_room)
        wrap.addWidget(self.last_room, 0, Qt.AlignCenter)

        hint = QLabel("回车开始观看 · F11 全屏 · 空格暂停 · M 静音", self)
        hint.setObjectName("idleHint")
        hint.setAlignment(Qt.AlignCenter)
        wrap.addWidget(hint)
        wrap.addStretch(4)

    def refresh(self, config: dict) -> None:
        self.room.setText(config.get("last_room", ""))
        quality = config.get("quality", "原画")
        cdn = config.get("cdn", "自动")
        self.quality.setCurrentText(quality if quality in QUALITIES else "原画")
        self.cdn.setCurrentText(cdn if cdn in CDNS else "自动")
        last = config.get("last_room", "")
        self.last_room.setText(f"上次观看 {last}" if last else "")
        self.last_room.setVisible(bool(last))

    def _use_last_room(self) -> None:
        self.room.setText(self.last_room.text().replace("上次观看 ", ""))
        self._window.play()


class OverlayBar(OwnedPopup):
    def __init__(self, host: QWidget, window: "PlayerWindow"):
        super().__init__(host)
        self.setObjectName("overlayBar")
        self._window = window
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        self.pause_btn = QPushButton("⏸", self)
        self.pause_btn.setObjectName("iconBtn")
        self.pause_btn.setFixedSize(36, 36)
        self.pause_btn.clicked.connect(window.toggle_pause)
        layout.addWidget(self.pause_btn)

        stop = QPushButton("■", self)
        stop.setObjectName("iconBtn")
        stop.setFixedSize(36, 36)
        stop.clicked.connect(window.stop)
        layout.addWidget(stop)

        self.volume = QSlider(Qt.Horizontal, self)
        self.volume.setRange(0, 130)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(window.set_volume)
        layout.addWidget(self.volume)
        self.volume_label = QLabel("100%", self)
        self.volume_label.setFixedWidth(42)
        layout.addWidget(self.volume_label)

        layout.addSpacing(8)
        self.quality = QComboBox(self)
        self.quality.addItems(list(QUALITIES))
        self.quality.currentTextChanged.connect(window.change_quality)
        layout.addWidget(self.quality)
        self.cdn = QComboBox(self)
        self.cdn.addItems(list(CDNS))
        self.cdn.currentTextChanged.connect(window.change_cdn)
        layout.addWidget(self.cdn)

        self.status = QLabel("", self)
        layout.addWidget(self.status, 1)

        self.full_btn = QPushButton("⛶", self)
        self.full_btn.setObjectName("iconBtn")
        self.full_btn.setFixedSize(36, 36)
        self.full_btn.clicked.connect(window.toggle_fullscreen)
        layout.addWidget(self.full_btn)

    def target_rect(self) -> QRect:
        rect = self._host.rect()
        return QRect(0, rect.height() - OVERLAY_H, rect.width(), OVERLAY_H)

    def paintEvent(self, _event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.45, QColor(0, 0, 0, 150))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 210))
        painter.fillRect(self.rect(), gradient)

    def reveal(self) -> None:
        super().reveal(self._window.theme["durations"]["fade_in"])
        self.schedule_hide()

    def keep(self) -> None:
        self._hide_timer.stop()

    def schedule_hide(self) -> None:
        self._hide_timer.start(self._window.theme["durations"]["idle_hide"])

    def _auto_hide(self) -> None:
        if self.underMouse():
            self.schedule_hide()
            return
        self.vanish(self._window.theme["durations"]["fade_out"])

    def enterEvent(self, event):
        self.keep()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.schedule_hide()
        super().leaveEvent(event)


class ChatOverlay(OwnedPopup):
    """全屏时弹幕栏的形态：半透明浮层贴画面右缘，与停靠栏共用一个 model。"""

    def __init__(self, host: QWidget, window: "PlayerWindow"):
        super().__init__(host)
        self.setObjectName("chatOverlay")
        self._window = window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = QListView(self)
        self.view.setObjectName("chatView")
        self.view.setModel(window.chat_model)
        self.view.setItemDelegate(ChatDelegate(self))
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.view)
        window.chat_model.rowsInserted.connect(self._follow)

    def theme(self):
        return self._window.theme

    def font_size(self):
        return self._window.chat_font_size

    def ui_family(self):
        return self._window.theme["fonts"]["ui"]

    def target_rect(self) -> QRect:
        rect = self._host.rect()
        width = clamp_chat_width(rect.width(), self._window._chat_wanted)
        return QRect(rect.width() - width, 0, width, rect.height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        color = QColor(self.theme()["colors"]["panel_solid"])
        color.setAlpha(225)
        painter.fillRect(self.rect(), color)

    def _follow(self, *_args):
        self.view.scrollToBottom()


SHORTCUTS = (
    ("F11 / Ctrl+F", "切换全屏"),
    ("Esc", "退出全屏"),
    ("空格", "暂停 / 继续"),
    ("M", "静音"),
    ("↑ / ↓", "音量加减"),
    ("Ctrl+D", "显示 / 隐藏弹幕栏"),
    ("Ctrl+← / →", "弹幕栏宽度"),
    ("Ctrl+滚轮", "弹幕字号"),
    ("F1", "本面板"),
)


class ShortcutSheet(QDialog):
    def __init__(self, window: "PlayerWindow"):
        super().__init__(window, Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("shortcutSheet")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        title = QLabel("快捷键", self)
        title.setObjectName("chatTitle")
        layout.addWidget(title)
        for keys, desc in SHORTCUTS:
            row = QHBoxLayout()
            row.setSpacing(12)
            key = QLabel(keys, self)
            key.setObjectName("shortcutKey")
            key.setMinimumWidth(96)
            row.addWidget(key)
            label = QLabel(desc, self)
            label.setObjectName("shortcutDesc")
            row.addWidget(label, 1)
            layout.addLayout(row)

    def show_centered(self, window: QWidget) -> None:
        self.adjustSize()
        self.move(window.x() + (window.width() - self.width()) // 2,
                  window.y() + (window.height() - self.height()) // 2)
        self.show()


class PlayerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMinimumSize(720, 480)
        self.resize(1080, 680)
        self.setWindowTitle(APP_TITLE)

        self.config = load_config()
        name = self.config.get("theme", "dark")
        self.theme = THEMES[name if name in THEMES else "dark"]

        self.fetching = False
        self.fetch_token = 0
        self.current_room = ""
        self._artist = ""
        self._result_queue: "queue.Queue" = queue.Queue()
        self._paused = False
        self._muted = False

        self.chat_model = ChatModel(
            enter_ms=self.theme["durations"]["enter"],
            anim_tail=self.theme["chat_anim_tail"])
        self.danmaku_visible = bool(self.config.get("danmaku_visible", True))
        self.chat_font_size = step_font_size(
            int(self.config.get("chat_font_size", DEFAULT_FONT_SIZE)), 0)
        self._chat_wanted = int(self.config.get("chat_width", DEFAULT_CHAT_WIDTH))
        self.chat_width = clamp_chat_width(1080, self._chat_wanted)
        self._dragging_chat = False
        self._drag_start_x = 0
        self._drag_start_w = 0
        self.danmaku = None
        self.danmaku_queue: "queue.Queue" = queue.Queue()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.titlebar = TitleBar(self)
        layout.addWidget(self.titlebar)

        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        layout.addWidget(body, 1)

        self.video_host = VideoHost(self)
        body_layout.addWidget(self.video_host, 1)

        self.chat_dock = ChatDock(self)
        self.chat_dock.setFixedWidth(self.chat_width)
        body_layout.addWidget(self.chat_dock)

        self.idle_page = IdlePage(self.video_host, self)
        self.overlay = OverlayBar(self.video_host, self)
        self.chat_overlay = ChatOverlay(self.video_host, self)
        self._popups = (self.idle_page, self.overlay, self.chat_overlay)
        self.chat_overlay.hide()
        if not self.danmaku_visible:
            self.chat_dock.hide()

        self.mpv = MpvController(find_mpv(), on_event=self._on_mpv_event)

        self.idle_page.refresh(self.config)
        self.overlay.quality.blockSignals(True)
        self.overlay.cdn.blockSignals(True)
        self.overlay.quality.setCurrentText(
            self.config.get("quality", "原画")
            if self.config.get("quality", "原画") in QUALITIES else "原画")
        self.overlay.cdn.setCurrentText(
            self.config.get("cdn", "自动")
            if self.config.get("cdn", "自动") in CDNS else "自动")
        self.overlay.quality.blockSignals(False)
        self.overlay.cdn.blockSignals(False)
        self.overlay.volume.blockSignals(True)
        self.overlay.volume.setValue(int(self.config.get("volume", 100)))
        self.overlay.volume.blockSignals(False)
        self.overlay.volume_label.setText(f"{self.overlay.volume.value()}%")
        self.overlay.status.setText("输入房间号，按回车开始观看")
        self.overlay.hide()

        self._result_timer = QTimer(self)
        self._result_timer.setInterval(100)
        self._result_timer.timeout.connect(self._poll_results)
        self._result_timer.start()

        self._mpv_timer = QTimer(self)
        self._mpv_timer.setInterval(250)
        self._mpv_timer.timeout.connect(self._mpv_tick)
        self._mpv_timer.start()

        self._danmaku_timer = QTimer(self)
        self._danmaku_timer.setInterval(60)
        self._danmaku_timer.timeout.connect(self._drain_danmaku)
        self._danmaku_timer.start()

        self._quitting = False
        self._dot_state = "idle"
        self.shortcut_sheet = ShortcutSheet(self)
        self.shortcut_sheet.hide()
        self._build_tray()

    # ---- 窗口行为 ----
    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _edge_at(self, pos: QPoint):
        if self.isMaximized() or self.isFullScreen():
            return None
        rect = self.rect()
        left = pos.x() < RESIZE_EDGE
        right = pos.x() > rect.width() - RESIZE_EDGE
        top = pos.y() < RESIZE_EDGE
        bottom = pos.y() > rect.height() - RESIZE_EDGE
        if top and left:
            return Qt.TopLeftCorner
        if top and right:
            return Qt.TopRightCorner
        if bottom and left:
            return Qt.BottomLeftCorner
        if bottom and right:
            return Qt.BottomRightCorner
        if left:
            return Qt.LeftEdge
        if right:
            return Qt.RightEdge
        if top:
            return Qt.TopEdge
        if bottom:
            return Qt.BottomEdge
        return None

    def mousePressEvent(self, event):
        edge = self._edge_at(event.position().toPoint())
        if edge is not None and event.button() == Qt.LeftButton:
            self.windowHandle().startSystemResize(edge)
            return
        super().mousePressEvent(event)

    def _sync_popups(self) -> None:
        for popup in self._popups:
            popup.sync()

    def moveEvent(self, event):
        self._sync_popups()
        super().moveEvent(event)

    def resizeEvent(self, event):
        self._sync_popups()
        super().resizeEvent(event)

    def _restore_popups(self) -> None:
        self._sync_popups()
        if not self.current_room:
            self.idle_page.show()
        elif self.overlay.wanted:
            self.overlay.show()

    def changeEvent(self, event):
        # 最小化恢复后 owned 浮层不会自动回来，按 wanted 状态还原
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                for popup in self._popups:
                    popup.hide()
            else:
                self._restore_popups()
        super().changeEvent(event)

    def closeEvent(self, event):
        self._save_settings()
        if not self._quitting and self.tray.isVisible():
            event.ignore()
            self.hide()
            return
        self._stop_danmaku()
        self.mpv.stop()
        super().closeEvent(event)

    # ---- 取流与播放 ----
    def play(self) -> None:
        if self.fetching:
            return
        room_id = normalize_room_id(self.idle_page.room.text())
        if not room_id:
            self.overlay.reveal()
            self.overlay.status.setText("请输入房间号")
            return
        self.idle_page.room.setText(room_id)
        self._save_settings()
        self.fetching = True
        self.fetch_token += 1
        token = self.fetch_token
        self.overlay.reveal()
        self.overlay.status.setText(f"正在获取房间 {room_id} 的直播流…")
        quality = QUALITIES.get(self.overlay.quality.currentText(), 0)
        cdn = CDNS.get(self.overlay.cdn.currentText(), "")
        threading.Thread(target=self._resolve_worker,
                         args=(token, room_id, quality, cdn), daemon=True).start()

    def _resolve_worker(self, token, room_id, quality, cdn) -> None:
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
        except Exception as exc:  # noqa: BLE001 线程内兜底，回主线程报错
            self._result_queue.put(("error", token, str(exc)))

    def _poll_results(self) -> None:
        try:
            while True:
                result = self._result_queue.get_nowait()
                if result[1] != self.fetch_token:
                    continue
                self.fetching = False
                if result[0] == "ok":
                    _, _, room_id, url, profile = result
                    self._start_stream(url, room_id, profile)
                else:
                    self.overlay.reveal()
                    self.overlay.status.setText(f"错误：{result[2]}")
                    QMessageBox.critical(self, APP_TITLE, result[2])
        except queue.Empty:
            pass

    def _start_stream(self, url: str, room_id: str, profile: dict) -> None:
        self.video_host.winId()  # 强制创建原生 HWND，mpv 才能挂进来
        self.mpv.start(int(self.video_host.winId()), extra_args=MPV_EXTRA_ARGS)
        self.mpv.load(url, headers={"User-Agent": WUP_UA,
                                    "Referer": "https://www.huya.com/"})
        self.mpv.set_volume(self.overlay.volume.value())
        self.current_room = room_id
        self._artist = profile.get("artist") or room_id
        self.chat_model.clear()
        self.chat_dock.count.setText("0")
        self._set_dot("idle")
        self._start_danmaku(room_id)
        self.titlebar.title.setText(f"{APP_TITLE} · {self._artist}")
        self.overlay.status.setText(f"正在播放：{self._artist}")
        self.idle_page.vanish(self.theme["durations"]["fade_out"])
        self.overlay.reveal()
        self._save_settings()

    def stop(self) -> None:
        self.fetch_token += 1
        self.fetching = False
        self.mpv.stop()
        self._stop_danmaku()
        self.chat_model.clear()
        self.chat_dock.count.setText("0")
        self._set_dot("idle")
        self.current_room = ""
        self.titlebar.title.setText(APP_TITLE)
        self.overlay.status.setText("已停止")
        self.overlay.vanish(self.theme["durations"]["fade_out"])
        self.idle_page.refresh(self.config)
        self.idle_page.reveal(self.theme["durations"]["fade_in"])

    def _mpv_tick(self) -> None:
        self.mpv.pump_events()
        self.mpv.poll()

    def _on_mpv_event(self, event: dict) -> None:
        name = event.get("event")
        if name == "playback-restart" and self.current_room:
            self.overlay.status.setText(f"正在播放：{self._artist}")
        elif name in ("eof-reached", "idle-active") and self.current_room:
            self.overlay.status.setText("连接中断，自动重连中…")

    # ---- 控制 ----
    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.mpv.set_pause(self._paused)
        self.overlay.pause_btn.setText("▶" if self._paused else "⏸")

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self.mpv.set_mute(self._muted)

    def set_volume(self, value: int) -> None:
        self.overlay.volume_label.setText(f"{value}%")
        self.mpv.set_volume(value)

    def change_quality(self, _text: str) -> None:
        if not self.current_room:
            return
        self._save_settings()
        self.play()

    def change_cdn(self, _text: str) -> None:
        if not self.current_room:
            return
        self._save_settings()
        self.play()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._set_chat_mode()

    def _set_chat_mode(self) -> None:
        if self.isFullScreen() and self.danmaku_visible:
            self.chat_dock.hide()
            self.chat_overlay.sync()
            self.chat_overlay.show()
            self.chat_overlay.view.scrollToBottom()
        else:
            self.chat_overlay.hide()
            self.chat_dock.setVisible(self.danmaku_visible)

    def toggle_danmaku(self) -> None:
        self.danmaku_visible = not self.danmaku_visible
        self._set_chat_mode()
        self._save_settings()

    # ---- 弹幕侧栏宽度与字号 ----
    def chat_dragging(self) -> bool:
        return self._dragging_chat

    def begin_chat_drag(self, x: int) -> None:
        self._dragging_chat = True
        self._drag_start_x = x
        self._drag_start_w = self.chat_width

    def move_chat_drag(self, x: int) -> None:
        if self._dragging_chat:
            self._apply_chat_width(self._drag_start_w + (self._drag_start_x - x))

    def end_chat_drag(self) -> None:
        self._dragging_chat = False
        self._save_settings()

    def reset_chat_width(self) -> None:
        self._apply_chat_width(DEFAULT_CHAT_WIDTH)
        self._save_settings()

    def step_chat_width(self, delta: int) -> None:
        if not self.isFullScreen():
            self._apply_chat_width(self._chat_wanted + delta)
            self._save_settings()

    def _apply_chat_width(self, width: int, remember: bool = True) -> None:
        if remember:
            self._chat_wanted = width
        shown = clamp_chat_width(self.video_host.width() or 1080, self._chat_wanted)
        if shown == self.chat_width:
            return
        self.chat_width = shown
        self.chat_dock.setFixedWidth(shown)

    def step_font_size(self, delta: int) -> None:
        size = step_font_size(self.chat_font_size, delta)
        if size == self.chat_font_size:
            return
        self.chat_font_size = size
        self.chat_dock.view.reset()
        self.chat_overlay.view.reset()
        self._save_settings()

    # ---- 弹幕流 ----
    def _start_danmaku(self, room_id: str) -> None:
        self._stop_danmaku()
        client = HuyaDanmaku(room_id)
        client.on_message = lambda name, content: self.danmaku_queue.put((name, content))
        client.on_status = lambda text: self.danmaku_queue.put(("__status__", text))
        self.danmaku = client
        client.start()

    def _stop_danmaku(self) -> None:
        client, self.danmaku = self.danmaku, None
        if client is not None:
            client.stop()

    def _drain_danmaku(self) -> None:
        try:
            for _ in range(60):
                name, content = self.danmaku_queue.get_nowait()
                if name == "__status__":
                    self._append_status(content)
                else:
                    self._append_danmaku(name, content)
        except queue.Empty:
            pass

    def _append_danmaku(self, name: str, content: str) -> None:
        self.chat_model.append(name, content)
        self.chat_dock.count.setText(str(self.chat_model.rowCount()))

    def _append_status(self, message: str) -> None:
        self._set_dot("ok" if "已连接" in message else "err")
        self.chat_model.append_status(message)

    def _set_dot(self, state: str) -> None:
        self._dot_state = state
        colors = self.theme["colors"]
        color = {"ok": colors["ok"], "err": colors["err"]}.get(
            state, colors["text_faint"])
        self.chat_dock.dot.setStyleSheet(f"color: {color};")

    # ---- 主题 / 托盘 / 快捷键面板 ----
    def toggle_theme(self) -> None:
        self.theme = (THEMES["light"] if self.theme is THEMES["dark"]
                      else THEMES["dark"])
        QApplication.instance().setStyleSheet(qss(self.theme))
        self._set_dot(self._dot_state)
        self._save_settings()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        icon = resource_path("assets", "icon.ico")
        if os.path.isfile(icon):
            self.tray.setIcon(QIcon(icon))
        self.tray.setToolTip(APP_TITLE)
        menu = QMenu(self)
        menu.addAction("显示 / 隐藏", self._tray_toggle_visible)
        menu.addAction("暂停 / 继续", self.toggle_pause)
        menu.addSeparator()
        menu.addAction("退出", self.tray_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_toggle_visible(self) -> None:
        if self.isHidden():
            self.show()
            self._restore_popups()
        else:
            self.hide()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._tray_toggle_visible()

    def tray_exit(self) -> None:
        self._quitting = True
        self.close()

    def toggle_shortcuts(self) -> None:
        if self.shortcut_sheet.isVisible():
            self.shortcut_sheet.hide()
        else:
            self.shortcut_sheet.show_centered(self)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F11 or (key == Qt.Key_F
                                 and event.modifiers() == Qt.ControlModifier):
            self.toggle_fullscreen()
        elif key == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        elif key == Qt.Key_Space:
            self.toggle_pause()
        elif key == Qt.Key_M:
            self.toggle_mute()
        elif key == Qt.Key_Up:
            self.overlay.volume.setValue(min(130, self.overlay.volume.value() + 5))
        elif key == Qt.Key_Down:
            self.overlay.volume.setValue(max(0, self.overlay.volume.value() - 5))
        elif key == Qt.Key_D and event.modifiers() == Qt.ControlModifier:
            if self.focusWidget() is not self.idle_page.room:
                self.toggle_danmaku()
        elif key == Qt.Key_Left and event.modifiers() == Qt.ControlModifier:
            self.step_chat_width(-CHAT_WIDTH_STEP)
        elif key == Qt.Key_Right and event.modifiers() == Qt.ControlModifier:
            self.step_chat_width(CHAT_WIDTH_STEP)
        elif key == Qt.Key_F1:
            self.toggle_shortcuts()
        else:
            super().keyPressEvent(event)

    # ---- 配置 ----
    def _save_settings(self) -> None:
        self.config.update({
            "last_room": normalize_room_id(self.idle_page.room.text()),
            "quality": self.overlay.quality.currentText(),
            "cdn": self.overlay.cdn.currentText(),
            "volume": self.overlay.volume.value(),
            "chat_width": int(self.config.get("chat_width", DEFAULT_CHAT_WIDTH)),
            "chat_font_size": int(self.config.get("chat_font_size", DEFAULT_FONT_SIZE)),
            "danmaku_visible": self.danmaku_visible,
            "theme": "dark" if self.theme is THEMES["dark"] else "light",
        })
        save_config(self.config)


def main() -> None:
    app = QApplication(sys.argv)
    window = PlayerWindow()
    app.setStyleSheet(qss(window.theme))
    icon = resource_path("assets", "icon.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    if len(sys.argv) > 1:
        window.idle_page.room.setText(normalize_room_id(sys.argv[1]))
        QTimer.singleShot(300, window.play)
    window.show()
    window.idle_page.sync()
    window.idle_page.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
