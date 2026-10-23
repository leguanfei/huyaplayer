#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""弹幕侧栏的停靠容器：自绘 delegate、拖拽把手、右键菜单、未读胶囊。

全屏浮层容器在 app.py（复用 OwnedPopup），两者共用同一个 ChatModel。
紧凑单行流：一条弹幕一行，超出宽度省略号，不做换行。
"""

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QListView, QMenu, QPushButton,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from chat_model import ChatModel

GRIP_WIDTH = 14
ROW_PAD_X = 10
ROW_PAD_Y = 4


class ChatDelegate(QStyledItemDelegate):
    def __init__(self, panel: "ChatDock"):
        super().__init__(panel)
        self._panel = panel

    def _font(self, bold=False):
        size = self._panel.font_size()
        font = QFont(self._panel.ui_family(), size)
        font.setBold(bold)
        return font

    def sizeHint(self, option, index):
        metrics = QFontMetrics(self._font())
        return QSize(option.rect.width(), metrics.height() + ROW_PAD_Y * 2)

    def paint(self, painter, option, index):
        model = index.model()
        kind = model.data(index, ChatModel.KindRole)
        alt = model.data(index, ChatModel.AltRole)
        theme = self._panel.theme()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if alt:
            painter.fillRect(option.rect, QColor(theme["colors"]["row_alt"]))
        if option.state & option.state.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme["colors"]["row_hover"]))

        now = model.now_ms()
        progress = 1.0
        for row, value in model.animating_rows(now):
            if row == index.row():
                progress = value
                break
        if progress < 1.0:
            painter.setOpacity(progress)
            painter.translate(0, (1.0 - progress) * 10)

        rect = option.rect.adjusted(ROW_PAD_X, ROW_PAD_Y, -ROW_PAD_X, -ROW_PAD_Y)
        metrics = QFontMetrics(self._font())
        x = rect.left()

        if kind == "status":
            painter.setFont(self._font())
            painter.setPen(QColor(theme["colors"]["text_faint"]))
            text = metrics.elidedText(
                model.data(index, ChatModel.ContentRole),
                Qt.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.restore()
            return

        stamp = model.data(index, ChatModel.StampRole)
        painter.setFont(self._font())
        painter.setPen(QColor(theme["colors"]["text_faint"]))
        painter.drawText(QPoint(x, rect.center().y() + metrics.height() // 2), stamp)
        x += metrics.horizontalAdvance(stamp) + 8

        nick = model.data(index, ChatModel.NickRole)
        painter.setFont(self._font(bold=True))
        painter.setPen(QColor(model.data(index, ChatModel.ColorRole)))
        painter.drawText(QPoint(x, rect.center().y() + metrics.height() // 2), nick)
        x += metrics.horizontalAdvance(nick) + 8

        painter.setFont(self._font())
        painter.setPen(QColor(theme["colors"]["text"]))
        content = model.data(index, ChatModel.ContentRole)
        width = rect.right() - x
        if width > 0:
            text = metrics.elidedText(content, Qt.ElideRight, width)
            painter.drawText(QPoint(x, rect.center().y() + metrics.height() // 2), text)
        painter.restore()


class Grip(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setFixedWidth(GRIP_WIDTH)
        self.setCursor(Qt.SizeHorCursor)
        self.setObjectName("chatGrip")
        self._window = window
        self._hot = False

    def paintEvent(self, _event):
        painter = QPainter(self)
        theme = self._window.theme
        active = self._hot or self._window.chat_dragging()
        center = self.width() // 2
        middle = self.height() // 2
        pen = QPen(QColor(theme["colors"]["divider"]))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(center, 0, center, self.height())
        if active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme["colors"]["accent"]))
            painter.drawRoundedRect(center - 5, middle - 12, 10, 24, 5, 5)
            mark = QColor(theme["colors"]["accent_ink"])
        else:
            mark = QColor(theme["colors"]["text_faint"])
        pen = QPen(mark)
        pen.setWidth(2)
        painter.setPen(pen)
        for offset in (-6, 0, 6):
            painter.drawLine(center - 3, middle + offset, center + 3, middle + offset)

    def enterEvent(self, event):
        self._hot = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._window.chat_dragging():
            self._hot = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._window.begin_chat_drag(event.globalPosition().toPoint().x())
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._window.move_chat_drag(event.globalPosition().toPoint().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._window.end_chat_drag()
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._window.reset_chat_width()
        super().mouseDoubleClickEvent(event)


class ChatDock(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("chatPanel")
        self._window = window
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(30)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._unread = 0

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.grip = Grip(window)
        outer.addWidget(self.grip)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        outer.addLayout(column, 1)

        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 10, 8)
        header.setSpacing(6)
        self.dot = QLabel("●", self)
        self.dot.setObjectName("chatDot")
        header.addWidget(self.dot)
        title = QLabel("弹幕", self)
        title.setObjectName("chatTitle")
        header.addWidget(title)
        self.count = QLabel("0", self)
        self.count.setObjectName("chatCount")
        header.addWidget(self.count)
        header.addStretch(1)
        clear = QPushButton("清屏", self)
        clear.setObjectName("iconBtn")
        clear.clicked.connect(self._clear)
        header.addWidget(clear)
        column.addLayout(header)

        hairline = QFrame(self)
        hairline.setObjectName("hairline")
        hairline.setFixedHeight(1)
        column.addWidget(hairline)

        self.view = QListView(self)
        self.view.setObjectName("chatView")
        self.view.setModel(window.chat_model)
        self.view.setItemDelegate(ChatDelegate(self))
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMouseTracking(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._open_menu)
        self.view.viewport().installEventFilter(self)
        column.addWidget(self.view, 1)

        self.pill = QPushButton("↓ 新消息", self)
        self.pill.setObjectName("jumpPill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.hide()
        self.pill.clicked.connect(self.jump_to_bottom)

        bar = self.view.verticalScrollBar()
        bar.valueChanged.connect(self._on_scroll)
        bar.rangeChanged.connect(self._on_range)
        window.chat_model.rowsInserted.connect(self._on_rows)

    # ---- 供 delegate 查询 ----
    def theme(self):
        return self._window.theme

    def font_size(self):
        return self._window.chat_font_size

    def ui_family(self):
        return self._window.theme["fonts"]["ui"]

    # ---- 跟随与未读 ----
    def _at_bottom(self) -> bool:
        bar = self.view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _on_rows(self, _parent, first, _last):
        if self._at_bottom():
            self.view.scrollToBottom()
            self._unread = 0
            self.pill.hide()
        else:
            self._unread += 1
            self.pill.setText(f"↓ 新消息 {self._unread} 条")
            self.pill.show()
            self.pill.adjustSize()
        self.count.setText(str(self._window.chat_model.rowCount()))
        self._anim_timer.start()

    def _on_scroll(self, _value):
        if self._at_bottom() and self._unread:
            self._unread = 0
            self.pill.hide()

    def _on_range(self, _min, _max):
        if not self._unread:
            self.view.scrollToBottom()

    def jump_to_bottom(self):
        self._unread = 0
        self.pill.hide()
        self.view.scrollToBottom()

    def _tick_anim(self):
        if self._window.chat_model.animating_rows(
                self._window.chat_model.now_ms()):
            self.view.viewport().update()
        else:
            self._anim_timer.stop()

    def resizeEvent(self, event):
        self.pill.move((self.width() - self.pill.width()) // 2,
                       self.height() - self.pill.height() - 12)
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() == event.Type.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = 1 if event.angleDelta().y() > 0 else -1
                self._window.step_font_size(delta)
                return True
        return super().eventFilter(watched, event)

    # ---- 菜单 ----
    def _clear(self):
        self._window.chat_model.clear()
        self.count.setText("0")
        self._unread = 0
        self.pill.hide()

    def _open_menu(self, pos):
        menu = QMenu(self)
        has_selection = False
        copy_sel = menu.addAction("复制选中")
        copy_sel.setEnabled(has_selection)
        copy_sel.triggered.connect(self._copy_selection)
        menu.addAction("复制全部弹幕", self._copy_all)
        menu.addSeparator()
        menu.addAction("放大字号", lambda: self._window.step_font_size(1))
        menu.addAction("缩小字号", lambda: self._window.step_font_size(-1))
        menu.addAction("复位栏宽", self._window.reset_chat_width)
        menu.addSeparator()
        menu.addAction("隐藏弹幕栏", self._window.toggle_danmaku)
        menu.exec(self.view.mapToGlobal(pos))

    def _copy_selection(self):
        pass

    def _copy_all(self):
        model = self._window.chat_model
        lines = []
        for row in range(model.rowCount()):
            index = model.index(row)
            if model.data(index, ChatModel.KindRole) == "chat":
                lines.append(f"{model.data(index, ChatModel.NickRole)}："
                             f"{model.data(index, ChatModel.ContentRole)}")
            else:
                lines.append(model.data(index, ChatModel.ContentRole))
        if lines:
            QApplication.clipboard().setText("\n".join(lines))
