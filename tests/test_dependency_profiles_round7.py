"""存在しないロード先の条件で有界構成探索を浪費しない。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.dependency_profiles import plan_dependency_scenarios


class ReachableLoadFolderPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('About/About.xml', '''<ModMetaData><packageId>target.mod</packageId>
          <supportedVersions><li>1.9</li><li>1.10</li></supportedVersions></ModMetaData>''')
        self.write('Actual/Defs/a.xml', '''<Defs><ThingDef><defName>Actual</defName>
          <label>conditional target label</label></ThingDef></Defs>''')

    def write(self, relative, xml):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding='utf-8')

    def keys(self, plan):
        return {
            scenario.name: {entry.key for entry in scan_mod(
                self.root, game_version=plan.game_version,
                active_mods=scenario.active_mods).entries}
            for scenario in plan.scenarios
        }

    def test_missing_folder_does_not_hide_reachable_keys_at_scenario_limit(self):
        self.write('LoadFolders.xml', '''<loadFolders><v1.9>
          <li IfModActive="aaa.missing">Missing</li>
          <li IfModActive="zzz.real">Actual</li>
          </v1.9><v1.10><li>Actual</li></v1.10></loadFolders>''')
        plan = plan_dependency_scenarios(self.root, '1.9', max_scenarios=2)
        # A missing folder cannot load in any active-MOD context. Spending the
        # only non-base slot on its condition suppresses the actual target key.
        self.assertEqual(self.keys(plan), {
            'base': set(), 'optional:zzz.real': {'Actual.label'},
        })
        self.assertEqual(plan.optional_mods, ('zzz.real',))
        self.assertEqual(plan.unexamined_scenarios, 0)
        self.assertIn('missing-folder', {item.code for item in plan.diagnostics})

    def test_rejected_paths_do_not_consume_scenarios(self):
        (self.root / 'Linked').symlink_to(self.root / 'Actual', target_is_directory=True)
        # A leading slash is MOD-relative in LoadFolders. This absolute-looking
        # value must not read the existing Actual directory at that OS path;
        # its normalized location inside the MOD does not exist.
        for rejected, diagnostic in (
                ('../Outside', 'load-path'),
                (str(self.root / 'Actual'), 'missing-folder'),
                ('Linked', 'load-path')):
            with self.subTest(rejected=rejected):
                self.write('LoadFolders.xml', f'''<loadFolders><v1.9>
                  <li IfModActive="aaa.invalid">{rejected}</li>
                  <li IfModActive="zzz.real">Actual</li>
                  </v1.9></loadFolders>''')
                plan = plan_dependency_scenarios(self.root, '1.9', max_scenarios=2)
                self.assertEqual(plan.optional_mods, ('zzz.real',))
                self.assertEqual(self.keys(plan), {
                    'base': set(), 'optional:zzz.real': {'Actual.label'},
                })
                self.assertIn(diagnostic, {item.code for item in plan.diagnostics})

    def test_other_version_and_non_folder_elements_do_not_add_optional_ids(self):
        self.write('LoadFolders.xml', '''<loadFolders><v1.9>
          <ignored IfModActive="aaa.ignored">Actual</ignored>
          <li IfModActive="zzz.real">Actual</li></v1.9>
          <v1.10><li>Actual</li></v1.10></loadFolders>''')
        old = plan_dependency_scenarios(self.root, '1.9', max_scenarios=2)
        future = plan_dependency_scenarios(self.root, '1.10', max_scenarios=2)
        self.assertEqual(self.keys(old), {
            'base': set(), 'optional:zzz.real': {'Actual.label'},
        })
        self.assertEqual(future.optional_mods, ())
        self.assertEqual(self.keys(future), {'base': {'Actual.label'}})


if __name__ == '__main__':
    unittest.main()
