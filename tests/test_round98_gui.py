"""Closed diagnostic windows release retained candidate widgets and saved state."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QListWidget
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class DiagnosticDialogLifetimeTests(unittest.TestCase):
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
        candidate = dict(code='unknown-field', message='Retained unverified candidate',
                         owner_type='Unknown.Owner', source_file='Defs/Panel.xml',
                         field_path='Panel.tooltipText', source_text='x' * 100_000,
                         entry_id=entry.id)
        self.path = root / 'work/project.json'
        Project.create(source, Scan(entries=[entry], diagnostics=[candidate])).save(self.path)
        self.window = Window(settings_path=root / 'settings.json')
        self.window.load_project(self.path)
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_repeated_rejected_modal_windows_release_widgets_without_changing_saved_work(self):
        before = self.path.read_bytes()
        diagnostics = copy.deepcopy(self.window.project.diagnostics)
        initial = len(self.window.findChildren(QDialog))
        for _ in range(3):
            QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
            self.window.show_warnings()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(len(self.window.findChildren(QDialog)), initial,
                             'Closed diagnostic widgets and full retained candidate data must be released')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.window.project.diagnostics, diagnostics)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.path)
        self.assertEqual(restored.entries[0].japanese, '保存済みパネル')
        self.assertTrue(restored.entries[0].approved)
        self.assertTrue(restored.entries[0].reviewed)
        self.assertEqual(restored.diagnostics, diagnostics)

    def test_translation_navigation_also_releases_closed_diagnostic_window(self):
        entry = self.window.project.entries[0]
        self.window.project.diagnostics = [dict(code='qa', message='Confirmed translation entry', entry_id=entry.id)]
        initial = len(self.window.findChildren(QDialog))
        def navigate_from_modal():
            dialog = QApplication.activeModalWidget()
            listing = dialog.findChild(QListWidget)
            listing.itemDoubleClicked.emit(listing.currentItem())
        with patch.object(self.window, 'navigate_entry') as navigate:
            QTimer.singleShot(0, navigate_from_modal)
            self.window.show_warnings()
            navigate.assert_called_once_with(entry.id)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(len(self.window.findChildren(QDialog)), initial,
                         'Accepting diagnostics by navigation must release the same retained widgets')
