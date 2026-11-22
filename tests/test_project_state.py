"""Backward compatibility and independent language review state."""
import json
from pathlib import Path
import tempfile
import unittest
from rimworld_translator.core import Entry, Project, Scan


class ProjectStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.item = Entry('DefInjected:ThingDef:Gun.label', 'DefInjected', 'ThingDef', 'Gun.label', 'gun', 'Defs/gun.xml')
        self.project = Project.create(self.source, Scan(entries=[self.item]), ['Japanese', 'French'])
        self.path = self.root / 'work/project.json'

    def test_reviews_are_independent_and_edit_invalidates_only_one_language(self):
        self.assertTrue(hasattr(self.project, 'set_translation'), 'Language-aware editing API is missing')
        p = self.project
        p.set_translation(self.item.id, '銃')
        p.mark_reviewed(self.item.id, approved=True)
        p.switch_language('French')
        self.assertFalse(p.entries[0].reviewed)
        p.set_translation(self.item.id, 'arme')
        p.mark_reviewed(self.item.id)
        p.switch_language('Japanese')
        self.assertTrue(p.entries[0].approved)
        p.set_translation(self.item.id, '鉄砲')
        self.assertFalse(p.entries[0].approved)
        p.switch_language('French')
        self.assertTrue(p.entries[0].reviewed)
        self.assertEqual(p.get_translation(self.item.id, 'Japanese'), '鉄砲')
        p.save(self.path)
        restored = Project.load(self.path)
        self.assertTrue(restored.entries[0].reviewed)
        restored.switch_language('Japanese')
        self.assertFalse(restored.entries[0].reviewed)

    def test_rescan_retains_exclusions_and_invalidates_all_language_reviews(self):
        self.assertTrue(hasattr(self.project, 'mark_reviewed'), 'Persistent per-language reviews are missing')
        p = self.project
        for language, text in [('Japanese', '銃'), ('French', 'arme')]:
            p.switch_language(language)
            p.set_translation(self.item.id, text)
            p.mark_reviewed(self.item.id, approved=True)
        p.entries[0].excluded = True
        changed = Entry(self.item.id, 'DefInjected', 'ThingDef', 'Gun.label', 'new gun', 'Defs/gun.xml')
        p.rescan(Scan(entries=[changed]))
        self.assertTrue(p.entries[0].excluded)
        for language in p.languages:
            p.switch_language(language)
            self.assertTrue(p.entries[0].changed)
            self.assertFalse(p.entries[0].approved)
            self.assertTrue(p.get_translation(self.item.id))

    def test_old_schema_and_unchanged_save(self):
        self.project.save(self.path)
        raw = json.loads(self.path.read_text())
        for field in ('language_states', 'metadata', 'glossary', 'game_version', 'active_mods'):
            raw.pop(field, None)
        for entry in raw['entries']:
            for field in ('reviewed', 'approved', 'excluded', 'confidence', 'evidence', 'is_new', 'classification'):
                entry.pop(field, None)
        self.path.write_text(json.dumps(raw))
        loaded = Project.load(self.path)
        self.assertTrue(hasattr(loaded, 'language_states'), 'Schema-1 migration is missing')
        loaded.save(self.path)
        before = self.path.stat().st_mtime_ns
        loaded.save(self.path)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_generated_definjected_layout_matches_game_loader(self):
        from rimworld_translator.core import export_mod
        self.project.entries[0].japanese = '銃'
        target = self.root / 'work/mod'
        export_mod(self.project, target)
        self.assertTrue((target / 'Languages/Japanese/DefInjected/ThingDef/Translations.xml').is_file(),
                        'RimWorld requires a Def-type subdirectory')

    def test_export_advertises_only_the_scanned_game_version(self):
        from rimworld_translator.core import export_mod
        import xml.etree.ElementTree as ET
        self.project.versions = ['1.5','1.6']
        self.project.game_version = '1.6'
        target = self.root/'work/mod'
        export_mod(self.project,target)
        about = ET.parse(target/'About/About.xml').getroot()
        self.assertEqual([e.text for e in about.findall('supportedVersions/li')],['1.6'])

    def test_publishable_metadata_is_used_without_changing_package_identity(self):
        from rimworld_translator.core import export_mod
        import xml.etree.ElementTree as ET
        self.project.metadata = {'name':'My translation','author':'Example translator','description':'Community translation description','license':'CC BY 4.0','use_source_preview':'false'}
        target = self.root/'work/mod'
        export_mod(self.project,target)
        about = ET.parse(target/'About/About.xml').getroot()
        self.assertEqual(about.findtext('name'),'My translation')
        self.assertEqual(about.findtext('author'),'Example translator')
        self.assertIn('CC BY 4.0',about.findtext('description'))
        self.assertEqual(about.findtext('packageId'),self.project.package_id)

    def test_unchanged_export_preserves_every_generated_file_timestamp(self):
        from rimworld_translator.core import export_mod
        import os
        self.project.entries[0].japanese = '銃'
        target = self.root/'work/mod'
        export_mod(self.project,target)
        files = [p for p in target.rglob('*') if p.is_file()]
        for path in files:
            os.utime(path,ns=(1,1))
        # Windows records file times in 100 ns units. Compare the actual stored
        # times so the test proves no rewrites on every filesystem.
        before = {path:path.stat().st_mtime_ns for path in files}
        export_mod(self.project,target)
        self.assertEqual({path:path.stat().st_mtime_ns for path in files},before)

    def test_formal_export_requires_review_for_each_changed_language(self):
        from rimworld_translator.core import export_mod
        p = self.project
        for language,text in [('Japanese','銃'),('French','arme')]:
            p.switch_language(language)
            p.set_translation(self.item.id,text)
            p.mark_reviewed(self.item.id)
        p.rescan(Scan(entries=[Entry(self.item.id,'DefInjected','ThingDef','Gun.label','updated gun','Defs/gun.xml')]))
        p.switch_language('Japanese')
        p.mark_reviewed(self.item.id)
        target = self.root/'work/mod'
        with self.assertRaisesRegex(ValueError, 'Source changed.*French'):
            export_mod(p,target)
        self.assertFalse(target.exists())
        p.switch_language('French')
        p.mark_reviewed(self.item.id)
        warnings = export_mod(p,target)
        self.assertFalse(any('Review needed' in w for w in warnings))


if __name__ == '__main__':
    unittest.main()
