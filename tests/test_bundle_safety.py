"""Bundles must not carry the sender's paths, and importing must not write arbitrary files or clobber existing ones."""
import json
import zipfile

from rimworld_translator import interchange
from rimworld_translator.core import Project, export_mod

from test_interchange_modules import Base, keyed


class BundlePathTests(Base):
    def test_export_blanks_output_folder_and_scrubs_source_path_from_diagnostics(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        project.output_folder = str(self.root / 'my-out')
        project.diagnostics = [{'code': 'x', 'message': f'bad file {self.source}/Defs/a.xml', 'source_file': ''}]
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        data = json.loads(zipfile.ZipFile(bundle).read('project.json'))
        self.assertEqual(data['output_folder'], '')
        text = zipfile.ZipFile(bundle).read('project.json').decode('utf-8')
        self.assertNotIn(str(self.source), text)
        self.assertNotIn(str(self.root / 'my-out'), text)

    def test_import_ignores_foreign_output_folder_of_any_os_style(self):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        bundle = self.root / 'bundles/share.rwtbundle'
        interchange.export_bundle(project, bundle)
        for index, foreign in enumerate((r'C:\Users\x\out', '/home/x/out')):
            patched = self.root / f'bundles/p{index}.rwtbundle'
            with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(patched, 'w') as target:
                for name in source.namelist():
                    payload = source.read(name)
                    if name == 'project.json':
                        data = json.loads(payload)
                        data['output_folder'] = foreign
                        payload = json.dumps(data).encode('utf-8')
                    target.writestr(name, payload)
            path = interchange.import_bundle(patched, self.root / f'received{index}', self.source)
            self.assertEqual(Project.load(path).output_folder, '')


class BundleModImportTests(Base):
    def bundle_with(self, extra):
        project = self.project([keyed('A', 'Alpha', 'あ')])
        export_mod(project, self.root / 'mod')
        good = self.root / 'bundles/good.rwtbundle'
        interchange.export_bundle(project, good, output_folder=self.root / 'mod')
        evil = self.root / 'bundles/evil.rwtbundle'
        with zipfile.ZipFile(good) as source, zipfile.ZipFile(evil, 'w') as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
            for name, payload in extra.items():
                target.writestr(name, payload)
        return good, evil

    def test_files_outside_the_export_whitelist_are_refused(self):
        _, evil = self.bundle_with({'mod/Assemblies/evil.dll': 'MZ'})
        destination = self.root / 'received'
        with self.assertRaises(ValueError):
            interchange.import_bundle(evil, destination, self.source)
        self.assertFalse((destination / 'mod/Assemblies/evil.dll').exists())
        self.assertFalse((destination / 'project.json').exists())

    def test_existing_mod_files_are_not_overwritten_without_overwrite(self):
        good, _ = self.bundle_with({})
        destination = self.root / 'received'
        existing = destination / 'mod/About/About.xml'
        existing.parent.mkdir(parents=True)
        existing.write_text('mine')
        with self.assertRaises(ValueError):
            interchange.import_bundle(good, destination, self.source)
        self.assertEqual(existing.read_text(), 'mine')
        self.assertFalse((destination / 'project.json').exists())
        interchange.import_bundle(good, destination, self.source, overwrite=True)
        self.assertNotEqual(existing.read_text(), 'mine')
