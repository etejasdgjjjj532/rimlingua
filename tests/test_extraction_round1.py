"""Target-owned patch text remains separate from dependency-owned text."""
from pathlib import Path
import tempfile
import unittest
from rimworld_translator.core import scan_mod


class PatchOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'
        self.context = self.root / 'dependency'
        self.target.mkdir()
        self.context.mkdir()
        self.write(self.context, 'Defs/base.xml', '''<Defs>
          <ThingDef><defName>Foreign</defName><label>foreign label</label>
            <description>foreign description</description><graphicData><texPath>old/path</texPath></graphicData>
            <comps><li><label>foreign component</label></li></comps></ThingDef>
          <ThingDef Name="Base" Abstract="True"><description>inherited foreign description</description></ThingDef>
          <ThingDef ParentName="Base"><defName>ForeignChild</defName><label>foreign child</label></ThingDef>
        </Defs>''')

    def write(self, root, path, xml):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(xml, encoding='utf-8')

    def scan(self, operations, **kwargs):
        self.write(self.target, 'Patches/patch.xml', '<Patch>' + operations + '</Patch>')
        return scan_mod(self.target, context_sources=[self.context], active_mods=set(), **kwargs)

    def values(self, result):
        return {entry.key: entry.english for entry in result.entries}

    def test_texture_test_and_remove_patches_do_not_claim_foreign_text(self):
        result = self.scan('''
          <Operation Class="PatchOperationTest"><xpath>Defs/ThingDef[defName="Foreign"]</xpath></Operation>
          <Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Foreign"]/graphicData/texPath</xpath><value><texPath>new/path</texPath></value></Operation>
          <Operation Class="PatchOperationRemove"><xpath>Defs/ThingDef[defName="Foreign"]/comps/li</xpath></Operation>
        ''')
        self.assertEqual(self.values(result), {})

    def test_dependency_patch_only_claims_added_and_replaced_text(self):
        result = self.scan('''
          <Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Foreign"]/description</xpath><value><description>target replacement</description></value></Operation>
          <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]/comps</xpath><value><li><label>target component</label></li></value></Operation>
        ''')
        self.assertEqual(self.values(result), {'Foreign.description': 'target replacement',
                                             'Foreign.comps.1.label': 'target component'})
        self.assertTrue(all(entry.source_file == 'Patches/patch.xml' for entry in result.entries))

    def test_patch_parent_text_propagates_without_claiming_foreign_child_label(self):
        result = self.scan('''<Operation Class="PatchOperationReplace">
          <xpath>Defs/ThingDef[@Name="Base"]/description</xpath>
          <value><description>target inherited replacement</description></value>
        </Operation>''')
        self.assertEqual(self.values(result), {'ForeignChild.description': 'target inherited replacement'})

    def test_target_child_keeps_dependency_parent_text(self):
        self.write(self.target, 'Defs/child.xml', '''<Defs><ThingDef ParentName="Base">
          <defName>OwnedChild</defName><label>target label</label></ThingDef></Defs>''')
        result = self.scan('')
        self.assertEqual(self.values(result), {'OwnedChild.label': 'target label',
                                             'OwnedChild.description': 'inherited foreign description'})

    def test_removed_target_patch_text_does_not_remain_candidate(self):
        result = self.scan('''
          <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]</xpath><value><labelShort>temporary target text</labelShort></value></Operation>
          <Operation Class="PatchOperationRemove"><xpath>Defs/ThingDef[defName="Foreign"]/labelShort</xpath></Operation>
        ''')
        self.assertEqual(self.values(result), {})

    def test_prepend_and_insert_keep_final_indexes_without_claiming_original_item(self):
        result = self.scan('''
          <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Foreign"]/comps</xpath><order>Prepend</order><value><li><label>first target component</label></li></value></Operation>
          <Operation Class="PatchOperationInsert"><xpath>Defs/ThingDef[defName="Foreign"]/comps/li[1]</xpath><order>Append</order><value><li><label>second target component</label></li></value></Operation>
        ''')
        self.assertEqual(self.values(result), {'Foreign.comps.0.label': 'first target component',
                                             'Foreign.comps.1.label': 'second target component'})

    def test_foreign_child_override_suppresses_patched_parent_text(self):
        self.write(self.context, 'Defs/override.xml', '''<Defs><ThingDef ParentName="Base">
          <defName>Override</defName><description>foreign override</description></ThingDef></Defs>''')
        result = self.scan('''<Operation Class="PatchOperationReplace">
          <xpath>Defs/ThingDef[@Name="Base"]/description</xpath>
          <value><description>target inherited replacement</description></value>
        </Operation>''')
        self.assertEqual(self.values(result), {'ForeignChild.description': 'target inherited replacement'})

    def test_flat_lists_preserve_text_ownership_for_schema_and_heuristic_paths(self):
        from rimworld_translator.schema import FieldSpec, TypeSpec, TranslationSchema
        self.write(self.context, 'Defs/list.xml', '''<Defs><RulePackDef><defName>ForeignRules</defName>
          <rulesStrings><li>rule-&gt;foreign rule</li></rulesStrings></RulePackDef></Defs>''')
        schema = TranslationSchema({'RulePackDef': TypeSpec('RulePackDef', fields={
            'rulesStrings': FieldSpec('System.String', is_list=True,
                                     attributes=('MustTranslateAttribute',))})})
        for current_schema in (None, schema):
            with self.subTest(schema=current_schema is not None):
                result = self.scan('''<Operation Class="PatchOperationAdd">
                  <xpath>Defs/RulePackDef[defName="ForeignRules"]/rulesStrings</xpath>
                  <value><li>rule-&gt;target rule</li></value></Operation>''', schema=current_schema)
                self.assertEqual(self.values(result), {'ForeignRules.rulesStrings.1': 'rule->target rule'})

    def test_patch_added_definition_keeps_dependency_inheritance(self):
        result = self.scan('''<Operation Class="PatchOperationAdd"><xpath>Defs</xpath>
          <value><ThingDef ParentName="Base"><defName>Added</defName><label>target addition</label></ThingDef></value>
        </Operation>''')
        self.assertEqual(self.values(result), {'Added.label': 'target addition',
                                             'Added.description': 'inherited foreign description'})


if __name__ == '__main__':
    unittest.main()
