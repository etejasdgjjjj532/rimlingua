"""Patch condition regressions with independently specified expected text."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod


class PatchConditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'
        self.context = self.root / 'context'
        self.write(self.target, 'About/About.xml', '<ModMetaData><name>Target Pack</name><packageId>test.target</packageId></ModMetaData>')
        self.write(self.context, 'About/About.xml', '<ModMetaData><name>Dependency Pack</name><packageId>test.dependency</packageId></ModMetaData>')
        self.write(self.target, 'Defs/items.xml', '<Defs><ThingDef><defName>Owned</defName><label>original label</label></ThingDef></Defs>')
        self.write(self.context, 'Defs/items.xml', '<Defs><ThingDef><defName>Foreign</defName><label>foreign label</label><description>foreign description</description></ThingDef></Defs>')

    def write(self, root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def scan(self, operation, active):
        self.write(self.target, 'Patches/condition.xml', '<Patch>' + operation + '</Patch>')
        return scan_mod(self.target, context_sources=[self.context], active_mods=active)

    def values(self, result):
        return {entry.key: entry.english for entry in result.entries}

    def findmod(self, names):
        return '<Operation Class="PatchOperationFindMod"><mods>' + ''.join('<li>' + name + '</li>' for name in names) + '''</mods>
          <match Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Foreign"]/description</xpath><value><description>target conditional description</description></value></match>
          <nomatch Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Owned"]/label</xpath><value><label>dependency absent</label></value></nomatch>
        </Operation>'''

    def test_findmod_display_name_resolves_active_package_without_foreign_label(self):
        result = self.scan(self.findmod(['Dependency Pack']), {'test.dependency'})
        self.assertEqual(self.values(result), {'Owned.label': 'original label', 'Foreign.description': 'target conditional description'})
        self.assertFalse(any(d['code'] == 'patch-context' for d in result.diagnostics))

    def test_findmod_known_complete_empty_active_set_uses_nomatch(self):
        result = self.scan(self.findmod(['Dependency Pack']), set())
        self.assertEqual(self.values(result), {'Owned.label': 'dependency absent'})

    def test_findmod_package_id_is_not_a_display_name(self):
        result = self.scan(self.findmod(['test.dependency']), {'test.dependency'})
        self.assertEqual(self.values(result), {'Owned.label': 'dependency absent'})

    def test_findmod_display_names_are_case_sensitive_and_any_name_can_match(self):
        for names, expected in [(['dependency pack'], {'Owned.label': 'dependency absent'}),
                                (['Absent Pack', 'Dependency Pack'], {'Owned.label': 'original label', 'Foreign.description': 'target conditional description'}),
                                (['Target Pack'], {'Owned.label': 'original label', 'Foreign.description': 'target conditional description'})]:
            with self.subTest(names=names):
                self.assertEqual(self.values(self.scan(self.findmod(names), {'test.dependency'})), expected)

    def test_unknown_active_package_names_do_not_fabricate_nomatch(self):
        result = self.scan(self.findmod(['Unresolved Pack']), {'unknown.package'})
        self.assertEqual(self.values(result), {'Owned.label': 'original label'})
        self.assertTrue(any(d['code'] == 'patch-context' for d in result.diagnostics))

    def test_unknown_active_context_does_not_hide_a_known_positive_match(self):
        result = self.scan(self.findmod(['Dependency Pack']), {'test.dependency', 'unknown.package'})
        self.assertEqual(self.values(result), {'Owned.label': 'original label', 'Foreign.description': 'target conditional description'})

    def test_unspecified_active_context_stays_unresolved(self):
        result = self.scan(self.findmod(['Dependency Pack']), None)
        self.assertEqual(self.values(result), {'Owned.label': 'original label'})
        self.assertTrue(any(d['code'] == 'patch-context' for d in result.diagnostics))

    def test_operation_mayrequire_excludes_inactive_replacement(self):
        for active, expected in [(set(), 'original label'), ({'test.dependency'}, 'conditional label')]:
            with self.subTest(active=active):
                result = self.scan('''<Operation Class="PatchOperationReplace" MayRequire="test.dependency">
                  <xpath>Defs/ThingDef[defName="Owned"]/label</xpath><value><label>conditional label</label></value></Operation>''', active)
                self.assertEqual(self.values(result), {'Owned.label': expected})

    def test_nested_inactive_operation_does_not_stop_sequence(self):
        result = self.scan('''<Operation Class="PatchOperationSequence"><operations>
          <li Class="PatchOperationReplace" MayRequire="absent.package"><xpath>Defs/ThingDef[defName="Owned"]/label</xpath><value><label>wrong branch</label></value></li>
          <li Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Owned"]</xpath><value><description>sequence remains active</description></value></li>
        </operations></Operation>''', set())
        self.assertEqual(self.values(result), {'Owned.label': 'original label', 'Owned.description': 'sequence remains active'})
