#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""弹幕列表数据模型。

QAbstractListModel + 自绘 delegate 使用。滚动锚定由 QListView 的像素级
scrollbar 天然保证（Tk Text 的比例锚定问题不复存在），这里只管数据与
入场动画窗口：动画只覆盖最近 anim_tail 行，避免整列表每帧重绘。
"""

import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

MAX_MESSAGES = 600
KEEP_MESSAGES = 300

NICK_COLORS = (
    "#e6b667", "#7fc4f0", "#f0938f", "#8fd39a",
    "#c09ae8", "#e8d67a", "#6fd0c4", "#ef9ac4",
    "#a8bcf0", "#d9a877", "#85d9b6", "#d98fb8",
)


class _Row:
    __slots__ = ("stamp", "nick", "content", "kind", "color", "alt", "appear")


class ChatModel(QAbstractListModel):
    StampRole = Qt.UserRole + 1
    NickRole = Qt.UserRole + 2
    ContentRole = Qt.UserRole + 3
    KindRole = Qt.UserRole + 4
    ColorRole = Qt.UserRole + 5
    AltRole = Qt.UserRole + 6

    def __init__(self, clock=None, enter_ms=180, anim_tail=8, parent=None):
        super().__init__(parent)
        self._clock = clock or (lambda: int(time.monotonic() * 1000))
        self._enter_ms = enter_ms
        self._anim_tail = anim_tail
        self._rows = []
        self._alt = False
        self._last_status = None
        self._colors = {}

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.StampRole:
            return row.stamp
        if role == self.NickRole:
            return row.nick
        if role == self.ContentRole:
            return row.content
        if role == self.KindRole:
            return row.kind
        if role == self.ColorRole:
            return row.color
        if role == self.AltRole:
            return row.alt
        if role == Qt.DisplayRole:
            return f"{row.nick}：{row.content}" if row.kind == "chat" else row.content
        return None

    def append(self, nick: str, content: str) -> None:
        self._push(self._make_row(nick, content, "chat"))

    def append_status(self, text: str) -> None:
        if text == self._last_status:
            return
        self._last_status = text
        self._push(self._make_row("", text, "status"))

    def clear(self) -> None:
        self._last_status = None
        self._alt = False
        if not self._rows:
            return
        self.beginRemoveRows(QModelIndex(), 0, len(self._rows) - 1)
        self._rows.clear()
        self.endRemoveRows()

    def now_ms(self) -> int:
        return self._clock()

    def animating_rows(self, now_ms: int):
        """返回 [(行号, 0..1 进度)]，只覆盖最近 anim_tail 行里仍在入场窗口内的。"""
        out = []
        start = max(0, len(self._rows) - self._anim_tail)
        for i in range(start, len(self._rows)):
            elapsed = now_ms - self._rows[i].appear
            if 0 <= elapsed < self._enter_ms:
                out.append((i, elapsed / self._enter_ms))
        return out

    def _make_row(self, nick, content, kind) -> _Row:
        row = _Row()
        row.stamp = time.strftime("%H:%M")
        row.nick = nick
        row.content = content
        row.kind = kind
        row.color = self._color_for(nick)
        row.alt = self._alt
        self._alt = not self._alt
        row.appear = self._clock()
        return row

    def _color_for(self, nick: str) -> str:
        color = self._colors.get(nick)
        if color is None:
            color = NICK_COLORS[sum(map(ord, nick)) % len(NICK_COLORS)]
            self._colors[nick] = color
        return color

    def _push(self, row: _Row) -> None:
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(row)
        self.endInsertRows()
        if len(self._rows) > MAX_MESSAGES:
            cut = len(self._rows) - KEEP_MESSAGES
            self.beginRemoveRows(QModelIndex(), 0, cut - 1)
            del self._rows[:cut]
            self.endRemoveRows()
