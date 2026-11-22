"""Translation progress, overall and for the player-visible core (P0: names and descriptions)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .core import Project
from .qa import _skippable, _translated_pairs, review_blockers

# Item, building, pawn and research names and descriptions (priority P0: player-visible text).
P0_SUFFIXES = {'label', 'labelPlural', 'labelShort', 'labelNoun', 'pawnLabel', 'description', 'descriptionShort'}


def is_p0(entry) -> bool:
    return entry.kind == 'DefInjected' and entry.key.rsplit('.', 1)[-1] in P0_SUFFIXES


@dataclass(frozen=True)
class Progress:
    total: int
    translated: int
    reviewed: int
    approved: int
    needs_review: int
    p0_total: int
    p0_translated: int

    @property
    def untranslated(self) -> int:
        return self.total - self.translated

    @staticmethod
    def _percent(done: int, total: int) -> float:
        return round(100.0 * done / total, 1) if total else 100.0

    @property
    def percent(self) -> float:
        return self._percent(self.translated, self.total)

    @property
    def p0_percent(self) -> float:
        return self._percent(self.p0_translated, self.p0_total)


def progress(project: Project, language: str | None = None) -> Progress:
    """Counts rows that can be exported (not stale, blocked, excluded or internal)."""
    language = language or project.language
    states = project.language_states.get(language, {})
    total = translated = reviewed = approved = needs = p0_total = p0_done = 0
    for entry, translation in _translated_pairs(project, language):
        if _skippable(entry):
            continue
        state = entry.__dict__ if language == project.language else states.get(entry.id, {})
        total += 1
        done = bool(translation.strip())
        translated += done
        # A reviewed row that now has a QA error does not count as reviewed until it is fixed.
        reviewed += bool(done and state.get('reviewed', False) and not review_blockers(entry, translation, project.glossary))
        approved += bool(done and state.get('approved', False))
        needs += bool(done and (state.get('review', False) or state.get('changed', False)))
        if is_p0(entry):
            p0_total += 1
            p0_done += done
    return Progress(total, translated, reviewed, approved, needs, p0_total, p0_done)


def progress_by_file(project: Project, language: str | None = None) -> dict[str, tuple[int, int]]:
    """source file -> (rows, translated rows), for a per-file overview or translator hand-over."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for entry, translation in _translated_pairs(project, language):
        if _skippable(entry):
            continue
        counts[entry.source_file][0] += 1
        counts[entry.source_file][1] += bool(translation.strip())
    return {name: (total, done) for name, (total, done) in sorted(counts.items())}
