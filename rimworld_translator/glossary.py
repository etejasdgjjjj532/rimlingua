"""Glossary support: collect terms from the project's short labels, flag inconsistent renderings, align with official wording."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re

from .core import Project, TOKENS
from .qa import _TAG, _skippable, _translated_pairs
from .workflow import set_glossary_term

_LABEL_SUFFIXES = {'label', 'labelPlural', 'labelShort', 'pawnLabel', 'labelNoun'}


@dataclass(frozen=True)
class GlossaryTerm:
    term: str
    translation: str
    count: int
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class TermInconsistency:
    """One English term rendered several ways; ``renderings`` maps each translation to its entry ids."""
    term: str
    renderings: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class OfficialAlignment:
    """A project term whose translation differs from the official Japanese pack's wording."""
    term: str
    current: str
    official: str
    entry_ids: tuple[str, ...]


def _term_rows(project: Project, language: str | None, max_words: int):
    """(english term, translation, entry id) of rows that look like names rather than sentences."""
    for entry, translation in _translated_pairs(project, language):
        text = entry.english.strip()
        translation = translation.strip()
        if (not translation or _skippable(entry) or not text or len(text) > 40 or TOKENS.search(text)
                or _TAG.search(text) or text.endswith(('.', '!', '?')) or len(text.split()) > max_words):
            continue
        last = entry.key.rsplit('.', 1)[-1]
        if entry.kind == 'DefInjected' and last not in _LABEL_SUFFIXES:
            continue
        if entry.kind == 'Strings' or text.casefold() == translation.casefold():
            continue
        yield text, translation, entry.id


def _group(project: Project, language: str | None, max_words: int) -> dict[str, dict[str, list[str]]]:
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    shown: dict[str, str] = {}
    for text, translation, entry_id in _term_rows(project, language, max_words):
        shown.setdefault(text.casefold(), text)
        groups[text.casefold()][translation].append(entry_id)
    return {shown[key]: dict(renderings) for key, renderings in groups.items()}


def collect_terms(project: Project, language: str | None = None, min_count: int = 2, max_words: int = 3) -> list[GlossaryTerm]:
    """Names the project already translates the same way at least ``min_count`` times, minus terms already in the glossary.

    The most used translation of a term is the candidate; see ``inconsistent_terms`` for terms with several.
    """
    known = {key.casefold() for key in project.glossary}
    terms = []
    for term, renderings in _group(project, language, max_words).items():
        if term.casefold() in known:
            continue
        translation, ids = max(renderings.items(), key=lambda item: (len(item[1]), item[0]))
        if len(ids) >= min_count:
            terms.append(GlossaryTerm(term, translation, len(ids), tuple(ids)))
    return sorted(terms, key=lambda t: (-t.count, t.term.casefold()))


def inconsistent_terms(project: Project, language: str | None = None, max_words: int = 3) -> list[TermInconsistency]:
    """English names with more than one translation. Often a mistake; sometimes a deliberate context split."""
    result = []
    for term, renderings in _group(project, language, max_words).items():
        if len(renderings) > 1:
            ordered = dict(sorted(renderings.items(), key=lambda item: (-len(item[1]), item[0])))
            result.append(TermInconsistency(term, ordered))
    return sorted(result, key=lambda item: item.term.casefold())


def adopt_terms(project: Project, terms: list[GlossaryTerm]) -> int:
    """Add the chosen candidates to the project glossary; returns how many were added."""
    for item in terms:
        set_glossary_term(project, item.term, item.translation)
    return len(terms)


def official_alignments(project: Project, index, language: str | None = None, max_words: int = 3) -> list[OfficialAlignment]:
    """Terms where the official Japanese pack (an ``OfficialIndex``) words a name differently from the project."""
    result = []
    for term, renderings in _group(project, language, max_words).items():
        official = index.by_english.get(term)
        if not official:
            continue
        wording = official.most_common(1)[0][0]
        for current, ids in renderings.items():
            if current != wording:
                result.append(OfficialAlignment(term, current, wording, tuple(ids)))
    return sorted(result, key=lambda item: (item.term.casefold(), item.current))
