"""Check boxes and radio buttons must draw a visible indicator in both themes (they were invisible)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtWidgets import QApplication, QCheckBox, QRadioButton, QVBoxLayout, QWidget

from rimworld_translator.theme import PALETTES, stylesheet


class IndicatorStyleTests(unittest.TestCase):
    def test_stylesheet_has_indicator_rules_without_leftover_placeholders(self):
        for mode in ('light', 'dark'):
            text = stylesheet(mode, 11)
            for rule in ('QCheckBox::indicator', 'QRadioButton::indicator', 'QCheckBox::indicator:checked',
                         'QCheckBox::indicator:disabled', 'QCheckBox::indicator:hover',
                         'QRadioButton::indicator:checked', 'QAbstractItemView::indicator'):
                self.assertIn(rule, text, f'{mode}: {rule}')
            self.assertIn('image:url(', text)
            self.assertNotRegex(text, r'@\w+@')


class IndicatorRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def grab_indicator(self, mode, cls, checked):
        page = QWidget()
        page.setStyleSheet(stylesheet(mode, 11))
        layout = QVBoxLayout(page)
        box = cls('x')
        box.setChecked(checked)
        layout.addWidget(box)
        page.resize(120, 40)
        page.show()
        self.app.processEvents()
        # the indicator sits at the left edge of the button: crop a 16x16 area next to it
        image = box.grab().toImage().copy(0, 0, 16, box.height())
        page.close()
        return image

    def pixels(self, image):
        return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}

    def test_unchecked_indicator_is_drawn_and_differs_from_checked(self):
        for mode in ('light', 'dark'):
            for cls in (QCheckBox, QRadioButton):
                with self.subTest(mode=mode, widget=cls.__name__):
                    off = self.grab_indicator(mode, cls, False)
                    on = self.grab_indicator(mode, cls, True)
                    self.assertNotEqual(off, on)
                    # unchecked: border and fill both show up, not just the page background
                    self.assertGreaterEqual(len(self.pixels(off)), 2)
                    # checked: the accent fill is present
                    self.assertIn(PALETTES[mode]['accent'].lower(), self.pixels(on))
                    self.assertNotIn(PALETTES[mode]['accent'].lower(), self.pixels(off))


if __name__ == '__main__':
    unittest.main()
