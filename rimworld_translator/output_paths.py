"""Where a project's translation MOD is written, and the folders it must never touch.

A project may name its own output folder (``Project.output_folder``, saved in project.json). Empty keeps the
original layout: formal output in ``<project folder>/mod`` and multi-version trial output in ``<project
folder>/mod-test``. Trial output always stays inside the project folder: it is a test artifact.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_FOLDER = 'mod'
TRIAL_FOLDER = 'mod-test'


class OutputLocationError(ValueError):
    """A refused output folder. ``reason`` is a stable code; the message comes in both UI languages."""
    def __init__(self, reason: str, japanese: str, english: str):
        super().__init__(english)
        self.reason, self.japanese, self.english = reason, japanese, english

    def text(self, language: str) -> str:
        return self.japanese if language == 'ja' else self.english


def formal_output(project_path: Path, project) -> Path:
    """The folder the translation MOD (single or formal multi-version output) is written to."""
    chosen = getattr(project, 'output_folder', '') or ''
    return Path(chosen) if chosen else Path(project_path).parent / DEFAULT_FOLDER


def trial_output(project_path: Path, project) -> Path:
    """The folder trial output of all declared versions goes to; never the user's release folder."""
    return Path(project_path).parent / TRIAL_FOLDER


def shown_output(project_path: Path, project) -> Path:
    """The folder the editor shows and opens: the user's folder if set, otherwise as before."""
    if getattr(project, 'output_folder', ''):
        return formal_output(project_path, project)
    return trial_output(project_path, project) if project.version_profiles else formal_output(project_path, project)


def protected_folders(settings_data, games, source) -> list[tuple[str, Path]]:
    """(kind, folder) pairs no output may overlap: the source, Workshop, each game's Data, the user's MOD folders.

    Mods folders are listed as ``mods``: only a separate folder directly inside them may be written.
    """
    from .platforms import mod_roots
    roots = mod_roots(settings_data, games)
    found = [('source', Path(source))] if source else []
    found += [('workshop', path) for path in (*roots.workshop, *(g.workshop for g in games if g.workshop))]
    found += [('data', g.root / 'Data') for g in games]
    found += [('external', path) for path in roots.external]
    found += [('mods', path) for path in (*roots.mods, *(g.mods for g in games))]
    unique, seen = [], set()
    for kind, path in found:
        key = (kind, str(_resolved(path)))
        if key not in seen:
            seen.add(key)
            unique.append((kind, path))
    return unique


def _resolved(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(path).expanduser().absolute()


MESSAGES = {
    'relative': ('出力先は絶対パスで指定してください。', 'Choose an absolute output folder.'),
    'source': ('出力先が元 MOD と重なっています。元 MOD の外のフォルダーを選んでください。',
               'The output folder overlaps the source MOD. Choose a folder outside it.'),
    'workshop': ('出力先が Steam Workshop のフォルダーと重なっています。Workshop の中には書き込みません。',
                 'The output folder overlaps the Steam Workshop folder, which is never written.'),
    'data': ('出力先がゲームの Data フォルダーと重なっています。公式データの中には書き込みません。',
             "The output folder overlaps the game's Data folder, which is never written."),
    'external': ('出力先が、設定で追加した MOD フォルダーと重なっています。そのフォルダーは読み取り専用です。',
                 'The output folder overlaps a MOD folder added in Preferences; those are read-only.'),
    'mods': ('ゲームの Mods フォルダーには、その直下の専用フォルダー（例: Mods/MyTranslation）だけを出力先にできます。',
             "Inside the game's Mods folder, choose a separate folder directly in it (for example Mods/MyTranslation)."),
    'project': ('出力先にプロジェクトのフォルダーそのもの、またはそれを含むフォルダーは選べません。',
                'The output folder cannot be the project folder or contain it.'),
}


def _refuse(reason: str):
    japanese, english = MESSAGES[reason]
    raise OutputLocationError(reason, japanese, english)


def check_output_folder(path: Path | str, *, project_path: Path | None, protected) -> Path:
    """Return the resolved folder, or raise OutputLocationError when it overlaps a protected place."""
    path = Path(path).expanduser()
    if not path.is_absolute():
        _refuse('relative')
    target = _resolved(path)
    for kind, folder in protected:
        folder = _resolved(folder)
        if kind == 'mods':
            # Exactly the arrangement install uses: a separate folder directly inside Mods.
            if target == folder or (folder in target.parents and target.parent != folder) or target in folder.parents:
                _refuse('mods')
            continue
        if target == folder or folder in target.parents or target in folder.parents:
            _refuse(kind)
    if project_path is not None:
        project_folder = _resolved(Path(project_path).parent)
        if target == project_folder or target in project_folder.parents:
            _refuse('project')
    return target


def resolve_output(project_path: Path, project, settings_data, games, *, trial: bool = False) -> Path:
    """The checked output folder for this project: the one every export and install call site uses."""
    folder = trial_output(project_path, project) if trial else formal_output(project_path, project)
    return check_output_folder(folder, project_path=project_path,
                               protected=protected_folders(settings_data, games, project.source))
