"""Chapter 3 backend: glossary, translation memory, official suggestions, batch apply, filters, progress."""
from pathlib import Path
import tempfile
import unittest

from rimworld_translator import glossary, progress, row_filters, translation_memory, workflow
from rimworld_translator.core import Entry, Project
from rimworld_translator.official_translations import OfficialIndex


def row(key, english, japanese='', kind='DefInjected', group='ThingDef', source='Defs/a.xml', **flags):
    return Entry(f'{kind}:{group}:{key}', kind, group, key, english, source, japanese, **flags)


def make(entries, name='Example', package='local.translation.aids'):
    return Project('/nonexistent/source', name, package, 'author.original', ['1.6'], entries, [])


class GlossaryTests(unittest.TestCase):
    def test_collect_terms_from_short_labels(self):
        project = make([row('Gun.label', 'rifle', 'ライフル'), row('Gun2.label', 'Rifle', 'ライフル'),
                        row('Gun.description', 'A long sentence about a rifle that goes on.', '説明')])
        terms = glossary.collect_terms(project, min_count=2)
        self.assertEqual([(t.term, t.translation, t.count) for t in terms], [('rifle', 'ライフル', 2)])

    def test_already_known_terms_are_not_suggested(self):
        project = make([row('A.label', 'rifle', 'ライフル'), row('B.label', 'rifle', 'ライフル')])
        project.glossary['Rifle'] = 'ライフル'
        self.assertEqual(glossary.collect_terms(project, min_count=2), [])

    def test_inconsistent_renderings(self):
        project = make([row('A.label', 'rifle', 'ライフル'), row('B.label', 'rifle', '小銃'),
                        row('C.label', 'rifle', 'ライフル'), row('D.label', 'pistol', '拳銃')])
        found = glossary.inconsistent_terms(project)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].term, 'rifle')
        self.assertEqual(found[0].renderings, {'ライフル': ['DefInjected:ThingDef:A.label', 'DefInjected:ThingDef:C.label'],
                                               '小銃': ['DefInjected:ThingDef:B.label']})

    def test_adopt_terms_writes_project_glossary(self):
        project = make([row('A.label', 'rifle', 'ライフル'), row('B.label', 'rifle', 'ライフル')])
        glossary.adopt_terms(project, glossary.collect_terms(project, min_count=2))
        self.assertEqual(project.glossary, {'rifle': 'ライフル'})

    def test_official_glossary_candidates_align_with_the_official_wording(self):
        index = OfficialIndex()
        index.add('Keyed', '', 'X', 'rifle', '小銃')
        project = make([row('A.label', 'rifle', 'ライフル')])
        found = glossary.official_alignments(project, index)
        self.assertEqual([(f.term, f.official, f.current) for f in found], [('rifle', '小銃', 'ライフル')])


class TranslationMemoryTests(unittest.TestCase):
    def test_remember_and_lookup_across_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / 'tm.json'
            memory = translation_memory.TranslationMemory(store)
            one = make([row('A.label', 'rifle', 'ライフル'), row('B.label', 'Hit {0}', '命中')])
            memory.add_project(one, 'Japanese')
            memory.save()
            reopened = translation_memory.TranslationMemory(store)
            hits = reopened.lookup('rifle', 'Japanese')
            self.assertEqual([(h.translation, h.exact) for h in hits], [('ライフル', True)])
            # a translation that breaks placeholders is never remembered
            self.assertEqual(reopened.lookup('Hit {0}', 'Japanese'), [])

    def test_fuzzy_matches_and_most_used_first(self):
        memory = translation_memory.TranslationMemory(None)
        memory.add('Fire at will now', 'Japanese', '自由射撃', 'p1')
        memory.add('Fire at will now', 'Japanese', '自由射撃', 'p2')
        memory.add('Fire at will now', 'Japanese', '好きに撃て', 'p3')
        hits = memory.lookup('Fire at will now', 'Japanese')
        self.assertEqual([h.translation for h in hits], ['自由射撃', '好きに撃て'])
        self.assertEqual(hits[0].count, 2)
        near = memory.lookup('Fire at will now!', 'Japanese')
        self.assertEqual([(h.translation, h.exact) for h in near][0], ('自由射撃', False))
        self.assertEqual(memory.lookup('Completely different', 'Japanese'), [])

    def test_suggest_for_project_entry_skips_current_translation(self):
        memory = translation_memory.TranslationMemory(None)
        memory.add('rifle', 'Japanese', 'ライフル', 'p1')
        project = make([row('A.label', 'rifle')])
        self.assertEqual([h.translation for h in memory.suggest(project, 'DefInjected:ThingDef:A.label')], ['ライフル'])

    def test_corrupt_store_is_kept_aside_and_starts_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / 'tm.json'
            store.write_text('not json', encoding='utf-8')
            memory = translation_memory.TranslationMemory(store)
            self.assertEqual(len(memory), 0)
            self.assertTrue(memory.kept_aside and memory.kept_aside.is_file())


class OfficialSuggestionTests(unittest.TestCase):
    def test_suggestions_for_an_entry(self):
        index = OfficialIndex()
        index.add('Keyed', '', 'X', 'Cancel', 'キャンセル')
        project = make([row('A', 'Cancel', kind='Keyed', group='Keyed')])
        self.assertEqual(translation_memory.official_suggestions(project, 'Keyed:Keyed:A', index), ['キャンセル'])


class IdenticalEnglishTests(unittest.TestCase):
    def test_groups_of_identical_english(self):
        project = make([row('A.label', 'Raider 1'), row('B.label', 'Raider 1', 'レイダー1'), row('C.label', 'Other')])
        groups = workflow.identical_english_groups(project)
        self.assertEqual([(g.english, len(g.entry_ids), g.untranslated) for g in groups], [('Raider 1', 2, 1)])

    def test_preview_and_apply_fill_only_empty_rows(self):
        project = make([row('A.label', 'Raider 1', 'レイダー1'), row('B.label', 'Raider 1'), row('C.label', 'Raider 1')])
        preview = workflow.preview_apply_identical(project, 'DefInjected:ThingDef:A.label')
        self.assertEqual([c.id for c in preview.changes], ['DefInjected:ThingDef:B.label', 'DefInjected:ThingDef:C.label'])
        workflow.apply_changes(project, preview.changes)
        self.assertEqual(project.entries[1].japanese, 'レイダー1')

    def test_existing_different_translations_need_overwrite(self):
        project = make([row('A.label', 'Raider 1', '新しい'), row('B.label', 'Raider 1', 'ほか')])
        keep = workflow.preview_apply_identical(project, 'DefInjected:ThingDef:A.label')
        self.assertEqual(keep.changes, [])
        self.assertEqual(len(keep.conflicts), 1)
        over = workflow.preview_apply_identical(project, 'DefInjected:ThingDef:A.label', overwrite=True)
        self.assertEqual([c.id for c in over.changes], ['DefInjected:ThingDef:B.label'])

    def test_a_source_row_without_translation_is_refused(self):
        project = make([row('A.label', 'Raider 1'), row('B.label', 'Raider 1')])
        with self.assertRaises(ValueError):
            workflow.preview_apply_identical(project, 'DefInjected:ThingDef:A.label')


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.project = make([
            row('A.label', 'a', 'あ', source='Defs/Things.xml'),
            row('B.label', 'b', source='Defs/Things.xml'),
            row('C.label', 'c', 'し', group='RecipeDef', source='Defs/Recipes.xml', changed=True),
            row('D.label', 'd', 'で', review=True),
            row('E', 'e', 'い', kind='Keyed', group='Keyed', source='Keyed/Main.xml'),
            row('F.label', 'f', 'ふ', stale=True),
        ])

    def ids(self, **kw):
        return [e.key for e in row_filters.filter_rows(self.project, **kw)]

    def test_status_filters(self):
        self.assertEqual(self.ids(status='untranslated'), ['B.label'])
        self.assertEqual(self.ids(status='changed'), ['C.label'])
        self.assertEqual(self.ids(status='needs-review'), ['D.label'])
        self.assertEqual(self.ids(status='stale'), ['F.label'])

    def test_def_type_file_and_text(self):
        self.assertEqual(self.ids(def_type='RecipeDef'), ['C.label'])
        self.assertEqual(self.ids(def_type='Keyed'), ['E'])
        self.assertEqual(self.ids(source_file='Defs/Things.xml'), ['A.label', 'B.label'])
        self.assertEqual(self.ids(text='し'), ['C.label'])
        self.assertEqual(self.ids(status='translated', def_type='ThingDef', source_file='Defs/Things.xml'), ['A.label'])

    def test_note_flag_filter(self):
        from rimworld_translator import notes
        notes.set_note(self.project, 'DefInjected:ThingDef:A.label', 'x', 'later')
        self.assertEqual(self.ids(flag='later'), ['A.label'])

    def test_facets_count_rows(self):
        facets = row_filters.facets(self.project)
        self.assertEqual(dict(facets.def_types), {'ThingDef': 4, 'RecipeDef': 1, 'Keyed': 1})
        self.assertEqual(dict(facets.files)['Defs/Things.xml'], 2)
        self.assertEqual(facets.statuses['untranslated'], 1)

    def test_unknown_status_is_refused(self):
        with self.assertRaises(ValueError):
            row_filters.filter_rows(self.project, status='nope')


class ProgressTests(unittest.TestCase):
    def test_reviewed_row_with_a_qa_error_does_not_count(self):
        project = make([row('A', 'Hit {0}', '命中', kind='Keyed', group='Keyed', reviewed=True)])
        self.assertEqual(progress.progress(project).reviewed, 0)

    def test_overall_and_p0_progress(self):
        project = make([row('A.label', 'a', 'あ'), row('A.description', 'ad', 'せつ'), row('B.label', 'b'),
                        row('C.jobString', 'job', 'しごと', ), row('D.text', 'd', ''),
                        row('X', 'x', 'で', kind='Keyed', group='Keyed', reviewed=True),
                        row('S', 's', 'す', stale=True)])
        result = progress.progress(project)
        self.assertEqual((result.total, result.translated), (6, 4))
        self.assertEqual((result.p0_total, result.p0_translated), (3, 2))
        self.assertAlmostEqual(result.p0_percent, 66.7, places=1)
        self.assertEqual(result.reviewed, 1)


if __name__ == '__main__':
    unittest.main()
