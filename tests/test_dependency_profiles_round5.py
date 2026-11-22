"""FindMod の表示名探索を、選択版の潜在ロードフォルダに限定する。"""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator.core import scan_mod
from rimworld_translator.dependency_profiles import plan_dependency_scenarios


class VersionedFindModPlanningTests(unittest.TestCase):
    def test_conditional_folder_finds_display_name_without_other_version_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(relative, text):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')

            write('target/About/About.xml', '''<ModMetaData><name>Target</name>
              <packageId>target.mod</packageId><supportedVersions><li>1.9</li><li>1.10</li>
              </supportedVersions></ModMetaData>''')
            for folder, name, ident in [('dependency', 'Known Display', 'dep.known'),
                                         ('future', 'Future Display', 'dep.future')]:
                write(f'{folder}/About/About.xml', f'''<ModMetaData><name>{name}</name>
                  <packageId>{ident}</packageId></ModMetaData>''')
            write('target/LoadFolders.xml', '''<loadFolders><v1.9><li>Common</li>
              <li IfModActive="opt.folder">Conditional</li></v1.9>
              <v1.10><li>Future</li></v1.10></loadFolders>''')
            write('target/Common/Defs/base.xml', '''<Defs><ThingDef><defName>Base</defName>
              <label>base</label></ThingDef></Defs>''')
            patch = '''<Patch><Operation Class="PatchOperationFindMod"><mods><li>{}</li></mods>
              <match Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Base"]</xpath>
              <value><description>target conditional text</description></value></match>
              </Operation></Patch>'''
            write('target/Conditional/Patches/add.xml', patch.format('Known Display'))
            write('target/Future/Patches/add.xml', patch.format('Future Display'))
            write('dependency/Defs/private.xml', '''<Defs><ThingDef><defName>Private</defName>
              <label>dependency private text</label></ThingDef></Defs>''')
            target = root / 'target'
            plan = plan_dependency_scenarios(target, '1.9',
                                            context_sources=[root / 'dependency', root / 'future'])
            self.assertEqual(plan.optional_mods, ('dep.known', 'opt.folder'))
            actual = {}
            for scenario in plan.scenarios:
                contexts = [root / 'dependency'] if 'dep.known' in scenario.active_mods else []
                result = scan_mod(target, game_version='1.9', active_mods=scenario.active_mods,
                                  context_sources=contexts)
                actual[scenario.name] = {entry.key for entry in result.entries}
            self.assertEqual(actual, {
                'base': {'Base.label'},
                'optional:dep.known': {'Base.label'},
                'optional:opt.folder': {'Base.label'},
                'optional:dep.known,opt.folder': {'Base.label', 'Base.description'},
            })
            future = plan_dependency_scenarios(target, '1.10',
                                              context_sources=[root / 'dependency', root / 'future'])
            self.assertEqual(future.optional_mods, ('dep.future',))


if __name__ == '__main__':
    unittest.main()
