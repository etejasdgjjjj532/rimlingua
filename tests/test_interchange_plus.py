"""Stronger CSV / PO exchange: detailed columns, Excel (Shift_JIS, semicolon) files, review flags, notes."""
import csv
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import notes, workflow
from rimworld_translator.core import Entry, Project


def keyed(key, english, japanese='', **flags):
    return Entry(f'Keyed:Keyed:{key}', 'Keyed', 'Keyed', key, english, 'Keyed/Main.xml', japanese, **flags)


def make(entries):
    return Project('/nonexistent/source', 'Example', 'local.translation.x', 'author.original', ['1.6'], entries, [])


class CsvTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)

    def test_detailed_export_adds_status_file_and_note(self):
        project = make([keyed('A', 'Alpha', 'あ', changed=True, previous_english='Old alpha'), keyed('B', 'Beta')])
        notes.set_note(project, 'Keyed:Keyed:A', 'check', 'later')
        workflow.export_csv(project, self.dir / 'x.csv', detailed=True)
        with (self.dir / 'x.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['status'], 'changed')
        self.assertEqual(rows[0]['source_file'], 'Keyed/Main.xml')
        self.assertEqual(rows[0]['previous_english'], 'Old alpha')
        self.assertEqual(rows[0]['note'], 'check')
        self.assertEqual(rows[1]['status'], 'untranslated')

    def test_plain_export_keeps_its_original_columns(self):
        workflow.export_csv(make([keyed('A', 'Alpha')]), self.dir / 'x.csv')
        header = (self.dir / 'x.csv').read_text(encoding='utf-8-sig').splitlines()[0]
        self.assertEqual(header, 'id,kind,group,key,english,translation,language')

    def test_detailed_export_round_trips_and_keeps_the_review_flag(self):
        project = make([keyed('A', 'Alpha', ''), keyed('B', 'Beta', '')])
        path = self.dir / 'in.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['id', 'english', 'translation', 'status'])
            writer.writerow(['Keyed:Keyed:A', 'Alpha', 'あ', 'needs-review'])
            writer.writerow(['Keyed:Keyed:B', 'Beta', 'べ', 'translated'])
        preview = workflow.preview_import(project, path)
        self.assertEqual({c.id: c.review for c in preview.changes}, {'Keyed:Keyed:A': True, 'Keyed:Keyed:B': False})

    def test_excel_shift_jis_semicolon_file(self):
        project = make([keyed('A', 'Alpha')])
        path = self.dir / 'excel.csv'
        path.write_bytes('id;translation\r\nKeyed:Keyed:A;あいう\r\n'.encode('cp932'))
        preview = workflow.preview_import(project, path)
        self.assertEqual([c.after for c in preview.changes], ['あいう'])
        self.assertTrue(any('Shift_JIS' in w for w in preview.warnings))

    def test_tab_separated_file(self):
        project = make([keyed('A', 'Alpha')])
        path = self.dir / 'x.csv'
        path.write_text('id\ttranslation\nKeyed:Keyed:A\tあ\n', encoding='utf-8')
        self.assertEqual([c.after for c in workflow.preview_import(project, path).changes], ['あ'])

    def test_rows_without_an_id_are_reported(self):
        project = make([keyed('A', 'Alpha')])
        path = self.dir / 'x.csv'
        path.write_text('id,translation\n,あ\n', encoding='utf-8')
        preview = workflow.preview_import(project, path)
        self.assertEqual(preview.changes, [])
        self.assertTrue(any('id' in w for w in preview.warnings))


class PoTests(unittest.TestCase):
    def test_notes_and_previous_english_are_written_as_comments(self):
        import polib
        project = make([keyed('A', 'New alpha', 'あ', changed=True, previous_english='Old alpha')])
        notes.set_note(project, 'Keyed:Keyed:A', '確認', 'later')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'x.po'
            workflow.export_po(project, path)
            item = polib.pofile(str(path))[0]
        self.assertIn('確認', item.tcomment)
        self.assertEqual(item.previous_msgid, 'Old alpha')
        self.assertIn('fuzzy', item.flags)


if __name__ == '__main__':
    unittest.main()
