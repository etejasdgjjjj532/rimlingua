"""Submitting a diagnostic search must not activate unrelated page controls."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QListWidget, QPushButton
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticSearchKeyboardTests(unittest.TestCase):
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
        diagnostics = [dict(code='unknown-field', message=f'candidate {i}',
                            source_file='Defs/Panel.xml', owner_type='Unknown.Owner',
                            field_path=f'Panel.tooltipText{i}', source_text='x' * 8192,
                            entry_id=entry.id) for i in range(1501)]
        self.path = root / 'work/project.json'
        Project.create(source, Scan(entries=[entry], diagnostics=diagnostics)).save(self.path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def inspect_modal(self, callback):
        errors = []
        def inspect():
            dialog = QApplication.activeModalWidget()
            try:
                callback(dialog)
            except BaseException as error:
                errors.append(error)
            finally:
                dialog.reject()
        QTimer.singleShot(0, inspect)
        self.window.show_warnings()
        if errors:
            raise errors[0]

    def test_search_return_and_keypad_enter_preserve_diagnostic_and_source_page_and_saved_work(self):
        before = self.path.read_bytes()
        diagnostics = copy.deepcopy(self.window.project.diagnostics)
        def check(dialog):
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            search.setText('candidate')
            dialog.findChild(QPushButton, 'diagnosticNextPage').click()
            dialog.findChild(QPushButton, 'diagnosticSourceNextPage').click()
            search.setFocus()
            self.app.processEvents()
            self.assertTrue(search.hasFocus())
            status = dialog.findChild(QLabel, 'diagnosticPageStatus')
            source_status = dialog.findChild(QLabel, 'diagnosticSourcePageStatus')
            listing = dialog.findChild(QListWidget)
            self.assertIn('1501–1501', status.text())
            self.assertIn('4097–8192', source_status.text())
            for key in (Qt.Key_Return, Qt.Key_Enter):
                QTest.keyClick(search, key)
                self.assertIn('1501–1501', status.text(),
                              'Submitting search must not activate the dialog default Previous page button')
                self.assertIn('4097–8192', source_status.text())
                # The list shows the plain-language title; the raw diagnostic stays on the item.
                self.assertEqual(listing.currentItem().data(Qt.UserRole + 1)['message'], 'candidate 1500')
                self.assertTrue(dialog.isVisible())
        self.inspect_modal(check)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.window.project.diagnostics, diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)
        self.assertEqual(restored.diagnostics, diagnostics)

    def test_page_button_return_and_search_escape_remain_available(self):
        def check(dialog):
            dialog.findChild(QPushButton, 'diagnosticNextPage').click()
            previous = dialog.findChild(QPushButton, 'diagnosticPreviousPage')
            previous.setFocus()
            QTest.keyClick(previous, Qt.Key_Return)
            self.assertIn('1–1500', dialog.findChild(QLabel, 'diagnosticPageStatus').text())
            search = dialog.findChild(QLineEdit, 'diagnosticSearch')
            search.setFocus()
            QTest.keyClick(search, Qt.Key_Escape)
            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.result(), QDialog.Rejected)
        self.inspect_modal(check)
