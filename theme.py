#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""设计令牌与 QSS 生成。不 import PySide6，纯数据 + 纯字符串，便于单测。"""

_DARK = {
    "colors": {
        "bg": "#0b0d11",
        "panel": "rgba(18, 20, 26, 0.92)",
        "panel_solid": "#12141a",
        "divider": "#22252d",
        "text": "#e6e8ee",
        "text_dim": "#9aa0ae",
        "text_faint": "#5f6572",
        "accent": "#e8a33d",
        "accent_ink": "#1a1408",
        "ok": "#4ec97a",
        "warn": "#e0b34f",
        "err": "#e08585",
        "video_bg": "#000000",
        "hover": "rgba(255, 255, 255, 0.06)",
        "row_alt": "rgba(255, 255, 255, 0.035)",
        "row_hover": "rgba(255, 255, 255, 0.07)",
    },
    "radius": {"card": 10, "ctrl": 6, "pill": 999},
    "space": (4, 8, 12, 16, 20, 24),
    "durations": {"enter": 180, "fade_in": 140, "fade_out": 260,
                  "idle_hide": 2000, "scroll": 120},
    "chat_anim_tail": 8,
    "fonts": {"ui": "Microsoft YaHei UI", "num": "Segoe UI",
              "xs": 11, "sm": 12, "md": 13, "lg": 15, "xl": 20, "idle": 28},
}

_LIGHT = {
    "colors": {
        "bg": "#f4f5f7",
        "panel": "#ffffff",
        "panel_solid": "#ffffff",
        "divider": "#e3e6ec",
        "text": "#23262c",
        "text_dim": "#6a7280",
        "text_faint": "#9aa1ad",
        "accent": "#c07f1f",
        "accent_ink": "#ffffff",
        "ok": "#2f9e5f",
        "warn": "#b07d18",
        "err": "#c65454",
        "video_bg": "#000000",
        "hover": "rgba(0, 0, 0, 0.05)",
        "row_alt": "rgba(0, 0, 0, 0.03)",
        "row_hover": "rgba(0, 0, 0, 0.06)",
    },
    "radius": {"card": 10, "ctrl": 6, "pill": 999},
    "space": (4, 8, 12, 16, 20, 24),
    "durations": {"enter": 180, "fade_in": 140, "fade_out": 260,
                  "idle_hide": 2000, "scroll": 120},
    "chat_anim_tail": 8,
    "fonts": {"ui": "Microsoft YaHei UI", "num": "Segoe UI",
              "xs": 11, "sm": 12, "md": 13, "lg": 15, "xl": 20, "idle": 28},
}

THEMES = {"dark": _DARK, "light": _LIGHT}

ACCENT_SOFT_ALPHA = 0.16


def _rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def with_accent(name: str, accent: str) -> dict:
    theme = THEMES[name]
    clone = {key: dict(value) if isinstance(value, dict) else value
             for key, value in theme.items()}
    clone["colors"] = dict(theme["colors"])
    clone["colors"]["accent"] = accent
    return clone


def qss(theme: dict) -> str:
    c = theme["colors"]
    r = theme["radius"]
    f = theme["fonts"]
    accent = c["accent"]
    accent_soft = _rgba(accent, ACCENT_SOFT_ALPHA)
    font = f'"{f["ui"]}", "{f["num"]}", sans-serif'

    return f"""
QWidget {{
    background: {c['bg']};
    color: {c['text']};
    font-family: {font};
    font-size: {f['md']}px;
}}
QWidget#titlebar {{
    background: {c['panel_solid']};
    border-bottom: 1px solid {c['divider']};
}}
QLabel#logoDot {{
    background: {accent};
    border-radius: 5px;
}}
QWidget#videoHost {{
    background: {c['video_bg']};
}}
QWidget#chatPanel {{
    background: {c['panel']};
    border-left: 1px solid {c['divider']};
}}
QWidget#overlayBar {{
    background: transparent;
}}
QLabel {{
    background: transparent;
}}
QLabel#idleTitle {{
    font-size: {f['xl']}px;
    color: {c['text_dim']};
}}
QLabel#idleHint {{
    font-size: {f['sm']}px;
    color: {c['text_faint']};
}}
QLineEdit {{
    background: {c['hover']};
    border: 1px solid {c['divider']};
    border-radius: {r['ctrl']}px;
    padding: 6px 12px;
    color: {c['text']};
    selection-background-color: {accent_soft};
}}
QLineEdit:focus {{
    border: 1px solid {accent};
}}
QLineEdit#idleRoom {{
    font-size: {f['idle']}px;
    padding: 10px 18px;
    border-radius: {r['card']}px;
}}
QPushButton {{
    background: {c['hover']};
    border: none;
    border-radius: {r['ctrl']}px;
    padding: 6px 14px;
    color: {c['text']};
}}
QPushButton:hover {{
    background: {c['row_hover']};
}}
QPushButton:pressed {{
    background: {accent_soft};
}}
QPushButton:disabled {{
    color: {c['text_faint']};
}}
QPushButton[accent="true"] {{
    background: {accent};
    color: {c['accent_ink']};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background: {_rgba(accent, 0.85)};
}}
QPushButton[accent="true"]:pressed {{
    background: {_rgba(accent, 0.7)};
}}
QPushButton#iconBtn {{
    background: transparent;
    border-radius: {r['ctrl']}px;
    padding: 4px 8px;
    color: {c['text_dim']};
}}
QPushButton#iconBtn:hover {{
    background: {c['hover']};
    color: {c['text']};
}}
QSlider::groove:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: {c['hover']};
}}
QSlider::sub-page:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: {accent};
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: {c['text']};
    border: 2px solid {accent};
}}
QListView {{
    background: transparent;
    border: none;
    outline: none;
}}
QListView::item {{
    background: transparent;
}}
QListView::item:alternate {{
    background: {c['row_alt']};
}}
QListView::item:hover {{
    background: {c['row_hover']};
}}
QLabel#chatTitle {{
    font-weight: 600;
}}
QLabel#chatCount {{
    color: {c['text_dim']};
    font-size: {f['xs']}px;
}}
QLabel#chatDot {{
    font-size: {f['xs']}px;
    color: {c['text_faint']};
}}
QFrame#hairline {{
    background: {c['divider']};
    border: none;
}}
QWidget#chatGrip {{
    background: {c['bg']};
}}
QWidget#chatGrip:hover {{
    background: {c['hover']};
}}
QPushButton#jumpPill {{
    background: {accent};
    color: {c['accent_ink']};
    border-radius: {r['pill']}px;
    padding: 4px 14px;
    font-weight: 600;
    font-size: {f['xs']}px;
}}
QWidget#chatOverlay {{
    background: transparent;
}}
QDialog#shortcutSheet {{
    background: {c['panel_solid']};
    border: 1px solid {c['divider']};
    border-radius: {r['card']}px;
}}
QLabel#shortcutKey {{
    color: {accent};
    font-weight: 600;
    font-size: {f['sm']}px;
}}
QLabel#shortcutDesc {{
    color: {c['text_dim']};
    font-size: {f['sm']}px;
}}
QMenu {{
    background: {c['panel_solid']};
    border: 1px solid {c['divider']};
    border-radius: {r['ctrl']}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 16px;
    border-radius: 4px;
    color: {c['text']};
}}
QMenu::item:selected {{
    background: {accent_soft};
    color: {accent};
}}
QMenu::separator {{
    height: 1px;
    background: {c['divider']};
    margin: 4px 8px;
}}
QToolTip {{
    background: {c['panel_solid']};
    color: {c['text']};
    border: 1px solid {c['divider']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {f['xs']}px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['row_hover']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['text_faint']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['row_hover']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""
