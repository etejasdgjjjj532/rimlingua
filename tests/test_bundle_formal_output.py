"""'Include the generated MOD' in a bundle must use the formal output, never multi-version mod-test."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from rimworld_translator.core import Project
from rimworld_translator.gui_share import ShareMixin


class Recorder:
    def showMessage(self, *args):
        pass


class BundleFormalOutputTests(unittest.TestCase):
    def test_include_output_uses_the_formal_folder_of_a_multi_version_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            formal, trial_dir = root / 'formal', root / 'work/mod-test'
            for folder, text in ((formal, 'formal'), (trial_dir, 'trial')):
                (folder / 'About').mkdir(parents=True)
                (folder / 'About/About.xml').write_text(text)
            source = root / 'src'
            (source / 'About').mkdir(parents=True)
            project = Project(str(source), 'N', 'local.n', 'a.b', ['1.6'], [], [])
            project.version_profiles = {'1.6': {}}
            calls = []

            def output_folder(trial=False):
                calls.append(trial)
                return trial_dir if trial else formal
            stub = SimpleNamespace(project=project, busy=False, save=lambda export=False: True,
                                   project_path=root / 'work/project.json', output_folder=output_folder,
                                   tr=lambda ja, en=None: en or ja, statusBar=lambda: Recorder(),
                                   error=lambda *a: self.fail(a), error_text=str)
            (root / 'out').mkdir()
            bundle = root / 'out/x.rwtbundle'
            self.assertTrue(ShareMixin.export_bundle_to(stub, bundle, include_output=True))
            self.assertEqual(zipfile.ZipFile(bundle).read('mod/About/About.xml'), b'formal')
            self.assertEqual(calls, [False])


if __name__ == '__main__':
    unittest.main()
