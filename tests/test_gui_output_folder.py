"""The editor writes the translation MOD to the project's own output folder, and refuses protected places."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Entry, Project, Scan
from rimworld_translator.gui import Window


class OutputFolderGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source'
        (source / 'About').mkdir(parents=True)
        (source / 'About/About.xml').write_text('<ModMetaData><packageId>a.b</packageId><name>Src</name></ModMetaData>')
        scan = Scan([Entry('Keyed:Keyed:A', 'Keyed', 'Keyed', 'A', 'a', 'Keyed/A.xml')], [], 'Src', 'a.b', ['1.6'])
        self.project = Project.create(source, scan)
        self.path = self.root / 'work/project.json'
        self.project.save(self.path)
        self.window = Window(settings_path=self.root / 'settings.json')
        self.errors = []
        self.window.error = self.errors.append
        self.addCleanup(self.close)

    def close(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def open_with_output(self, folder):
        project = Project.load(self.path)
        project.output_folder = str(folder)
        project.save(self.path)
        self.window.load_project(self.path)

    def test_default_output_is_unchanged(self):
        self.window.load_project(self.path)
        self.assertTrue(self.window.generate())
        self.assertTrue((self.root / 'work/mod/About/About.xml').is_file())

    def test_custom_output_receives_the_export_and_is_shown(self):
        chosen = self.root / 'exports/MyTranslation'
        self.open_with_output(chosen)
        self.assertIn(str(chosen), self.window.location.text())
        self.assertTrue(self.window.generate())
        self.assertTrue((chosen / 'About/About.xml').is_file())
        self.assertFalse((self.root / 'work/mod').exists())
        self.assertTrue(self.window.save())
        self.assertFalse((self.root / 'work/mod').exists())

    def test_protected_output_is_refused_without_writing(self):
        workshop = self.root / 'workshop'
        workshop.mkdir()
        self.window.settings.data['workshop_folder'] = str(workshop)
        self.open_with_output(workshop / 'mine')
        self.assertFalse(self.window.generate())
        self.assertTrue(self.errors)
        self.assertIn('Workshop', str(self.errors[-1]))
        self.assertFalse((workshop / 'mine').exists())
        # Saving keeps the work and reports why the game files were not updated.
        self.assertTrue(self.window.save())
        self.assertIn('Workshop', self.window.last_export_error)


if __name__ == '__main__':
    unittest.main()
