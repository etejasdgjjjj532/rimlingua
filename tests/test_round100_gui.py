"""A retained source match crossing a preview boundary remains inspectable."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticBoundaryMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'
        source.mkdir()
        entry = Entry(id='DefInjected:ThingDef:Panel.label', kind='DefInjected', group='ThingDef',
                      key='Panel.label', english='panel', source_file='Defs/Panel.xml',
                      japanese='保存済みパネル', approved=True, reviewed=True)
        self.path = root / 'work/project.json'
        Project.create(source, Scan(entries=[entry])).save(self.path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def check_boundary(self, prefix, source_match, query):
        text = prefix + source_match + 'z' * 10000
        self.window.project.diagnostics = [dict(
            code='unknown-field', message='Retained candidate', source_file='Defs/Panel.xml',
            owner_type='Unknown.Owner', field_path='Panel.tooltipText', source_text=text,
            entry_id=self.window.project.entries[0].id)]
        self.window.save(export=False)
        before = self.path.read_bytes()
        diagnostics = copy.deepcopy(self.window.project.diagnostics)
        errors = []
        def inspect():
            dialog = QApplication.activeModalWidget()
            try:
                search = dialog.findChild(QLineEdit, 'diagnosticSearch')
                detail = dialog.findChild(QPlainTextEdit, 'diagnosticDetail')
                status = dialog.findChild(QLabel, 'diagnosticSourcePageStatus')
                jump = dialog.findChild(QPushButton, 'diagnosticSourceMatchPage')
                search.setText(query)
                self.assertEqual(dialog.findChild(QListWidget).count(), 1)
                self.assertNotIn(source_match, detail.toPlainText())
                self.assertTrue(jump.isEnabled())
                jump.click()
                self.assertIn(source_match, detail.toPlainText(),
                              'A cross-boundary match must be visible together in the bounded source preview')
                self.assertIn(f'{len(prefix) + 1}–{len(prefix) + 4096}', status.text())
                self.assertLess(len(detail.toPlainText()), 5000)
                self.assertTrue(detail.isReadOnly())
                following = dialog.findChild(QPushButton, 'diagnosticSourceNextPage')
                previous = dialog.findChild(QPushButton, 'diagnosticSourcePreviousPage')
                following.click()
                self.assertIn(f'{len(prefix) + 4097}–{len(prefix) + 8192}', status.text())
                previous.click()
                self.assertIn(source_match, detail.toPlainText())
                previous.click()
                self.assertIn('1–4096', status.text())
                self.assertFalse(previous.isEnabled())
                jump.click()
                self.assertIn(source_match, detail.toPlainText())
                search.clear()
                self.assertIn('1–4096', status.text())
                self.assertFalse(jump.isEnabled())
            except BaseException as error:
                errors.append(error)
            finally:
                dialog.reject()
        QTimer.singleShot(0, inspect)
        self.window.show_warnings()
        if errors:
            raise errors[0]
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.window.project.diagnostics, diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.diagnostics, diagnostics)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)

    def test_cross_boundary_match_is_visible_without_changing_saved_translation(self):
        self.check_boundary('x' * 4094, 'BoundaryWord', 'boundaryword')

    def test_cross_boundary_casefold_match_maps_original_unicode_positions(self):
        self.check_boundary('ß' * 4093, 'Straße' + chr(0x1F680), 'STRASSE' + chr(0x1F680))
