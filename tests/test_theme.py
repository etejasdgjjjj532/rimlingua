import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import re
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from rimworld_translator.gui import Window
from rimworld_translator.settings import SettingsStore
from rimworld_translator.theme import PALETTES, resolve_mode, stylesheet


class ThemeTokenTests(unittest.TestCase):
    def test_both_palettes_define_the_same_tokens(self):
        self.assertEqual(set(PALETTES['light']), set(PALETTES['dark']))

    def test_stylesheets_have_no_unresolved_placeholders_and_differ(self):
        light, dark = stylesheet('light', 11), stylesheet('dark', 11)
        self.assertNotRegex(light + dark, r'@\w+@')
        self.assertNotEqual(light, dark)
        self.assertIn('11pt', light)
        self.assertIn('15pt', stylesheet('light', 15))

    def test_system_mode_follows_the_system_scheme(self):
        self.assertEqual(resolve_mode('system', True), 'dark')
        self.assertEqual(resolve_mode('system', False), 'light')
        self.assertEqual(resolve_mode('light', True), 'light')
        self.assertEqual(resolve_mode('dark', False), 'dark')

    def test_text_is_readable_in_both_modes(self):
        def luminance(value):
            r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
            f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
            return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)
        def contrast(a, b):
            high, low = sorted((luminance(a), luminance(b)), reverse=True)
            return (high + .05) / (low + .05)
        for mode, tokens in PALETTES.items():
            for foreground, background in (('text', 'window'), ('text', 'panel'), ('text', 'input'),
                                           ('muted', 'window'), ('accent_text', 'accent'),
                                           ('sidebar_text', 'sidebar'), ('sidebar_muted', 'sidebar'),
                                           ('selection_text', 'selection'), ('ok', 'panel'), ('warn', 'panel'),
                                           ('info', 'panel'), ('ok', 'status'), ('ok', 'row_alt'), ('warn', 'row_alt'), ('info', 'row_alt')):
                self.assertGreaterEqual(contrast(tokens[foreground], tokens[background]), 4.5,
                                        f'{mode}: {foreground} on {background}')
            # WCAG 1.4.11: input boundaries and the focus indicator need 3:1 against adjacent colours.
            for foreground in ('input_border', 'accent'):
                for background in ('window', 'panel', 'input', 'raised'):
                    self.assertGreaterEqual(contrast(tokens[foreground], tokens[background]), 3,
                                            f'{mode}: {foreground} against {background}')

    def test_each_mode_keeps_one_tone_including_the_sidebar(self):
        def luminance(value):
            r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
            return .2126 * r + .7152 * g + .0722 * b
        self.assertGreater(luminance(PALETTES['light']['sidebar']), .8)   # no dark rail in the light mode
        self.assertLess(luminance(PALETTES['dark']['sidebar']), .2)

    def test_type_scale_has_three_sizes_and_a_readable_minimum(self):
        import re
        for font in (9, 11, 15):
            sizes = set(re.findall(r'font-size:(\d+)pt', stylesheet('light', font)))
            self.assertLessEqual(len(sizes), 3, sizes)
            self.assertGreaterEqual(min(map(int, sizes)), 9)  # 9pt = 12px, the smallest legible regular text


class ThemeSettingsTests(unittest.TestCase):
    def test_default_and_invalid_values_fall_back_to_system(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 's.json'
            self.assertEqual(SettingsStore(path).data['theme_mode'], 'system')
            path.write_text('{"theme_mode": "neon"}')
            self.assertEqual(SettingsStore(path).data['theme_mode'], 'system')
            path.write_text('{"theme_mode": "dark"}')
            self.assertEqual(SettingsStore(path).data['theme_mode'], 'dark')


class ThemeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        window = Window(settings_path=Path(temp.name) / 's.json')
        window.settings.data['inspect_metadata'] = False
        window.show()
        self.app.processEvents()
        def close():
            window.dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(close)
        return window

    def test_switching_mode_restyles_and_persists(self):
        window = self.make_window()
        window.set_theme_mode('dark', persist=False)
        dark_sheet = window.styleSheet()
        window.set_theme_mode('light', persist=False)
        self.assertNotEqual(window.styleSheet(), dark_sheet)
        self.assertIn(PALETTES['light']['panel'], window.styleSheet())
        self.assertEqual(window.settings.data['theme_mode'], 'light')
        with self.assertRaises(ValueError):
            window.set_theme_mode('purple')

    def test_toggle_and_menu_reflect_the_current_mode(self):
        window = self.make_window()
        window.set_theme_mode('light', persist=False)
        window.toggle_theme()
        self.assertEqual(window.settings.data['theme_mode'], 'dark')
        checked = [value for action, value in window.theme_actions.items() if action.isChecked()]
        self.assertEqual(checked, ['dark'])

    def test_font_size_change_keeps_the_theme(self):
        window = self.make_window()
        window.set_theme_mode('dark', persist=False)
        window.set_editor_font(14, persist=False)
        self.assertIn('14pt', window.styleSheet())
        self.assertEqual(window.theme_mode_resolved, 'dark')


if __name__ == '__main__':
    unittest.main()
