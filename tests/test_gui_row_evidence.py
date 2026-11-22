"""The detail pane shows why a row is a target, and a manual include/exclude choice is saved and visible."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


class RowEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'source').mkdir()
        entries = [
            Entry('DefInjected:ThingDef:A.label', 'DefInjected', 'ThingDef', 'A.label', 'Gun', 'Defs/a.xml', confidence='schema',
                  evidence=['CLR Verse.ThingDef.label: MustTranslateAttribute'], reasons=['must-translate', 'official-pattern']),
            Entry('DefInjected:ThingDef:B.label', 'DefInjected', 'ThingDef', 'B.label', 'Rifle', 'Defs/a.xml'),
            Entry('Keyed:Keyed:K', 'Keyed', 'Keyed', 'K', 'Hello', 'Keyed/k.xml', confidence='catalog', reasons=['keyed']),
        ]
        project = Project(str(root / 'source'), 'P', 'local.p', 'demo.p', ['1.6'], entries, [], languages=['Japanese'])
        self.path = root / 'workspace/project.json'
        project.save(self.path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.settings.data['ui_language'] = 'en'
        self.window.ui_language = 'en'
        self.window.load_project(self.path)
        self.window.show()
        self.addCleanup(self.close)

    def close(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def select(self, entry_id):
        row = self.window.model.row_for_id[entry_id]
        self.window.table.setCurrentIndex(self.window.proxy.mapFromSource(self.window.model.index(row, 0)))
        self.app.processEvents()

    def test_detail_pane_lists_the_machine_readable_reasons(self):
        self.select('DefInjected:ThingDef:A.label')
        details = self.window.notice_details.toPlainText()
        self.assertIn('must-translate', details)
        self.assertIn('official-pattern', details)
        self.assertIn('MustTranslate', details)  # the reason's plain wording, not only its code

    def test_detail_pane_has_no_reason_block_for_rows_saved_without_reasons(self):
        self.select('DefInjected:ThingDef:B.label')
        self.assertNotIn('Why', self.window.notice_details.toPlainText())

    def test_table_tooltip_lists_the_reasons(self):
        row = self.window.model.row_for_id['Keyed:Keyed:K']
        tip = self.window.model.data(self.window.model.index(row, 1), Qt.ToolTipRole)
        self.assertIn('keyed', tip)

    def pick(self, position):
        return patch('rimworld_translator.gui_tools.QInputDialog.getItem',
                     side_effect=lambda *args, **kwargs: (args[3][position], True))

    def test_classification_is_saved_shown_and_not_stacked(self):
        self.select('DefInjected:ThingDef:B.label')
        for _ in range(2):
            with self.pick(0):
                self.window.classify_current()
        details = self.window.notice_details.toPlainText()
        self.assertEqual(details.count('User classification'), 1)
        self.assertIn('verified', self.window.notice.toPlainText() + details)
        self.assertTrue(self.window.save(export=False))
        saved = Project.load(self.path).entry_index()['DefInjected:ThingDef:B.label']
        self.assertEqual(saved.classification, 'verified')

    def test_manual_exclusion_is_saved_marked_in_the_table_and_filterable(self):
        self.select('DefInjected:ThingDef:B.label')
        self.window.exclude_current()
        self.assertTrue(self.window.save(export=False))
        saved = Project.load(self.path).entry_index()['DefInjected:ThingDef:B.label']
        self.assertTrue(saved.excluded)
        row = self.window.model.row_for_id['DefInjected:ThingDef:B.label']
        marker = self.window.model.data(self.window.model.index(row, 4), Qt.DisplayRole)
        self.assertIn('⊘', marker)
        other = self.window.model.row_for_id['DefInjected:ThingDef:A.label']
        self.assertNotIn('⊘', self.window.model.data(self.window.model.index(other, 4), Qt.DisplayRole))
        self.window.status_filter.setCurrentIndex(self.window.status_filter.findData('excluded'))
        self.assertEqual(self.window.proxy.rowCount(), 1)

    def test_excluded_rows_stay_excluded_after_a_rescan_merge(self):
        self.select('DefInjected:ThingDef:B.label')
        self.window.exclude_current()
        project = self.window.project
        from rimworld_translator.core import Scan
        fresh = Scan(entries=[Entry(e.id, e.kind, e.group, e.key, e.english, e.source_file) for e in project.entries],
                     package_id=project.original_package_id, versions=list(project.versions))
        project.rescan(fresh)
        self.assertTrue(project.entry_index()['DefInjected:ThingDef:B.label'].excluded)


if __name__ == '__main__':
    unittest.main()
