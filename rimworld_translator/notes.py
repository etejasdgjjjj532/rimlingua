"""Per-row notes (sticky flags and comments) and per-file translator assignments, stored in project.json."""
from __future__ import annotations

from dataclasses import dataclass

from .core import Entry, Project

FLAGS = ('later', 'question', 'check_in_game', 'done_for_now')
FLAG_LABELS = {'later': '後で見直す', 'question': '質問・要相談', 'check_in_game': 'ゲーム内で確認', 'done_for_now': '一旦完了'}


@dataclass(frozen=True)
class Note:
    text: str = ''
    flag: str = ''


def set_note(project: Project, entry_id: str, text: str = '', flag: str = '') -> None:
    """Store a comment and/or flag on a row. Empty text and flag remove the note."""
    if entry_id not in project.entry_index():
        raise ValueError(f'Unknown entry: {entry_id}')
    if not isinstance(text, str) or not isinstance(flag, str) or (flag and flag not in FLAGS):
        raise ValueError('Invalid note')
    if not text.strip() and not flag:
        project.notes.pop(entry_id, None)
        return
    project.notes[entry_id] = {'text': text, 'flag': flag}


def get_note(project: Project, entry_id: str) -> Note:
    item = project.notes.get(entry_id) or {}
    return Note(item.get('text', ''), item.get('flag', ''))


def list_notes(project: Project, flag: str | None = None) -> list[tuple[str, Note]]:
    """(entry id, note) for every note, in project row order; ``flag`` narrows to one flag."""
    result = []
    for entry in project.entries:
        if entry.id in project.notes:
            note = get_note(project, entry.id)
            if flag is None or note.flag == flag:
                result.append((entry.id, note))
    return result


def assign_file(project: Project, source_file: str, translator: str) -> None:
    """Assign a source file's rows to a translator. An empty name clears the assignment."""
    if source_file not in {entry.source_file for entry in project.entries}:
        raise ValueError(f'Unknown source file: {source_file}')
    translator = translator.strip()
    if translator:
        project.assignments[source_file] = translator
    else:
        project.assignments.pop(source_file, None)


def assignee(project: Project, entry: Entry) -> str:
    return project.assignments.get(entry.source_file, '')


def entries_for(project: Project, translator: str) -> list[Entry]:
    """Rows in the files assigned to ``translator`` (an empty name selects unassigned rows)."""
    return [entry for entry in project.entries if assignee(project, entry) == translator.strip()]


def assignment_summary(project: Project) -> dict[str, dict[str, int]]:
    """translator -> {'files': n, 'rows': n, 'translated': n}; unassigned rows are listed under ''."""
    summary: dict[str, dict[str, int]] = {}
    files: dict[str, set[str]] = {}
    for entry in project.entries:
        who = assignee(project, entry)
        item = summary.setdefault(who, {'files': 0, 'rows': 0, 'translated': 0})
        files.setdefault(who, set()).add(entry.source_file)
        item['rows'] += 1
        item['translated'] += bool(entry.japanese.strip())
    for who, item in summary.items():
        item['files'] = len(files[who])
    return summary
