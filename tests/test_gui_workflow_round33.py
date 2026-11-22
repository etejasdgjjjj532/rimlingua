"""A real sharing dialog requires a per-version selection before copying text."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QListWidget, QPlainTextEdit, QPushButton
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class GuiSharingRound33Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        (source / 'About').mkdir(parents=True)
        (source / 'About/About.xml').write_text('<ModMetaData><packageId>test.sharegui</packageId>'
            '<supportedVersions><li>1.6</li><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>')
        keyed = source / 'Languages/English/Keyed/a.xml'
        keyed.parent.mkdir(parents=True)
        keyed.write_text('<LanguageData><Greeting>Hello</Greeting></LanguageData>')
        project = Project.create_versions(source, {version: scan_mod(source, game_version=version)
                                                   for version in ('1.6', '1.9', '1.10')})
        self.saved = self.root / 'workspace/project.json'
        project.save(self.saved)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.addCleanup(self.close_window)
        self.window.load_project(self.saved)
        self.identity = 'Keyed:Keyed:Greeting'

    def close_window(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_dialog_copies_only_selected_version_and_retains_source_edit_and_review(self):
        button = self.window.findChild(QPushButton, 'shareTranslation')
        self.assertIsNotNone(button, 'The editor must expose explicit cross-version sharing')
        self.window.japanese.setPlainText('編集中の挨拶')
        self.window.mark_reviewed(approved=True)
        undo_record = object()
        self.window.undo_batches[:] = [undo_record]
        disk = self.saved.read_bytes()
        observed = {}
        def approve():
            dialog = self.window.findChild(QDialog, 'translationSharing')
            choices = dialog.findChild(QListWidget)
            observed['versions'] = [choices.item(i).data(Qt.UserRole) for i in range(choices.count())]
            observed['initial'] = [choices.item(i).checkState() for i in range(choices.count())]
            choices.item(1).setCheckState(Qt.Checked)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(0, approve)
        button.click()
        self.assertEqual(observed['versions'], ['1.9', '1.10'])
        self.assertEqual(observed['initial'], [Qt.Unchecked, Qt.Unchecked])
        self.assertEqual(self.window.project.game_version, '1.6')
        self.assertEqual(self.window.japanese.toPlainText(), '編集中の挨拶')
        self.assertTrue(self.window.current.approved)
        self.assertTrue(self.window.dirty)
        self.assertEqual(self.window.undo_batches, [undo_record])
        self.assertEqual(self.saved.read_bytes(), disk)
        self.assertTrue(self.window.save(export=False))
        restored = Project.load(self.saved)
        restored.switch_version('1.10')
        self.assertEqual(restored.get_translation(self.identity), '編集中の挨拶')
        self.assertFalse(restored.entry_index()[self.identity].approved)
        restored.switch_version('1.9')
        self.assertEqual(restored.get_translation(self.identity), '')

    def test_cancel_and_empty_selection_never_copy_and_busy_disables_sharing(self):
        button = self.window.findChild(QPushButton, 'shareTranslation')
        self.assertIsNotNone(button, 'The editor must expose explicit cross-version sharing')
        self.window.japanese.setPlainText('挨拶')
        self.window.dirty = False
        def cancel():
            dialog = self.window.findChild(QDialog, 'translationSharing')
            self.assertFalse(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled())
            dialog.reject()
        QTimer.singleShot(0, cancel)
        button.click()
        self.assertFalse(self.window.dirty)
        for version in ('1.9', '1.10'):
            self.assertEqual(self.window.project._version_view(version).get_translation(self.identity), '')
        self.window.busy = True
        self.window.set_project_controls(False)
        self.assertFalse(button.isEnabled())
        self.window.busy = False
        self.window.set_project_controls(True)
        self.assertTrue(button.isEnabled())

    def test_long_translation_can_scroll_without_hiding_confirmation_controls(self):
        button = self.window.findChild(QPushButton, 'shareTranslation')
        self.assertIsNotNone(button)
        self.window.japanese.setPlainText('長い文章\n' * 300)
        observed = {}
        def inspect():
            dialog = self.window.findChild(QDialog, 'translationSharing')
            detail = dialog.findChild(QPlainTextEdit)
            observed['scrollable'] = detail is not None and detail.verticalScrollBar().maximum() > 0
            observed['fits'] = dialog.height() <= dialog.screen().availableGeometry().height()
            dialog.reject()
        QTimer.singleShot(0, inspect)
        button.click()
        self.assertTrue(observed['scrollable'])
        self.assertTrue(observed['fits'])
