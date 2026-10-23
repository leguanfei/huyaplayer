import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from chat_model import KEEP_MESSAGES, MAX_MESSAGES, ChatModel

_app = QApplication.instance() or QApplication([])


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


def make_model():
    clock = FakeClock()
    return ChatModel(clock=clock, enter_ms=180, anim_tail=8), clock


class Roles(unittest.TestCase):
    def test_append_exposes_every_role_the_delegate_needs(self):
        model, _clock = make_model()
        model.append("夜刃", "这波打得漂亮")
        index = model.index(0)
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(index, ChatModel.NickRole), "夜刃")
        self.assertEqual(model.data(index, ChatModel.ContentRole), "这波打得漂亮")
        self.assertEqual(model.data(index, ChatModel.KindRole), "chat")
        self.assertIsInstance(model.data(index, ChatModel.StampRole), str)
        self.assertIsInstance(model.data(index, ChatModel.ColorRole), str)

    def test_zebra_rows_alternate(self):
        model, _clock = make_model()
        for i in range(4):
            model.append(f"u{i}", "x")
        flags = [model.data(model.index(i), ChatModel.AltRole) for i in range(4)]
        self.assertEqual(flags, [False, True, False, True])

    def test_nick_color_is_stable_for_the_same_nick(self):
        model, _clock = make_model()
        model.append("夜刃", "a")
        model.append("别人", "b")
        model.append("夜刃", "c")
        first = model.data(model.index(0), ChatModel.ColorRole)
        third = model.data(model.index(2), ChatModel.ColorRole)
        self.assertEqual(first, third)

    def test_status_rows_dedupe_consecutive_identical_text(self):
        model, _clock = make_model()
        model.append_status("弹幕已连接")
        model.append_status("弹幕已连接")
        model.append_status("弹幕已断开")
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.data(model.index(0), ChatModel.KindRole), "status")


class Trimming(unittest.TestCase):
    def test_trim_keeps_only_the_tail(self):
        model, _clock = make_model()
        total = MAX_MESSAGES + 120
        for i in range(total):
            model.append("u", f"msg-{i}")
        count = model.rowCount()
        self.assertLessEqual(count, MAX_MESSAGES)
        self.assertGreaterEqual(count, KEEP_MESSAGES)
        first_kept = total - count
        self.assertEqual(
            model.data(model.index(0), ChatModel.ContentRole), f"msg-{first_kept}")

    def test_clear_resets_count_and_zebra(self):
        model, _clock = make_model()
        model.append("u", "a")
        model.append("u", "b")
        model.clear()
        self.assertEqual(model.rowCount(), 0)
        model.append("u", "c")
        self.assertFalse(model.data(model.index(0), ChatModel.AltRole))


class EntranceAnimation(unittest.TestCase):
    def test_only_the_recent_tail_animates(self):
        model, clock = make_model()
        for i in range(20):
            model.append("u", f"msg-{i}")
        rows = model.animating_rows(clock.now + 50)
        self.assertEqual([row for row, _ in rows], list(range(12, 20)))
        for _, progress in rows:
            self.assertAlmostEqual(progress, 50 / 180, places=2)

    def test_animation_window_closes(self):
        model, clock = make_model()
        model.append("u", "msg")
        self.assertEqual(model.animating_rows(clock.now + 180), [])

    def test_later_appends_restart_only_their_own_window(self):
        model, clock = make_model()
        model.append("u", "old")
        clock.now = 1000
        model.append("u", "new")
        rows = model.animating_rows(1050)
        self.assertEqual([row for row, _ in rows], [1])


if __name__ == "__main__":
    unittest.main()
