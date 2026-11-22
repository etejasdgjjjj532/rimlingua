"""Translation memory shared across projects, plus suggestions from the official translation pack.

The memory only remembers clean work: translated, not stale, free of QA errors and not left as English.
It is advice for the translator; nothing is written to a project automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
from pathlib import Path

from .core import Project, atomic_write
from .qa import _same_as_source, _skippable, _translated_pairs, qa_entry

FUZZY_THRESHOLD = 0.85
MAX_SEGMENT = 400


@dataclass(frozen=True)
class TmHit:
    english: str
    translation: str
    count: int
    projects: tuple[str, ...]
    exact: bool
    score: float


class TranslationMemory:
    """language -> English -> translation -> {'count', 'projects'}, optionally persisted as JSON at ``path``."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.data: dict[str, dict[str, dict[str, dict]]] = {}
        self.kept_aside: Path | None = None
        if self.path is not None and self.path.is_file():
            self._load()

    def __len__(self) -> int:
        return sum(len(table) for table in self.data.values())

    @staticmethod
    def _valid(memory) -> bool:
        """language -> English -> translation -> {'count': int, 'projects': [str, ...]}, all the way down."""
        if not isinstance(memory, dict):
            return False
        for language, table in memory.items():
            if not isinstance(language, str) or not isinstance(table, dict):
                return False
            for english, translations in table.items():
                if not isinstance(english, str) or not isinstance(translations, dict):
                    return False
                for translation, item in translations.items():
                    if (not isinstance(translation, str) or not isinstance(item, dict)
                            or type(item.get('count')) is not int
                            or not isinstance(item.get('projects'), list)
                            or not all(isinstance(project, str) for project in item['projects'])):
                        return False
        return True

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict) or payload.get('schema') != 1 or not self._valid(payload.get('memory')):
                raise ValueError('unsupported translation memory')
            self.data = payload['memory']
        except (ValueError, UnicodeDecodeError, OSError, RecursionError):
            # An unreadable memory is only a cache of earlier work; keep the bytes (never over an earlier keep) and start empty.
            import datetime
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            kept, number = self.path.with_name(f'{self.path.name}.corrupt-{stamp}'), 1
            while kept.exists():
                number += 1
                kept = self.path.with_name(f'{self.path.name}.corrupt-{stamp}-{number}')
            try:
                self.path.replace(kept)
                self.kept_aside = kept
            except OSError:
                pass
            self.data = {}

    def save(self) -> None:
        if self.path is None:
            raise ValueError('This translation memory has no file')
        atomic_write(self.path, (json.dumps({'schema': 1, 'memory': self.data}, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))

    def add(self, english: str, language: str, translation: str, project_id: str = '') -> None:
        english, translation = english.strip(), translation.strip()
        if not english or not translation or len(english) > MAX_SEGMENT:
            return
        item = self.data.setdefault(language, {}).setdefault(english, {}).setdefault(translation, {'count': 0, 'projects': []})
        item['count'] += 1
        if project_id and project_id not in item['projects']:
            item['projects'].append(project_id)

    def add_project(self, project: Project, language: str | None = None, project_id: str | None = None) -> int:
        """Remember every clean translation of ``project``; returns how many rows were taken."""
        language = language or project.language
        project_id = project_id or project.package_id
        project.stash_current_language()
        taken = 0
        for entry, translation in _translated_pairs(project, language):
            if (not translation.strip() or _skippable(entry) or _same_as_source(entry, translation)
                    or any(issue.severity == 'error' for issue in qa_entry(entry, translation))):
                continue
            self.add(entry.english, language, translation, project_id)
            taken += 1
        return taken

    def forget_project(self, project_id: str) -> None:
        """Drop one project's contribution (counts keep what other projects contributed only if they are listed)."""
        for table in self.data.values():
            for english in list(table):
                for translation in list(table[english]):
                    item = table[english][translation]
                    if project_id in item['projects']:
                        item['projects'].remove(project_id)
                        item['count'] = max(len(item['projects']), 0)
                        if not item['projects']:
                            del table[english][translation]
                if not table[english]:
                    del table[english]

    def lookup(self, english: str, language: str, limit: int = 5, fuzzy: bool = True) -> list[TmHit]:
        """Exact matches first, then near matches (similarity >= 0.85); within a tier, higher score and more use first."""
        english = english.strip()
        table = self.data.get(language, {})
        hits = []
        if english in table:
            hits.extend(self._hits(english, table[english], True, 1.0))
        if fuzzy and english:
            matcher = difflib.SequenceMatcher(autojunk=False)
            matcher.set_seq2(english)
            for other, translations in table.items():
                if other == english or abs(len(other) - len(english)) > max(5, len(english) * 0.3):
                    continue
                matcher.set_seq1(other)
                if matcher.real_quick_ratio() < FUZZY_THRESHOLD or matcher.quick_ratio() < FUZZY_THRESHOLD:
                    continue
                score = matcher.ratio()
                if score >= FUZZY_THRESHOLD:
                    hits.extend(self._hits(other, translations, False, score))
        hits.sort(key=lambda hit: (not hit.exact, -hit.score, -hit.count, hit.translation))
        return hits[:limit]

    @staticmethod
    def _hits(english: str, translations: dict, exact: bool, score: float) -> list[TmHit]:
        return [TmHit(english, text, item['count'], tuple(item['projects']), exact, score)
                for text, item in sorted(translations.items(), key=lambda pair: (-pair[1]['count'], pair[0]))]

    def suggest(self, project: Project, entry_id: str, language: str | None = None, limit: int = 5) -> list[TmHit]:
        """Memory hits for one project row, without the translation it already has."""
        language = language or project.language
        entry = project.entry_index().get(entry_id)
        if entry is None:
            raise ValueError(f'Unknown entry: {entry_id}')
        current = project.get_translation(entry_id, language).strip()
        return [hit for hit in self.lookup(entry.english, language, limit + 1) if hit.translation != current][:limit]


def official_suggestions(project: Project, entry_id: str, index, limit: int = 3) -> list[str]:
    """Official translations (an ``OfficialIndex`` from ``official_translations.official_index``) for one row."""
    entry = project.entry_index().get(entry_id)
    if entry is None:
        raise ValueError(f'Unknown entry: {entry_id}')
    return index.suggest(entry, limit)
