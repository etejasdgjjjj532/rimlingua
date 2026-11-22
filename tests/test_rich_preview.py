import unittest

from rimworld_translator.preview import Span, rich_text_html, rich_text_model


class RichTextModelTests(unittest.TestCase):
    def test_color_nesting_and_line_breaks(self):
        lines = rich_text_model('Hit <color=#ff0000>{0}</color>\\n<b>done</b>')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], [Span('Hit '), Span('{0}', color='#ff0000', token=True)])
        self.assertEqual(lines[1], [Span('done', bold=True)])

    def test_real_newlines_and_br(self):
        self.assertEqual(len(rich_text_model('a\nb<br>c')), 3)

    def test_named_and_short_hex_colors(self):
        self.assertEqual(rich_text_model('<color=red>x</color>')[0][0].color, '#ff0000')
        self.assertEqual(rich_text_model('<color=#f00>x</color>')[0][0].color, '#ff0000')
        self.assertEqual(rich_text_model('<color=#11223344>x</color>')[0][0].color, '#112233')
        self.assertEqual(rich_text_model('<color=nonsense>x</color>')[0][0].color, '')

    def test_unknown_tags_and_unclosed_tags_do_not_break(self):
        lines = rich_text_model('<unknown>x <i>y')
        self.assertEqual(''.join(span.text for span in lines[0]), '<unknown>x y')
        self.assertTrue(lines[0][-1].italic)

    def test_html_escapes_and_styles(self):
        html = rich_text_html('<color=red>a<b</color>\\nb')
        self.assertIn('color:#ff0000', html)
        self.assertIn('&lt;', html)
        self.assertIn('<br>', html)


if __name__ == '__main__':
    unittest.main()
