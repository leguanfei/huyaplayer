import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from theme import THEMES, qss, with_accent

COLOR_RE = re.compile(r"^(#[0-9a-f]{6}|rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\))$")
LEGACY_ACCENT = "#f5a623"
ALWAYS_THEMED = ("QToolTip", "QMenu", "QScrollBar")


class TokenContract(unittest.TestCase):
    def test_both_themes_share_the_same_keys(self):
        self.assertEqual(set(THEMES), {"dark", "light"})
        self.assertEqual(set(THEMES["dark"]), set(THEMES["light"]))

    def test_every_color_token_is_valid_css(self):
        for name, theme in THEMES.items():
            for key, value in theme["colors"].items():
                with self.subTest(theme=name, token=key):
                    self.assertRegex(value, COLOR_RE)

    def test_video_area_stays_black_in_both_themes(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertEqual(theme["colors"]["video_bg"], "#000000")

    def test_geometry_tokens_match_the_approved_design(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertEqual(theme["radius"], {"card": 10, "ctrl": 6, "pill": 999})
                self.assertEqual(theme["space"], (4, 8, 12, 16, 20, 24))
                self.assertEqual(theme["durations"],
                                 {"enter": 180, "fade_in": 140, "fade_out": 260,
                                  "idle_hide": 2000, "scroll": 120})

    def test_animation_only_drives_the_recent_tail(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertEqual(theme["chat_anim_tail"], 8)


class QssGeneration(unittest.TestCase):
    def test_qss_uses_the_theme_accent(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                sheet = qss(theme)
                self.assertIn(theme["colors"]["accent"], sheet)

    def test_qss_drops_the_legacy_accent_entirely(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertNotIn(LEGACY_ACCENT, qss(theme))

    def test_with_accent_replaces_every_accent_occurrence(self):
        sheet = qss(with_accent("dark", "#5b8cff"))
        self.assertIn("#5b8cff", sheet)
        self.assertNotIn(THEMES["dark"]["colors"]["accent"], sheet)

    def test_qss_covers_the_widgets_that_always_need_theming(self):
        for name, theme in THEMES.items():
            sheet = qss(theme)
            for selector in ALWAYS_THEMED:
                with self.subTest(theme=name, selector=selector):
                    self.assertIn(selector, sheet)

    def test_qss_is_a_single_string_of_balanced_blocks(self):
        for name, theme in THEMES.items():
            sheet = qss(theme)
            with self.subTest(theme=name):
                self.assertIsInstance(sheet, str)
                self.assertEqual(sheet.count("{"), sheet.count("}"))
                self.assertGreater(sheet.count("{"), 10)

    def test_logo_dot_color_comes_from_qss_not_hardcoded(self):
        for name, theme in THEMES.items():
            sheet = qss(theme)
            with self.subTest(theme=name):
                self.assertIn("#logoDot", sheet)
                block = sheet.split("#logoDot", 1)[1].split("}", 1)[0]
                self.assertIn(theme["colors"]["accent"], block)

    def test_chat_panel_chrome_is_themed_by_qss(self):
        for name, theme in THEMES.items():
            sheet = qss(theme)
            with self.subTest(theme=name):
                for selector in ("#chatGrip", "#jumpPill", "#hairline", "#chatCount",
                                 "#shortcutSheet", "#shortcutKey"):
                    self.assertIn(selector, sheet)
                pill = sheet.split("#jumpPill", 1)[1].split("}", 1)[0]
                self.assertIn(theme["colors"]["accent"], pill)


if __name__ == "__main__":
    unittest.main()
