import unittest

from chat_layout import (
    CHAT_MAX_WIDTH,
    CHAT_MIN_WIDTH,
    DEFAULT_CHAT_WIDTH,
    FONT_SIZES,
    clamp_chat_width,
    step_font_size,
)


class ClampChatWidthTest(unittest.TestCase):
    def test_leaves_valid_width_untouched(self):
        self.assertEqual(clamp_chat_width(body_width=1080, width=DEFAULT_CHAT_WIDTH), 320)

    def test_never_goes_below_minimum(self):
        self.assertEqual(clamp_chat_width(body_width=1080, width=80), CHAT_MIN_WIDTH)

    def test_never_goes_above_absolute_maximum(self):
        self.assertEqual(clamp_chat_width(body_width=2400, width=5000), CHAT_MAX_WIDTH)

    def test_keeps_video_its_ratio_floor_on_large_windows(self):
        # body 1500 -> 画面至少 55% = 825 -> 侧栏最多 675，比硬上限 720 更严
        self.assertEqual(clamp_chat_width(body_width=1500, width=700), 675)

    def test_keeps_video_its_absolute_floor_on_small_windows(self):
        # body 1080 -> 画面至少 max(560, 594) = 594 -> 侧栏最多 486
        self.assertEqual(clamp_chat_width(body_width=1080, width=700), 486)

    def test_minimum_wins_when_window_is_too_narrow_for_both(self):
        # body 700 -> 画面固定要 560 -> 算出的上限 140 低于下限，此时保住侧栏可读宽度
        self.assertEqual(clamp_chat_width(body_width=700, width=400), CHAT_MIN_WIDTH)

    def test_handles_unmeasured_window_width(self):
        # Tk 在窗口 realize 前 winfo_width() 返回 1
        self.assertEqual(clamp_chat_width(body_width=1, width=320), CHAT_MIN_WIDTH)


class StepFontSizeTest(unittest.TestCase):
    def test_steps_up_one_notch(self):
        self.assertEqual(step_font_size(11, 1), 12)

    def test_steps_down_one_notch(self):
        self.assertEqual(step_font_size(11, -1), 10)

    def test_stays_at_smallest(self):
        self.assertEqual(step_font_size(FONT_SIZES[0], -3), FONT_SIZES[0])

    def test_stays_at_largest(self):
        self.assertEqual(step_font_size(FONT_SIZES[-1], 3), FONT_SIZES[-1])

    def test_snaps_unknown_size_to_nearest(self):
        self.assertEqual(step_font_size(9, 0), 10)
        self.assertEqual(step_font_size(14, 0), FONT_SIZES[-1])


if __name__ == "__main__":
    unittest.main()
