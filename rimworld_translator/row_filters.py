"""Row filters for the translation table: status, Def type, file, text and note flag."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Iterable

from .core import Entry, Project
from .qa import _translated_pairs, qa_entry

STATUSES = ('untranslated', 'translated', 'needs-review', 'changed', 'stale', 'reviewed', 'qa-error')


def def_type(entry: Entry) -> str:
    """The table's "Def type" column: the Def class for DefInjected rows, else the kind (Keyed / Strings)."""
    return entry.group if entry.kind == 'DefInjected' else entry.kind


def _view(project: Project, entry: Entry, translation: str, language: str) -> Entry:
    """The row as it stands in ``language`` (its translation and review state)."""
    if language == project.language:
        return entry
    state = project.language_states.get(language, {}).get(entry.id, {})
    return replace(entry, japanese=translation, review=state.get('review', False), changed=state.get('changed', False),
                   reviewed=state.get('reviewed', False), approved=state.get('approved', False))


def row_statuses(view: Entry, glossary: dict[str, str] | None = None) -> set[str]:
    """Every filter status the row matches: its ``Entry.status`` plus 'reviewed' and 'qa-error'."""
    found = {view.status}
    if view.reviewed:
        found.add('reviewed')
    if view.japanese.strip() and any(issue.severity == 'error' for issue in qa_entry(view, view.japanese, glossary)):
        found.add('qa-error')
    return found


def filter_rows(project: Project, *, language: str | None = None, status: str | Iterable[str] | None = None,
                def_type: str | None = None, source_file: str | None = None, text: str | None = None,
                flag: str | None = None, assignee: str | None = None) -> list[Entry]:
    """Rows matching every given criterion, in project order. Rows of another language are returned as copies
    carrying that language's translation and state. ``text`` searches English, key and translation."""
    wanted = {status} if isinstance(status, str) else set(status or ())
    if wanted - set(STATUSES):
        raise ValueError('Unknown status: ' + ', '.join(sorted(wanted - set(STATUSES))))
    needle = (text or '').casefold()
    result = []
    for entry, translation in _translated_pairs(project, language):
        view = _view(project, entry, translation, language or project.language)
        if def_type is not None and globals()['def_type'](entry) != def_type:
            continue
        if source_file is not None and entry.source_file != source_file:
            continue
        if flag is not None and (project.notes.get(entry.id) or {}).get('flag', '') != flag:
            continue
        if assignee is not None and project.assignments.get(entry.source_file, '') != assignee:
            continue
        if needle and not any(needle in value.casefold() for value in (view.english, view.key, view.japanese)):
            continue
        if wanted and not wanted & row_statuses(view, project.glossary):
            continue
        result.append(view)
    return result


@dataclass
class Facets:
    def_types: list[tuple[str, int]]
    files: list[tuple[str, int]]
    statuses: dict[str, int]


def facets(project: Project, language: str | None = None) -> Facets:
    """Counts for the filter drop-downs: Def types, source files and statuses (most rows first)."""
    types, files, statuses = Counter(), Counter(), Counter()
    for entry, translation in _translated_pairs(project, language):
        view = _view(project, entry, translation, language or project.language)
        types[def_type(entry)] += 1
        files[entry.source_file] += 1
        statuses.update(row_statuses(view, project.glossary))
    order = lambda counter: sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return Facets(order(types), order(files), {name: statuses.get(name, 0) for name in STATUSES})
