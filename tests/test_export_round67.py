"""API export gates reject malformed rules and preserve saved project data."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from rimworld_translator.core import (Entry, Project, Scan, _export_payloads,
                                      _export_string_payloads, export_mod, export_versions_test)


def rule(translation='主題->宇宙船の構造工学'):
    return Entry('DefInjected:ResearchProjectDef:ShipBasics.generalRules.rulesStrings.0',
                 'DefInjected', 'ResearchProjectDef', 'ShipBasics.generalRules.rulesStrings.0',
                 'subject->starship structural engineering', 'Research.xml',
                 japanese=translation, review=True, reviewed=True, approved=True)


class ExportGateRound67Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()

    def project(self, entries=None):
        return Project.create(self.source, Scan(entries=entries or [rule()], name='Grammar fixture',
                                               package_id='test.rules67', versions=['1.6']))

    def test_xml_payload_formal_rejects_test_excludes_invalid_grammar(self):
        project = self.project()
        for translation in ('主題->宇宙船の構造工学', '宇宙船の構造工学', '->宇宙船の構造工学'):
            with self.subTest(translation=translation):
                project.entries[0].japanese = translation
                with self.assertRaisesRegex(ValueError, 'subject->'):
                    _export_payloads(project)
                payloads, warnings = _export_payloads(project, test_only=True)
                self.assertFalse(any(p.startswith('Languages/') for p in payloads))
                self.assertTrue(any('subject->' in warning for warning in warnings))
                self.assertEqual(project.entries[0].japanese, translation)

    def test_formal_rejection_preserves_existing_target_bytes(self):
        project = self.project([rule('subject->宇宙船の構造工学')])
        target = self.root / 'output'
        export_mod(project, target)
        before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        project.entries[0].japanese = '主題->宇宙船の構造工学'
        with self.assertRaises(ValueError):
            export_mod(project, target)
        self.assertEqual({p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}, before)

    def test_saved_version_profiles_exclude_bad_rule_retain_good_rule_and_history(self):
        scans = {version: Scan(entries=[rule()], name='Fixture', package_id='test.rules67',
                               versions=['1.5', '1.6'], stats={'active_version': version}) for version in ('1.5', '1.6')}
        project = Project.create_versions(self.source, scans)
        ident = project.entries[0].id
        project.set_translation(ident, 'subject->宇宙船の構造工学')
        project.mark_reviewed(ident, approved=True)
        project.switch_version('1.6')
        project.entries[0].changed = True
        path = self.root / 'workspace/project.json'
        project.save(path)
        saved_bytes = path.read_bytes()
        restored = Project.load(path)
        before = copy.deepcopy(restored.version_profiles)
        target = self.root / 'test-output'
        warnings = export_versions_test(restored, target)
        relative = 'Languages/Japanese/DefInjected/ResearchProjectDef/Translations.xml'
        self.assertFalse((target / '1.6' / relative).exists())
        self.assertEqual(ET.parse(target / '1.5' / relative).getroot()[0].text, 'subject->宇宙船の構造工学')
        self.assertTrue(any('1.6' in warning and 'subject->' in warning for warning in warnings))
        self.assertEqual(restored.version_profiles, before)
        self.assertEqual(path.read_bytes(), saved_bytes)
        self.assertEqual((restored.entries[0].english, restored.entries[0].japanese),
                         ('subject->starship structural engineering', '主題->宇宙船の構造工学'))
        self.assertTrue(restored.entries[0].reviewed and restored.entries[0].approved and restored.entries[0].changed)
        with self.assertRaisesRegex(ValueError, 'formal multi-version output'):
            export_mod(restored, self.root / 'formal')
        self.assertFalse((self.root / 'formal').exists())

    def test_strings_general_arrow_is_not_a_rulestring_and_existing_token_gate_still_applies(self):
        entry = Entry('Strings:Names/Own.txt:line_0', 'Strings', 'Names/Own.txt', 'line_0',
                      'subject->name {0}', 'Names/Own.txt', japanese='主題->名前 {0}')
        project = self.project([entry])
        payloads, warnings = _export_string_payloads(project, 'Japanese', {entry.id: entry.japanese}, test_only=False)
        self.assertEqual(payloads['Languages/Japanese/Strings/Names/Own.txt'], '主題->名前 {0}\n'.encode())
        self.assertEqual(warnings, [])
        with self.assertRaisesRegex(ValueError, 'プレースホルダー'):
            _export_string_payloads(project, 'Japanese', {entry.id: '名前'}, test_only=False)
        payloads, warnings = _export_string_payloads(project, 'Japanese', {entry.id: '名前'}, test_only=True)
        self.assertEqual(payloads, {})
        self.assertTrue(warnings)


class LegacyUnsafeEntriesRound67Tests(unittest.TestCase):
    setUp = ExportGateRound67Tests.setUp
    project = ExportGateRound67Tests.project
    unsafe_fields = (
        ('SaveOurShip2.ShipDef', 'AfterlifeVaultStart.bigString', '2,1,0,?|1,2,0,?'),
        ('SaveOurShip2.ShipDef', 'AfterlifeVaultStart.core.shapeOrDef', 'Ship_ComputerCore'),
        ('StorytellerDef', 'Sara.comps.1.enableIfAnyModActive.0', 'Ludeon.RimWorld.Ideology'),
        ('StorytellerDef', 'Sara.comps.1.disableIfAnyModActive.0', 'test.package'),
        ('ThingDef', 'Ship_BeamArchotech_Unpowered.comps.1.unlock', 'ArchotechUplink'),
        ('RuleDef', 'ShipDebrisDiningRoom.resolvers.0.interior', 'interior_diningRoom'),
        ('ScenarioDef', 'SoSDerelict.scenario.surfaceLayer.tag', 'Surface'),
        ('ThingDef', 'ShipAirlock.comps.5.graphicPathAlt', 'Things/Building/Ship/DockTubeV'),
        ('SaveOurShip2.NavyDef', 'Pirate_SpaceNavy.colorPrimary', 'Structure_Black'),
        ('SaveOurShip2.NavyDef', 'Pirate_SpaceNavy.colorSecondary', 'Structure_White'),
        ('HediffDef', 'SoSArchotechSkin.tags.0', 'ArmorGland'),
        ('RecipeDef', 'InstallSoSArchotechSkin.incompatibleWithHediffTags.0', 'ArmorGland'),
    )

    def unsafe_entry(self, group, key, english):
        return Entry(f'DefInjected:{group}:{key}', 'DefInjected', group, key, english,
                     'fixture.xml', japanese='保存された旧訳', reviewed=True, approved=True,
                     confidence='schema')

    def test_saved_unsafe_fields_cannot_edit_or_approve_and_preserve_history(self):
        from rimworld_translator.qa import qa_entry
        for group, key, english in self.unsafe_fields:
            with self.subTest(key=key):
                project = self.project([self.unsafe_entry(group, key, english)])
                saved = self.root / 'workspace' / (key + '.json')
                project.save(saved)
                restored = Project.load(saved)
                before = copy.deepcopy(restored.entries[0])
                self.assertTrue(any(i.code == 'nonlocalizable' and i.severity == 'error'
                                    for i in qa_entry(restored.entries[0])))
                with self.assertRaises(ValueError):
                    restored.set_translation(before.id, '新しい訳')
                with self.assertRaises(ValueError):
                    restored.mark_reviewed(before.id, approved=True)
                self.assertEqual(restored.entries[0], before)
                restored.save(saved)
                self.assertEqual(Project.load(saved).entries[0], before)

    def test_saved_unsafe_fields_formal_refuse_test_omit_and_keep_label_control(self):
        entries = [self.unsafe_entry(*values) for values in self.unsafe_fields]
        control = Entry('DefInjected:ThingDef:Ship.label', 'DefInjected', 'ThingDef',
                        'Ship.label', 'ship', 'fixture.xml', japanese='宇宙船')
        project = self.project(entries + [control])
        saved = self.root / 'workspace/project.json'
        project.save(saved)
        restored = Project.load(saved)
        before = copy.deepcopy(restored.entries)
        with self.assertRaises(ValueError):
            _export_payloads(restored)
        payloads, warnings = _export_payloads(restored, test_only=True)
        paths = [p for p in payloads if p.startswith('Languages/')]
        self.assertEqual(paths, ['Languages/Japanese/DefInjected/ThingDef/Translations.xml'])
        root = ET.fromstring(payloads[paths[0]])
        self.assertEqual([(e.tag, e.text) for e in root], [('Ship.label', '宇宙船')])
        self.assertEqual(sum('試験出力から除外' in w for w in warnings), len(entries))
        self.assertEqual(restored.entries, before)

    def test_rescan_removal_retains_unsafe_old_multilanguage_state_without_export(self):
        unsafe = self.unsafe_entry(*self.unsafe_fields[1])
        unsafe.excluded = True
        unsafe.classification = 'manual classification'
        scans = {version: Scan(entries=[unsafe], package_id='test.rules67', versions=['1.5', '1.6'],
                               stats={'active_version': version}) for version in ('1.5', '1.6')}
        project = Project.create_versions(self.source, scans, ['Japanese', 'French'])
        for version in project.versions:
            project.switch_version(version)
            project.translations['French'] = {unsafe.id: 'ancienne traduction'}
            project.language_states['French'] = {unsafe.id: {'reviewed': True, 'approved': True}}
            project.entries[0].previous_english = 'old reference'
            project.rescan(Scan(entries=[], package_id='test.rules67', versions=project.versions,
                                stats={'active_version': version}))
            self.assertTrue(project.entries[0].stale)
        saved = self.root / 'workspace/rescanned.json'
        project.save(saved)
        restored = Project.load(saved)
        before = copy.deepcopy(restored.version_profiles)
        target = self.root / 'rescanned-output'
        export_versions_test(restored, target)
        self.assertFalse(any(p.name == 'Translations.xml' for p in target.rglob('*')))
        self.assertEqual(restored.version_profiles, before)
        for version in project.versions:
            restored.switch_version(version)
            entry = restored.entries[0]
            self.assertEqual((entry.english, entry.previous_english, entry.japanese, entry.classification),
                             ('Ship_ComputerCore', 'old reference', '保存された旧訳', 'manual classification'))
            self.assertTrue(entry.stale and entry.excluded and entry.reviewed and entry.approved)
            self.assertEqual(restored.get_translation(unsafe.id, 'French'), 'ancienne traduction')
            self.assertEqual(restored.language_states['French'][unsafe.id], {'reviewed': True, 'approved': True})

    def test_positive_clr_owner_of_same_named_visible_field_remains_editable_and_exportable(self):
        entry = Entry('DefInjected:ThingDef:Ship.comps.1.unlock', 'DefInjected', 'ThingDef',
                      'Ship.comps.1.unlock', 'Unlock the ship', 'fixture.xml',
                      evidence=['CLR Example.VisibleComp.unlock: MustTranslateAttribute'])
        project = self.project([entry])
        project.set_translation(entry.id, '宇宙船を解放')
        project.mark_reviewed(entry.id, approved=True)
        payloads, _ = _export_payloads(project)
        root = ET.fromstring(payloads['Languages/Japanese/DefInjected/ThingDef/Translations.xml'])
        self.assertEqual([(e.tag, e.text) for e in root], [('Ship.comps.1.unlock', '宇宙船を解放')])
