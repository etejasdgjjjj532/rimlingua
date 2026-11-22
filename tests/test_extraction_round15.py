"""DOM sibling text remains independent during static Replace and Insert."""
from pathlib import Path
import tempfile
import unittest
from xml.dom import minidom

from rimworld_translator import extraction
from rimworld_translator.core import scan_mod


class PatchSiblingTextTests(unittest.TestCase):
    versions = ('1.3', '1.4', '1.5', '1.6', '1.9', '1.10')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.context = self.root / 'context'
        self.cache = self.root / 'cache.sqlite'
        self.clear_memory()
        self.addCleanup(self.clear_memory)
        for folder, package in ((self.source, 'test.sibling.patch'),
                                (self.context, 'test.sibling.context')):
            self.write(folder, 'About/About.xml',
                       '<ModMetaData><packageId>' + package + '</packageId>'
                       '<supportedVersions>' + ''.join('<li>' + v + '</li>' for v in self.versions)
                       + '</supportedVersions></ModMetaData>')
            self.write(folder, 'LoadFolders.xml', '<loadFolders>' + ''.join(
                '<v' + v + '><li>' + v + '</li></v' + v + '>' for v in self.versions)
                + '</loadFolders>')

    @staticmethod
    def write(root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    @staticmethod
    def clear_memory():
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES = 0

    @staticmethod
    def dom_text(original, value, kind, order):
        """Independent DOM oracle for the legally inspected 1.6 sibling APIs."""
        document = minidom.parseString('<label>' + original + '</label>')
        label = document.documentElement
        anchor = next(n for n in label.childNodes
                      if n.nodeType in (n.PROCESSING_INSTRUCTION_NODE, n.ELEMENT_NODE))
        children = list(minidom.parseString('<value>' + value + '</value>').documentElement.childNodes)
        if kind == 'Replace':
            for child in children:
                label.insertBefore(document.importNode(child, True), anchor)
            label.removeChild(anchor)
        elif order == 'Append':
            for child in children:
                imported = document.importNode(child, True)
                if anchor.nextSibling is None:
                    label.appendChild(imported)
                else:
                    label.insertBefore(imported, anchor.nextSibling)
        else:
            for child in reversed(children):
                label.insertBefore(document.importNode(child, True), anchor)
        return ''.join(n.data for n in label.childNodes if n.nodeType == n.TEXT_NODE)

    def assert_case(self, original, value, kind, order, expected, selector='processing-instruction("anchor")', owned=True, position=''):
        # The literal expected value is checked independently before scan_mod.
        self.assertEqual(self.dom_text(original, value, kind, order), expected)
        for version in self.versions:
            self.write(self.context, version + '/Defs/external.xml',
                       '<Defs><ThingDef Name="ExternalBase" Abstract="True"><label>'
                       + original.replace('VERSION', version) + '</label>'
                       '<description>external description excluded</description></ThingDef>'
                       '<ThingDef ParentName="ExternalBase"><defName>ExternalChild</defName></ThingDef>'
                       '<ThingDef><defName>Untouched</defName><label>unrelated external text</label>'
                       '</ThingDef></Defs>')
            self.write(self.source, version + '/Patches/sibling.xml',
                       '<Patch><Operation Class="PatchOperation' + kind
                       + '" MayRequire="test.sibling.context"><xpath>'
                       'Defs/ThingDef[@Name="ExternalBase"]/label/' + selector + '</xpath>'
                       + ('<order>' + order + '</order>' if order else '')
                       + '<value>' + value.replace('VERSION', version) + '</value></Operation>'
                       + ('<Operation Class="PatchOperationConditional"><xpath>'
                          'Defs/ThingDef[@Name="ExternalBase"]/label/processing-instruction("anchor")/'
                          + position + '-sibling::processing-instruction("probe")</xpath>'
                          '<match Class="PatchOperationAdd"><xpath>Defs/ThingDef[@Name="ExternalBase"]</xpath>'
                          '<value><labelShort>position verified</labelShort></value></match></Operation>'
                          if position else '') + '</Patch>')
        before = {p: p.read_bytes() for p in self.root.rglob('*.xml')}
        for version in self.versions:
            for mode in ('uncached', 'sqlite-first', 'memory', 'sqlite-restored'):
                with self.subTest(version=version, mode=mode):
                    if mode == 'sqlite-restored':
                        self.clear_memory()
                    result = scan_mod(self.source, game_version=version,
                                      context_sources=[self.context], active_mods={'test.sibling.context'},
                                      cache_path=None if mode == 'uncached' else self.cache)
                    wanted = {'ExternalChild.label': expected.replace('VERSION', version)} if owned else {}
                    if position:
                        wanted['ExternalChild.labelShort'] = 'position verified'
                    self.assertEqual({e.key: e.english for e in result.entries}, wanted)
                    for entry in result.entries:
                        self.assertEqual(entry.source_file, version + '/Patches/sibling.xml')
                    if mode == 'memory':
                        self.assertEqual(result.stats['memory_hits'], 2)
                    if mode == 'sqlite-restored':
                        self.assertEqual(result.stats['parsed_files'], 0)
                        self.assertEqual(result.stats['cached_files'], 2)
            excluded = scan_mod(self.source, game_version=version,
                                context_sources=[self.context], active_mods=set())
            self.assertEqual(excluded.entries, [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*.xml')})

    def test_replace_preserves_anchor_following_text_and_value_leading_text(self):
        self.assert_case('head<?anchor old?> tail VERSION', 'new VERSION<?probe inert?> end',
                         'Replace', '', 'headnew VERSION end tail VERSION')

    def test_replace_empty_value_keeps_external_tail_without_claiming_ownership(self):
        # No target-owned text was introduced, so the external string stays excluded.
        original = 'head<?anchor old?> tail VERSION'
        self.assertEqual(self.dom_text(original, '', 'Replace', ''), 'head tail VERSION')
        self.assert_case(original, '', 'Replace', '', 'head tail VERSION', owned=False)

    def test_replace_normal_element_retains_following_text(self):
        self.assert_case('head<part>removed</part> tail VERSION', 'new VERSION<?probe inert?> end',
                         'Replace', '', 'headnew VERSION end tail VERSION', selector='part')

    def test_insert_append_uses_dom_child_order_before_existing_tail(self):
        self.assert_case('head<?anchor old?> tail VERSION', 'left VERSION<?probe inert?>right',
                         'Insert', 'Append', 'headrightleft VERSION tail VERSION', position='following')

    def test_insert_prepend_uses_dom_child_order(self):
        self.assert_case('head<?anchor old?> tail VERSION', 'left VERSION<?probe inert?>right',
                         'Insert', 'Prepend', 'headrightleft VERSION tail VERSION', position='preceding')

    def test_insert_default_is_prepend(self):
        self.assert_case('head<?anchor old?> tail VERSION', 'left VERSION<?probe inert?>right',
                         'Insert', '', 'headrightleft VERSION tail VERSION', position='preceding')


    def test_insert_multiple_list_elements_reverse_order_without_claiming_external_item(self):
        for version in self.versions:
            self.write(self.context, version + '/Defs/list.xml',
                       '<Defs><RulePackDef><defName>ExternalRules</defName>'
                       '<rulesStrings><li>external original</li></rulesStrings></RulePackDef></Defs>')
        for order, indexes in (('Append', (1, 2)), ('Prepend', (0, 1))):
            document = minidom.parseString('<rulesStrings><li>external original</li></rulesStrings>')
            anchor = document.documentElement.firstChild
            children = minidom.parseString('<value><li>first</li><li>second</li></value>').documentElement.childNodes
            for child in children if order == 'Append' else reversed(children):
                imported = document.importNode(child, True)
                if order == 'Append' and anchor.nextSibling is None:
                    document.documentElement.appendChild(imported)
                else:
                    document.documentElement.insertBefore(imported,
                        anchor.nextSibling if order == 'Append' else anchor)
            self.assertEqual([n.firstChild.data for n in document.documentElement.childNodes],
                             ['external original', 'second', 'first'] if order == 'Append'
                             else ['second', 'first', 'external original'])
            for version in self.versions:
                self.write(self.source, version + '/Patches/list.xml',
                           '<Patch><Operation Class="PatchOperationInsert">'
                           '<xpath>Defs/RulePackDef/rulesStrings/li</xpath><order>' + order
                           + '</order><value><li>first</li><li>second</li></value></Operation></Patch>')
                for mode in ('uncached', 'sqlite-first', 'sqlite-restored'):
                    with self.subTest(version=version, order=order, mode=mode):
                        if mode == 'sqlite-restored':
                            self.clear_memory()
                        result = scan_mod(self.source, game_version=version,
                                          context_sources=[self.context],
                                          cache_path=None if mode == 'uncached' else self.cache)
                        self.assertEqual({e.key: e.english for e in result.entries}, {
                            'ExternalRules.rulesStrings.' + str(indexes[0]): 'second',
                            'ExternalRules.rulesStrings.' + str(indexes[1]): 'first'})

    def test_invalid_insert_order_is_diagnosed_without_claiming_external_text(self):
        self.write(self.context, '1.6/Defs/list.xml',
                   '<Defs><ThingDef><defName>External</defName><label>external</label></ThingDef></Defs>')
        self.write(self.source, '1.6/Patches/list.xml',
                   '<Patch><Operation Class="PatchOperationInsert"><xpath>Defs/ThingDef/label</xpath>'
                   '<order>After</order><value><description>must not be imported</description>'
                   '</value></Operation></Patch>')
        result = scan_mod(self.source, game_version='1.6', context_sources=[self.context])
        self.assertEqual(result.entries, [])
        self.assertTrue(any(d['code'] == 'patch-order' for d in result.diagnostics))


if __name__ == '__main__':
    unittest.main()
