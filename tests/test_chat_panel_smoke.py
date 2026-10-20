import sys
import types
import unittest
from pathlib import Path
from tkinter import TclError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tkinter as tk

import app as app_module
from chat_layout import CHAT_MIN_WIDTH

TRIM_MESSAGES = 800


def display_available() -> bool:
    try:
        probe = tk.Tk()
    except TclError:
        return False
    probe.destroy()
    return True


@unittest.skipUnless(display_available(), "本机无法创建 Tk 窗口，跳过面板集成测试")
class ChatPanelTest(unittest.TestCase):
    """弹幕侧栏的行为回归：跟随、悬浮、宽度边界。"""

    def setUp(self):
        # 测试不得读写用户真实配置
        self._real_save = app_module.save_config
        self._real_load = app_module.load_config
        app_module.save_config = lambda cfg: None
        app_module.load_config = lambda: {}

        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app_module.HuyaApp(self.root)
        self.root.geometry("1280x720")
        self.root.deiconify()
        self.root.update()

    def tearDown(self):
        self.app.mpv_proc = None
        self.root.tk.eval("after cancel all")
        self.root.destroy()
        app_module.save_config = self._real_save
        app_module.load_config = self._real_load

    def test_append_at_bottom_keeps_view_glued_to_end(self):
        text = self.app.chat_text
        for index in range(20):
            self.app._append_danmaku(f"主播{index}", "收到")
        self.root.update()
        self.assertEqual(self.app._chat_count, 20)
        self.assertTrue(self.app._is_at_bottom())
        self.assertEqual(text.yview()[1], 1.0)

    def test_appends_before_first_layout_stay_following(self):
        # 新建但尚未布局的窗口里 yview() 是 (0.0, 0.0x)，不能据此判定用户上翻了
        top = tk.Toplevel(self.root)
        late = app_module.HuyaApp(top)
        for index in range(5):
            late._append_danmaku(f"主播{index}", "收到")

        self.assertEqual(late._new_msg_count, 0)
        self.assertEqual(late.new_msg_btn.winfo_manager(), "")

    def test_following_mode_never_reports_unread(self):
        # _drain_danmaku 一次批量插入多条且不经过事件循环，此时 yview 还是旧值
        for index in range(200):
            self.app._append_danmaku(f"主播{index}", "收到")
        self.root.update()

        self.assertEqual(self.app._new_msg_count, 0)
        self.assertEqual(self.app.new_msg_btn.winfo_manager(), "")
        self.assertTrue(self.app._is_at_bottom())

    def test_grip_and_width_controls_stay_consistent(self):
        self.app._grip_enter(types.SimpleNamespace())
        self.app._grip_leave(types.SimpleNamespace())
        self.root.update()
        self.assertTrue(self.app.divider.find_all(), "把手未被绘制")

        self.app._apply_chat_width(400)
        self.root.update()
        self.assertEqual(self.app.chat_width, 400)

        self.app._step_chat_width(-40)
        self.assertEqual(self.app.chat_width, 360)
        self.app._step_chat_width(40)
        self.assertEqual(self.app.chat_width, 400)

        self.app._reset_chat_width(None)
        self.assertEqual(self.app._chat_wanted, app_module.DEFAULT_CHAT_WIDTH)
        self.assertEqual(self.app.chat_width, app_module.DEFAULT_CHAT_WIDTH)

    def test_font_size_steps_between_gears(self):
        start = self.app.chat_font_size
        self.app._on_font_wheel(types.SimpleNamespace(delta=120))
        self.assertEqual(self.app.chat_font_size, start + 1)
        self.assertIn(str(start + 1), str(self.app.chat_text.cget("font")))

        self.app._on_font_wheel(types.SimpleNamespace(delta=-120))
        self.assertEqual(self.app.chat_font_size, start)
        self.assertIn(str(start), str(self.app.chat_text.cget("font")))

    def test_scrolled_up_history_is_not_pushed_away(self):
        text = self.app.chat_text
        for index in range(120):
            self.app._append_danmaku(f"主播{index}", "收到")
        self.root.update()

        text.yview_moveto(0.5)
        self.root.update()
        marker = self._top_line_text()

        for index in range(30):
            self.app._append_danmaku(f"路人{index}", "哈哈哈")
        self.root.update()

        self.assertEqual(self._top_line_text(), marker, "上翻后被新弹幕顶走了")
        self.assertFalse(self.app._is_at_bottom())

    def test_scrolled_up_reports_pending_messages(self):
        text = self.app.chat_text
        for index in range(120):
            self.app._append_danmaku(f"主播{index}", "收到")
        text.yview_moveto(0.0)
        self.root.update()

        for index in range(5):
            self.app._append_danmaku(f"路人{index}", "你好")
        self.root.update()

        self.assertEqual(self.app._new_msg_count, 5)
        self.assertTrue(self.app.new_msg_btn.winfo_manager() == "place")
        self.assertIn("5", self.app.new_msg_btn.cget("text"))

    def test_jump_to_bottom_clears_pending_badge(self):
        text = self.app.chat_text
        for index in range(120):
            self.app._append_danmaku(f"主播{index}", "收到")
        text.yview_moveto(0.0)
        for index in range(3):
            self.app._append_danmaku(f"路人{index}", "你好")
        self.root.update()

        self.app._jump_to_bottom()
        self.root.update()

        self.assertEqual(self.app._new_msg_count, 0)
        self.assertEqual(self.app.new_msg_btn.winfo_manager(), "")
        self.assertTrue(self.app._is_at_bottom())

    def test_history_is_trimmed_to_cap(self):
        for index in range(TRIM_MESSAGES):
            self.app._append_danmaku(f"主播{index}", "收到")
        self.root.update()
        self.assertLessEqual(self.app._display_line_count(), app_module.MAX_CHAT_LINES)

    def _top_line_text(self) -> str:
        line = self.app._top_visible_line()
        return self.app.chat_text.get(f"{line}.0", f"{line}.end")

    def test_trim_keeps_viewed_content_still_visible(self):
        text = self.app.chat_text
        for index in range(app_module.MAX_CHAT_LINES - 5):
            self.app._append_danmaku(f"主播{index}", "收到")
        text.yview_moveto(0.85)
        self.root.update()
        marker = self._top_line_text()

        for index in range(200):
            self.app._append_danmaku(f"路人{index}", "你好")
        self.root.update()

        self.assertLessEqual(self.app._display_line_count(), app_module.MAX_CHAT_LINES)
        self.assertFalse(self.app._is_at_bottom())
        self.assertEqual(self._top_line_text(), marker)

    def test_trim_past_the_viewport_lands_on_oldest_kept_line(self):
        text = self.app.chat_text
        for index in range(app_module.MAX_CHAT_LINES - 5):
            self.app._append_danmaku(f"主播{index}", "收到")
        text.yview_moveto(0.35)
        self.root.update()

        for index in range(200):
            self.app._append_danmaku(f"路人{index}", "你好")
        self.root.update()

        # 正在看的那条已被裁掉，此时应停在最旧保留行，而不是跳到最新消息附近
        self.assertEqual(self.app._top_visible_line(), 1)
        self.assertLess(self.app._top_visible_line(), self.app._display_line_count())

    def test_rows_alternate_backgrounds(self):
        self.app._append_danmaku("主播", "第一条")
        self.app._append_danmaku("主播", "第二条")
        self.root.update()
        self.assertIn("row", self.app.chat_text.tag_names("1.0"))
        self.assertIn("row_alt", self.app.chat_text.tag_names("2.0"))

    def test_hover_highlights_the_line_under_the_cursor(self):
        self.app._append_danmaku("主播", "第一条")
        self.app._append_danmaku("主播", "第二条")
        self.root.update()
        info = self.app.chat_text.dlineinfo("2.0")
        self.assertIsNotNone(info, "文本控件未 realize，无法验证悬停")

        self.app._on_chat_motion(types.SimpleNamespace(x=info[0] + 4, y=info[1] + 4))
        self.assertTrue(self.app.chat_text.tag_ranges("current"))
        self.app._clear_hover()
        self.assertFalse(self.app.chat_text.tag_ranges("current"))

    def test_status_lines_are_deduplicated(self):
        before = self.app._display_line_count()
        self.app._append_status("弹幕已连接")
        self.app._append_status("弹幕已连接")
        self.app._append_status("弹幕已断开：网络异常")
        self.root.update()
        self.assertEqual(self.app._display_line_count() - before, 2)

    def test_clear_chat_resets_follow_and_badge_state(self):
        for index in range(120):
            self.app._append_danmaku(f"主播{index}", "收到")
        self.app.chat_text.yview_moveto(0.0)
        self.app._append_danmaku("路人", "你好")
        self.root.update()

        self.app._clear_chat()
        self.root.update()

        self.assertEqual(self.app._display_line_count(), 1)
        self.assertEqual(self.app._new_msg_count, 0)
        self.assertTrue(self.app._is_at_bottom())

    def test_drag_resize_moves_the_panel(self):
        start = self.app.chat_width
        event = types.SimpleNamespace(x_root=1000)
        self.app._start_resize(event)
        self.app._on_resize(types.SimpleNamespace(x_root=1000 - 120))
        self.app._end_resize(types.SimpleNamespace())
        self.root.update()

        self.assertEqual(self.app.chat_width, start + 120)
        self.assertEqual(self.app.chat_frame.winfo_width(), start + 120)

    def test_drag_beyond_bounds_anchors_at_video_floor(self):
        self.app._start_resize(types.SimpleNamespace(x_root=1000))
        # 往左拖 900px，远超可用空间，应停在「画面不小于 55%」的上限
        self.app._on_resize(types.SimpleNamespace(x_root=100 - 900))
        self.app._end_resize(types.SimpleNamespace())
        self.root.update()

        body_width = self.app.body.winfo_width()
        self.assertEqual(self.app.chat_width, body_width - body_width * 55 // 100)

        # 反向拖动必须立刻有响应，不能穿过死区
        self.app._start_resize(types.SimpleNamespace(x_root=self.app.chat_width))
        anchor = self.app.chat_width
        self.app._on_resize(types.SimpleNamespace(x_root=self.app._drag_start_x + 200))
        self.app._end_resize(types.SimpleNamespace())
        self.root.update()
        self.assertLess(self.app.chat_width, anchor)

    def test_shrinking_window_then_reopening_panel_reclamps(self):
        self.app._apply_chat_width(700)
        self.root.geometry("760x600")
        self.root.update()
        self.app.toggle_danmaku()   # 隐藏
        self.app.toggle_danmaku()   # 重新展开
        self.root.update()
        self.assertLessEqual(self.app.chat_width, self.app.body.winfo_width() - CHAT_MIN_WIDTH)
        self.assertGreaterEqual(self.app.chat_width, CHAT_MIN_WIDTH)


if __name__ == "__main__":
    unittest.main()
