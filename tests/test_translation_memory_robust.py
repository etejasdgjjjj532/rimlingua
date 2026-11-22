"""A bad translation-memory file must never abort loading, saving or exporting; it is kept aside with a unique name."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rimworld_translator.editor_panel import EditorPanelMixin
from rimworld_translator.translation_memory import TranslationMemory

GOOD = {'ja': {'Hello': {'こんにちは': {'count': 2, 'projects': ['a.b']}}}}


class MemoryLoadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'translation-memory.json'

    def write(self, memory):
        self.path.write_text(json.dumps({'schema': 1, 'memory': memory}), encoding='utf-8')

    def test_valid_memory_loads(self):
        self.write(GOOD)
        self.assertEqual(len(TranslationMemory(self.path)), 1)

    def test_bad_nested_structures_are_kept_aside_and_memory_starts_empty(self):
        for bad in ({'ja': []}, {'ja': {'Hello': 'x'}}, {'ja': {'Hello': {'t': 5}}},
                    {'ja': {'Hello': {'t': {'count': 'many', 'projects': []}}}},
                    {'ja': {'Hello': {'t': {'count': 1, 'projects': 'a'}}}}):
            for old in self.root.glob('translation-memory*'):
                old.unlink()
            self.write(bad)
            memory = TranslationMemory(self.path)
            self.assertEqual(len(memory), 0, bad)
            self.assertIsNotNone(memory.kept_aside, bad)
            memory.add('Hello', 'ja', 'やあ', 'p')  # must not raise
            memory.save()

    def test_keep_aside_never_overwrites_an_earlier_one(self):
        first = self.root / 'translation-memory.json.corrupt'
        first.write_text('older evidence')
        self.path.write_text('{broken', encoding='utf-8')
        memory = TranslationMemory(self.path)
        self.assertNotEqual(memory.kept_aside, first)
        self.assertEqual(first.read_text(), 'older evidence')
        self.assertTrue(memory.kept_aside.exists())
        self.path.write_text('{broken again', encoding='utf-8')
        second = TranslationMemory(self.path).kept_aside
        self.assertNotIn(second, (first, memory.kept_aside))
        self.assertEqual(memory.kept_aside.read_text(), '{broken')


class RememberTests(unittest.TestCase):
    def test_any_exception_from_the_memory_is_swallowed(self):
        class Broken:
            def forget_project(self, *_):
                raise KeyError('bad structure')
        panel = SimpleNamespace(project=SimpleNamespace(package_id='x'), memory=lambda: Broken(), _suggest_cache='old')
        EditorPanelMixin.remember_translations(panel)
        self.assertIsNone(panel._suggest_cache)


if __name__ == '__main__':
    unittest.main()
