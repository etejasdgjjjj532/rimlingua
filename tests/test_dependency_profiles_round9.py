"""版別依存・条件付きPatchの結果を永続XMLキャッシュ経路で保護する。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod
from rimworld_translator.dependency_profiles import plan_dependency_scenarios


class VersionedDependencyCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'target'
        self.context = self.root / 'dependency'
        self.cache = self.root / 'cache.sqlite'
        self.write(self.source, 'About/About.xml', '''<ModMetaData>
          <packageId>target.mod</packageId><supportedVersions>
          <li>1.10</li><li>1.9</li></supportedVersions>
          <modDependenciesByVersion>
          <v1.9><li><packageId>dep.old</packageId></li></v1.9>
          <v1.10><li><packageId>dep.new</packageId></li></v1.10>
          </modDependenciesByVersion></ModMetaData>''')
        self.write(self.source, 'LoadFolders.xml', '''<loadFolders>
          <v1.9><li>Common</li><li IfModActiveAll="opt.a,opt.b">OldAB</li></v1.9>
          <v1.10><li>Common</li><li IfModActiveAll="opt.a,opt.b">NewAB</li></v1.10>
          </loadFolders>''')
        self.write(self.source, 'Common/Defs/own.xml', '''<Defs><ThingDef>
          <defName>Own</defName><label>target own label</label>
          </ThingDef></Defs>''')
        self.write(self.context, 'LoadFolders.xml', '''<loadFolders>
          <v1.9><li>Old</li></v1.9><v1.10><li>New</li></v1.10>
          </loadFolders>''')
        for version, branch, dependency in [('1.9', 'Old', 'dep.old'), ('1.10', 'New', 'dep.new')]:
            self.write(self.context, f'{branch}/Defs/desk.xml', f'''<Defs>
              <ThingDef MayRequire="{dependency}"><defName>Desk{branch}</defName>
              <label>foreign label</label><description>head<part>middle</part>tail</description>
              </ThingDef></Defs>''')
            self.write(self.source, f'{branch}AB/Patches/tail.xml', f'''<Patch>
              <Operation Class="PatchOperationAdd">
              <xpath>Defs/ThingDef[defName="Desk{branch}" and string(description)="headmiddletail"]</xpath>
              <value><labelShort>target {version} addition</labelShort></value>
              </Operation></Patch>''')

    @staticmethod
    def write(root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    def scan(self, version, scenario, cache):
        result = scan_mod(self.source, game_version=version,
                          active_mods=scenario.active_mods,
                          context_sources=[self.context], cache_path=cache)
        return {entry.key: entry.english for entry in result.entries}, result.stats

    def test_declared_versions_keep_separate_dependency_and_combination_inventory(self):
        for version, dependency in [('1.9', 'dep.old'), ('1.10', 'dep.new')]:
            with self.subTest(version=version):
                plan = plan_dependency_scenarios(self.source, version)
                self.assertEqual(plan.required_mods, (dependency,))
                self.assertEqual(plan.optional_mods, ('opt.a', 'opt.b'))
                self.assertEqual(plan.total_scenarios, 4)
                self.assertEqual(plan.unexamined_scenarios, 0)
                self.assertTrue(all(dependency in item.active_mods for item in plan.scenarios))

    def test_disk_cache_keeps_version_and_dependency_conditioned_patch_keys(self):
        self.addCleanup(self.clear_memory)
        for version, branch in [('1.9', 'Old'), ('1.10', 'New')]:
            plan = plan_dependency_scenarios(self.source, version)
            for scenario in plan.scenarios:
                with self.subTest(version=version, scenario=scenario.name):
                    expected = {'Own.label': 'target own label'}
                    if {'opt.a', 'opt.b'} <= scenario.active_mods:
                        expected[f'Desk{branch}.labelShort'] = f'target {version} addition'
                    self.assertEqual(self.scan(version, scenario, None)[0], expected)
                    self.assertEqual(self.scan(version, scenario, self.cache)[0], expected)
                    memory, memory_stats = self.scan(version, scenario, self.cache)
                    self.assertEqual(memory, expected)
                    self.assertGreater(memory_stats['memory_hits'], 0)
                    self.clear_memory()
                    disk, disk_stats = self.scan(version, scenario, self.cache)
                    self.assertEqual(disk_stats['parsed_files'], 0)
                    self.assertEqual(disk_stats['memory_hits'], 0)
                    self.assertGreater(disk_stats['cached_files'], 0)
                    self.assertEqual(disk, expected)

    def test_same_paths_with_changed_tail_invalidate_both_cache_layers(self):
        self.addCleanup(self.clear_memory)
        scenario = plan_dependency_scenarios(self.source, '1.9').scenarios[-1]
        initial = {'Own.label': 'target own label', 'DeskOld.labelShort': 'target 1.9 addition'}
        self.assertEqual(self.scan('1.9', scenario, self.cache)[0], initial)
        context = self.context / 'Old/Defs/desk.xml'
        patch = self.source / 'OldAB/Patches/tail.xml'
        context.write_text(context.read_text(encoding='utf-8').replace('tail</description>', 'revised</description>'), encoding='utf-8')
        patch.write_text(patch.read_text(encoding='utf-8').replace('headmiddletail', 'headmiddlerevised').replace('target 1.9 addition', 'revised addition'), encoding='utf-8')
        expected = {'Own.label': 'target own label', 'DeskOld.labelShort': 'revised addition'}
        changed, stats = self.scan('1.9', scenario, self.cache)
        self.assertEqual(changed, expected)
        self.assertEqual(stats['parsed_files'], 2)
        self.clear_memory()
        restored, stats = self.scan('1.9', scenario, self.cache)
        self.assertEqual(restored, expected)
        self.assertEqual(stats['parsed_files'], 0)
        self.assertEqual(stats['memory_hits'], 0)


if __name__ == '__main__':
    unittest.main()
