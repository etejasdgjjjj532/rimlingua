"""FindMod の表示名を提供された About の packageId に結び付ける。"""
from pathlib import Path
import inspect
import tempfile
import unittest

from rimworld_translator import dependency_profiles as profiles
from rimworld_translator.core import scan_mod


class FindModDependencyPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.mod('target', 'Target', 'target.mod')
        self.dependency = self.mod('dependency', 'Dependency Display Name', 'Dep.Package')
        self.write(self.target, 'Defs/base.xml', '<Defs><ThingDef><defName>Base</defName><label>base</label></ThingDef></Defs>')

    def write(self, source, relative, xml):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding='utf-8')

    def mod(self, folder, name, package):
        source = self.root / folder
        self.write(source, 'About/About.xml', f'<ModMetaData><name>{name}</name><packageId>{package}</packageId><supportedVersions><li>1.6</li></supportedVersions></ModMetaData>')
        return source

    def patch(self, names):
        self.write(self.target, 'Patches/find.xml', f'''<Patch><Operation Class="PatchOperationFindMod"><mods>{''.join(f'<li>{name}</li>' for name in names)}</mods>
          <match Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Base"]</xpath><value><description>conditional target text</description></value></match>
          </Operation></Patch>''')

    def plan(self, sources=(), **options):
        # Before the new keyword exists, still expose the missing scenario as an
        # assertion failure instead of stopping at an unrelated TypeError.
        if 'context_sources' in inspect.signature(profiles.plan_dependency_scenarios).parameters:
            options['context_sources'] = sources
        return profiles.plan_dependency_scenarios(self.target, '1.6', **options)

    def test_supplied_display_name_recovers_target_patch_without_dependency_text(self):
        self.patch(['Dependency Display Name'])
        self.write(self.dependency, 'Defs/private.xml', '<Defs><ThingDef><defName>DependencyOwn</defName><label>dependency text</label></ThingDef></Defs>')
        plan = self.plan([self.dependency])
        self.assertEqual(plan.optional_mods, ('dep.package',))
        actual = {}
        for scenario in plan.scenarios:
            contexts = [self.dependency] if 'dep.package' in scenario.active_mods else []
            scan = scan_mod(self.target, game_version='1.6', active_mods=scenario.active_mods, context_sources=contexts)
            actual[scenario.name] = {entry.key for entry in scan.entries}
        self.assertEqual(actual, {'base': {'Base.label'}, 'optional:dep.package': {'Base.label', 'Base.description'}})

    def test_display_names_are_case_sensitive_and_package_id_is_not_a_name(self):
        self.patch(['dependency display name', 'Dep.Package'])
        plan = self.plan([self.dependency])
        self.assertEqual(plan.optional_mods, ())
        self.assertIn('findmod-context', {d.code for d in plan.diagnostics})

    def test_unknown_name_stays_diagnosed_with_known_any_alternative(self):
        self.patch(['Dependency Display Name', 'Unknown Name'])
        plan = self.plan([self.dependency])
        self.assertEqual(plan.optional_mods, ('dep.package',))
        self.assertTrue(any(d.code == 'findmod-context' and 'Unknown Name' in d.message for d in plan.diagnostics))

    def test_duplicate_display_name_keeps_both_ids_with_ambiguity_diagnostic(self):
        other = self.mod('other', 'Dependency Display Name', 'other.package')
        self.patch(['Dependency Display Name'])
        plan = self.plan([self.dependency, other])
        self.assertEqual(plan.optional_mods, ('dep.package', 'other.package'))
        self.assertEqual(plan.total_scenarios, 4)
        self.assertIn('findmod-ambiguous-name', {d.code for d in plan.diagnostics})

    def test_fixed_and_own_names_do_not_create_optional_scenarios(self):
        self.patch(['Target', 'Dependency Display Name'])
        plan = self.plan([self.dependency], base_active_mods=['DEP.PACKAGE'])
        self.assertEqual(plan.optional_mods, ())
        self.assertEqual(plan.total_scenarios, 1)
        self.assertNotIn('findmod-context', {d.code for d in plan.diagnostics})

    def test_unused_context_source_does_not_become_optional(self):
        plan = self.plan([self.dependency])
        self.assertEqual(plan.optional_mods, ())


if __name__ == '__main__':
    unittest.main()
