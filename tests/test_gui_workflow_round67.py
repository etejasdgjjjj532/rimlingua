"""Grammar rule guidance and blocking QA stay visible without discarding edits."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit
from rimworld_translator.core import Entry, Project, Scan, export_mod
from rimworld_translator.gui import Window


class GrammarEditorRound67Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        entry = Entry(id='DefInjected:ResearchProjectDef:ShipBasics.generalRules.rulesStrings.0',
                      kind='DefInjected', group='ResearchProjectDef',
                      key='ShipBasics.generalRules.rulesStrings.0',
                      english='subject->starship structural engineering',
                      source_file='Defs/Research.xml')
        scans = {version: Scan(entries=[entry], versions=['1.6', '1.10'], stats={'active_version': version})
                 for version in ('1.6', '1.10')}
        project = Project.create_versions(self.source, scans)
        self.ident = entry.id
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.window.load_project(self.saved)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_guidance_identifies_exact_prefix_and_errors_update_while_editing(self):
        window = self.window
        self.assertIn('subject->', window.notice.toPlainText())
        self.assertIn('右側', window.notice.toPlainText())
        for invalid in ('主題->宇宙船の構造工学', '宇宙船の構造工学'):
            window.japanese.setPlainText(invalid)
            self.app.processEvents()
            self.assertEqual(window.current.japanese, invalid)
            self.assertIn('QA エラー', window.notice.toPlainText())
            self.assertIn('試験出力', window.notice.toPlainText())
        window.japanese.setPlainText('subject->宇宙船の構造工学')
        self.app.processEvents()
        self.assertNotIn('QA エラー', window.notice.toPlainText())
        self.assertIn('subject->', window.notice.toPlainText())

    def test_gui_trial_omits_bad_rule_preserves_saved_edit_and_formal_rejects(self):
        window = self.window
        window.japanese.setPlainText('主題->宇宙船の構造工学')
        self.app.processEvents()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self.assertTrue(window.generate_versions_test())
        self.app.processEvents()
        restored = Project.load(self.saved)
        self.assertEqual(restored.entry_index()[self.ident].japanese, '主題->宇宙船の構造工学')
        output = self.saved.parent / 'mod-test'
        self.assertFalse(any(ET.parse(path).getroot().find('ShipBasics.generalRules.rulesStrings.0') is not None
                             for path in output.rglob('Translations.xml')))
        self.assertIn('rulesStrings', window.trial_output_report.findChild(QPlainTextEdit).toPlainText())
        single = Project.create(self.source, Scan(entries=restored.entries))
        with self.assertRaisesRegex(ValueError, 'rulesStrings|文法|prefix|subject'):
            export_mod(single, self.root / 'formal')
        self.assertFalse((self.root / 'formal').exists())

    def test_legacy_internal_reference_is_read_only_and_old_translation_is_retained(self):
        window = self.window
        unsafe = Entry(id='DefInjected:SaveOurShip2.ShipDef:Example.core.shapeOrDef',
                       kind='DefInjected', group='SaveOurShip2.ShipDef',
                       key='Example.core.shapeOrDef', english='ShipConsoleTactical',
                       source_file='Defs/Ships.xml', japanese='保存済みの旧訳', approved=True)
        project = Project.create(self.source, Scan(entries=[unsafe]))
        saved = self.root / 'legacy/project.json'
        project.save(saved)
        window.load_project(saved)
        self.app.processEvents()
        self.assertTrue(window.japanese.isReadOnly())
        self.assertIn('内部', window.model.data(window.model.index(0, 0)))
        self.assertEqual(window.progress.value(), 0)
        index = window.model.index(0, 3)
        self.assertFalse(window.model.flags(index) & Qt.ItemIsEditable)
        self.assertFalse(window.model.setData(index, '変更しない'))
        self.assertEqual(window.current.japanese, '保存済みの旧訳')
        self.assertIn('内部', window.notice.toPlainText())
        self.assertIn('出力', window.notice.toPlainText())
        self.assertTrue(window.save(export=False))
        self.assertEqual(Project.load(saved).entries[0].japanese, '保存済みの旧訳')
        window.scan_finished(self.source, None, None, 'cancelled')
        self.assertTrue(window.japanese.isReadOnly(), 'Cancelled scans must retain the internal-data edit lock')
        window.declared_scan_finished(None, 'cancelled')
        self.assertTrue(window.japanese.isReadOnly(), 'Cancelled declared scans must retain the edit lock')

    def test_custom_clr_owner_keeps_visible_unlock_text_editable(self):
        window = self.window
        visible = Entry(id='DefInjected:ThingDef:Visible.comps.0.unlock',
                        kind='DefInjected', group='ThingDef', key='Visible.comps.0.unlock',
                        english='Unlock this achievement', source_file='Defs/Visible.xml',
                        confidence='schema', evidence=['CLR Example.VisibleComp.unlock: MustTranslateAttribute'])
        project = Project.create(self.source, Scan(entries=[visible]))
        saved = self.root / 'visible/project.json'
        project.save(saved)
        window.load_project(saved)
        self.app.processEvents()
        self.assertFalse(window.japanese.isReadOnly())
        index = window.model.index(0, 3)
        self.assertTrue(window.model.flags(index) & Qt.ItemIsEditable)
        self.assertTrue(window.model.setData(index, '実績を解除する'))
        self.assertEqual(window.current.japanese, '実績を解除する')
