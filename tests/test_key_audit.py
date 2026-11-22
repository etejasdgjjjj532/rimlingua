"""The tracked key audit: answer keys from a MOD's own translations and official patterns, and the scores."""
from pathlib import Path
import tempfile
import unittest

from tools import key_audit


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class AnswerKeyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'mod'
        write(self.root / 'About/About.xml', '<ModMetaData><packageId>a.b</packageId></ModMetaData>')

    def test_other_language_keys_of_every_load_folder_are_answers(self):
        write(self.root / 'LoadFolders.xml', '<loadFolders><v1.6><li>/</li><li IfModNotActive="x.y">Extra</li>'
              '</v1.6></loadFolders>')
        write(self.root / 'Languages/Japanese/DefInjected/ThingDef/a.xml',
              '<LanguageData><Gun.label>銃</Gun.label><Empty.label></Empty.label></LanguageData>')
        write(self.root / 'Extra/Languages/German/Keyed/k.xml', '<LanguageData><Hello>Hallo</Hello></LanguageData>')
        write(self.root / 'Languages/English/Keyed/k.xml', '<LanguageData><Hello>Hello</Hello></LanguageData>')
        keys = key_audit.translated_keys(self.root, '1.6')
        self.assertEqual(keys, {('DefInjected', 'gun.label'), ('Keyed', 'hello')})

    def test_only_keys_of_the_mods_own_defs_and_keyed_catalog_are_answers(self):
        # A pure translation MOD (or keys of generated or other MODs' Defs) is not the scanned MOD's text.
        write(self.root / 'Defs/a.xml', '<Defs><ThingDef><defName>Gun</defName></ThingDef></Defs>')
        write(self.root / 'Languages/English/Keyed/k.xml', '<LanguageData><Hello>Hello</Hello></LanguageData>')
        truth = {('DefInjected', 'gun.label'), ('DefInjected', 'steel.label'), ('Keyed', 'hello'), ('Keyed', 'corekey')}
        self.assertEqual(key_audit.answerable(truth, self.root, '1.6'), {('DefInjected', 'gun.label'), ('Keyed', 'hello')})

    def test_folders_of_another_version_are_not_answers(self):
        write(self.root / '1.5/Languages/Japanese/Keyed/k.xml', '<LanguageData><Old>古い</Old></LanguageData>')
        write(self.root / '1.6/Languages/Japanese/Keyed/k.xml', '<LanguageData><New>新しい</New></LanguageData>')
        self.assertEqual(key_audit.translated_keys(self.root, '1.6'), {('Keyed', 'new')})


class ScoreTests(unittest.TestCase):
    def test_recall_and_precision_counts(self):
        rows = [
            {'cat': 'entry', 'kind': 'DefInjected', 'group': 'ThingDef', 'key': 'Gun.label', 'text': 'gun', 'ev': [],
             'blocked': False},
            {'cat': 'entry', 'kind': 'DefInjected', 'group': 'ThingDef', 'key': 'Gun.tag', 'text': 'Gun_Tex',
             'ev': [], 'blocked': False},
            {'cat': 'entry', 'kind': 'DefInjected', 'group': 'ThingDef', 'key': 'Gun.note', 'text': 'Some note',
             'ev': ['CLR Verse.ThingDef.note: MayTranslateAttribute'], 'blocked': True},
            {'cat': 'entry', 'kind': 'Keyed', 'group': 'Keyed', 'key': 'Hello', 'text': 'Hello', 'ev': [],
             'blocked': False},
            {'cat': 'unknown-field', 'owner': 'ThingDef', 'path': 'Gun.description', 'text': 'A gun'},
        ]
        truth = {('DefInjected', 'gun.label'), ('DefInjected', 'gun.description'), ('Keyed', 'hello')}
        official = {('ThingDef', 'description', 'description')}
        score = key_audit.score_rows(rows, truth, official, internal_names={'Gun_Tex'})
        self.assertEqual(score['truth'], 3)
        self.assertEqual(score['truth_hit'], 2)
        self.assertEqual(score['entries'], 4)
        self.assertEqual(score['blocked'], 1)
        self.assertEqual(score['evidenced'], 3)  # label (T), note (A), Hello (K and T)
        self.assertEqual(score['proven_internal'], 1)
        self.assertEqual(score['official_missed'], 1)

    def test_case_insensitive_match_only_for_asset_paths(self):
        rows = [{'cat': 'entry', 'kind': 'DefInjected', 'group': 'ThingDef', 'key': f'A{i}.label', 'text': text,
                 'ev': [], 'blocked': False} for i, text in enumerate(('Knarloc', 'Things/Knarloc', 'things/knarloc'))]
        score = key_audit.score_rows(rows, set(), set(), internal_names={'things/knarloc', 'knarloc'})
        self.assertEqual(score['proven_internal'], 2)  # a label spelled like a defName in another case is a label

    def test_summary_rates(self):
        total = key_audit.summarize([{'truth': 4, 'truth_hit': 3, 'entries': 10, 'evidenced': 8,
                                      'proven_internal': 1, 'blocked': 0, 'official_missed': 2}])
        self.assertAlmostEqual(total['recall'], 0.75)
        self.assertAlmostEqual(total['precision'], 0.9)
        self.assertAlmostEqual(total['evidenced_share'], 0.8)


if __name__ == '__main__':
    unittest.main()
