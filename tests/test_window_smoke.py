import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import app as app_module

_qapp = None


def qapp():
    global _qapp
    if _qapp is None:
        _qapp = QApplication.instance() or QApplication([])
    return _qapp


class WindowSmoke(unittest.TestCase):
    def setUp(self):
        qapp()
        self._saved_load = app_module.load_config
        self._saved_save = app_module.save_config
        app_module.load_config = lambda: {}
        app_module.save_config = lambda cfg: None
        self.window = app_module.PlayerWindow()

    def tearDown(self):
        self.window.mpv.stop()
        self.window.close()
        app_module.load_config = self._saved_load
        app_module.save_config = self._saved_save

    def test_idle_page_shows_and_overlay_stays_hidden(self):
        self.window.show()
        self.window.idle_page.sync()
        self.window.idle_page.show()
        self.assertTrue(self.window.idle_page.isVisible())
        self.assertFalse(self.window.overlay.isVisible())

    def test_play_without_room_only_warns(self):
        self.window.play()
        self.assertEqual(self.window.overlay.status.text(), "请输入房间号")
        self.assertFalse(self.window.fetching)

    def test_global_edge_detection_matches_the_frame(self):
        self.window.show()
        QApplication.processEvents()
        frame = self.window.frameGeometry()
        self.assertIsNone(self.window.edge_at_global(frame.center()))
        self.assertEqual(
            self.window.edge_at_global(QPoint(frame.left() + 1, frame.center().y())),
            Qt.LeftEdge)
        self.assertEqual(
            self.window.edge_at_global(QPoint(frame.right() - 1, frame.top() + 1)),
            Qt.RightEdge | Qt.TopEdge)
        outside = frame.topLeft() - QPoint(20, 20)
        self.assertIsNone(self.window.edge_at_global(outside))

    def test_volume_label_follows_the_slider(self):
        self.window.overlay.volume.setValue(42)
        self.assertEqual(self.window.overlay.volume_label.text(), "42%")

    def test_stop_returns_to_the_idle_page(self):
        self.window.stop()
        self.assertEqual(self.window.current_room, "")
        self.assertTrue(self.window.idle_page.wanted)

    def test_danmaku_toggle_hides_and_shows_the_dock(self):
        self.window.show()
        self.assertTrue(self.window.chat_dock.isVisible())
        self.window.toggle_danmaku()
        self.assertFalse(self.window.chat_dock.isVisible())
        self.window.toggle_danmaku()
        self.assertTrue(self.window.chat_dock.isVisible())

    def test_fullscreen_moves_the_panel_into_an_overlay(self):
        self.window.show()
        self.window.toggle_fullscreen()
        self.assertTrue(self.window.isFullScreen())
        self.assertFalse(self.window.chat_dock.isVisible())
        self.assertTrue(self.window.chat_overlay.isVisible())
        self.window.toggle_fullscreen()
        self.assertTrue(self.window.chat_dock.isVisible())
        self.assertFalse(self.window.chat_overlay.isVisible())

    def test_incoming_danmaku_lands_in_the_shared_model(self):
        self.window.show()
        self.window._append_danmaku("夜刃", "你好")
        self.window._append_danmaku("夜刃", "第二条")
        self.assertEqual(self.window.chat_model.rowCount(), 2)
        self.assertEqual(self.window.chat_dock.count.text(), "2")

    def test_theme_toggle_swaps_the_active_palette(self):
        qapp = QApplication.instance()
        self.window.toggle_theme()
        self.assertIs(self.window.theme, app_module.THEMES["light"])
        self.assertIn(app_module.THEMES["light"]["colors"]["bg"], qapp.styleSheet())
        self.window.toggle_theme()
        self.assertIs(self.window.theme, app_module.THEMES["dark"])
        self.assertIn(app_module.THEMES["dark"]["colors"]["bg"], qapp.styleSheet())

    def test_close_goes_to_tray_unless_quit_was_requested(self):
        self.window.show()
        self.window.close()
        self.assertTrue(self.window.isHidden())
        self.assertFalse(self.window._quitting)
        self.window.tray_exit()
        self.assertTrue(self.window._quitting)

    def test_shortcut_sheet_toggles(self):
        self.window.show()
        self.window.toggle_shortcuts()
        self.assertTrue(self.window.shortcut_sheet.isVisible())
        self.window.toggle_shortcuts()
        self.assertFalse(self.window.shortcut_sheet.isVisible())


class EdgeResizeRouting(unittest.TestCase):
    """边缘按压落在原生子窗口/浮层上时，也必须发起系统缩放。"""

    def setUp(self):
        qapp()
        self._saved_load = app_module.load_config
        self._saved_save = app_module.save_config
        app_module.load_config = lambda: {}
        app_module.save_config = lambda cfg: None
        self.window = app_module.PlayerWindow()
        self.window.show()
        QApplication.processEvents()
        self.edges = []
        self.window.request_resize = self.edges.append

    def tearDown(self):
        self.window.mpv.stop()
        self.window.close()
        app_module.load_config = self._saved_load
        app_module.save_config = self._saved_save

    def press_at(self, point, target):
        local = target.mapFromGlobal(point)
        event = QMouseEvent(QEvent.MouseButtonPress, local, point,
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target, event)

    def test_left_edge_press_over_the_video_child_resizes(self):
        frame = self.window.frameGeometry()
        self.press_at(QPoint(frame.left() + 2, frame.center().y()),
                      self.window.video_host)
        self.assertEqual(self.edges, [Qt.LeftEdge])

    def test_right_edge_press_over_the_dock_resizes(self):
        frame = self.window.frameGeometry()
        self.press_at(QPoint(frame.right() - 2, frame.center().y()),
                      self.window.chat_dock)
        self.assertEqual(self.edges, [Qt.RightEdge])

    def test_bottom_edge_press_resizes(self):
        frame = self.window.frameGeometry()
        self.press_at(QPoint(frame.center().x(), frame.bottom() - 2),
                      self.window.video_host)
        self.assertEqual(self.edges, [Qt.BottomEdge])

    def test_bottom_right_corner_wins_over_edges(self):
        frame = self.window.frameGeometry()
        self.press_at(QPoint(frame.right() - 2, frame.bottom() - 2),
                      self.window.video_host)
        self.assertEqual(self.edges, [Qt.RightEdge | Qt.BottomEdge])

    def test_press_in_the_middle_does_not_resize(self):
        frame = self.window.frameGeometry()
        self.press_at(frame.center(), self.window.video_host)
        self.assertEqual(self.edges, [])

    def test_maximized_window_ignores_edge_presses(self):
        frame = self.window.frameGeometry()
        self.window.isMaximized = lambda: True
        self.press_at(QPoint(frame.left() + 2, frame.center().y()),
                      self.window.video_host)
        self.assertEqual(self.edges, [])


if __name__ == "__main__":
    unittest.main()
