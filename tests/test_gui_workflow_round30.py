"""Rejected refreshes report an error without discarding the open editor work."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Project, scan_mod
from rimworld_translator.gui import Window


class GuiWorkflowRound30Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rejected_version_refresh_preserves_work_and_shows_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for relative, content in {
                'About/About.xml': '<ModMetaData><packageId>test.guirefresh</packageId>'
                    '<supportedVersions><li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>',
                'LoadFolders.xml': '<loadFolders><v1.6><li>1.6</li></v1.6>'
                    '<v1.10><li>1.10</li></v1.10></loadFolders>',
                '1.6/Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello</Greeting></LanguageData>',
                '1.10/Languages/English/Keyed/a.xml': '<LanguageData><Greeting>Hello newer</Greeting></LanguageData>',
            }.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            previous_settings = os.environ.get('RW_TRANSLATOR_SETTINGS')
            os.environ['RW_TRANSLATOR_SETTINGS'] = str(root / 'ui-settings.json')
            window = None
            try:
                saved = root / 'workspace/project.json'
                project = Project.create(source, scan_mod(source, game_version='1.6'))
                project.save(saved)
                window = Window()
                window.load_project(saved)
                window.project.set_translation('Keyed:Keyed:Greeting', '未保存の挨拶')
                window.dirty = True
                undo, redo = object(), object()
                window.undo_batches[:] = [undo]
                window.redo_batches[:] = [redo]
                errors = []
                window.error = errors.append
                before = copy.deepcopy(window.project)
                disk_before = {str(p.relative_to(root / 'workspace')): p.read_bytes()
                               for p in (root / 'workspace').rglob('*') if p.is_file()}
                original = window.project
                window.busy = True

                window.scan_finished(source, None, scan_mod(source, game_version='1.10'), '')

                self.assertEqual(len(errors), 1)
                self.assertIn('version', errors[0].lower())
                self.assertIs(window.project, original)
                self.assertEqual(window.project, before)
                self.assertTrue(window.dirty)
                self.assertEqual(window.undo_batches, [undo])
                self.assertEqual(window.redo_batches, [redo])
                self.assertFalse(window.busy)
                self.assertTrue(window.table.isEnabled())
                self.assertFalse(window.japanese.isReadOnly())
                self.assertEqual({str(p.relative_to(root / 'workspace')): p.read_bytes()
                                  for p in (root / 'workspace').rglob('*') if p.is_file()}, disk_before)
            finally:
                if window is not None:
                    window.dirty = False
                    window.close()
                    self.app.processEvents()
                if previous_settings is None:
                    os.environ.pop('RW_TRANSLATOR_SETTINGS', None)
                else:
                    os.environ['RW_TRANSLATOR_SETTINGS'] = previous_settings


if __name__ == '__main__':
    unittest.main()
