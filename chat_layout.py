#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""弹幕侧栏的布局数学，与 Tkinter 解耦以便单测。"""

CHAT_MIN_WIDTH = 220
CHAT_MAX_WIDTH = 720
DEFAULT_CHAT_WIDTH = 320
CHAT_WIDTH_STEP = 40

VIDEO_MIN_WIDTH = 560
VIDEO_MIN_PERCENT = 55

FONT_SIZES = (10, 11, 12, 13)
DEFAULT_FONT_SIZE = 10


def clamp_chat_width(body_width: int, width: int) -> int:
    """把期望栏宽收敛到可用区间，优先保证画面不被挤没。

    画面至少保留 VIDEO_MIN_WIDTH 与窗口宽 55% 中的较大者。
    栏宽下限永远优先：窗口窄到放不下「画面 560 + 栏 220」时保留栏宽，
    否则侧栏会退化成不可读的一根条。
    """
    video_floor = max(VIDEO_MIN_WIDTH, body_width * VIDEO_MIN_PERCENT // 100)
    upper = min(CHAT_MAX_WIDTH, body_width - video_floor)
    return max(CHAT_MIN_WIDTH, min(upper, width))


def step_font_size(current: int, delta: int) -> int:
    """在字号档位间上下跳，越界即停在端点；未知字号吸附到最近档。"""
    if delta > 0:
        for size in FONT_SIZES:
            if size > current:
                return size
        return FONT_SIZES[-1]
    if delta < 0:
        for size in reversed(FONT_SIZES):
            if size < current:
                return size
        return FONT_SIZES[0]
    return min(FONT_SIZES, key=lambda size: (abs(size - current), size))
