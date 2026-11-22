"""Small user-owned preferences; project text remains in project.json."""
from __future__ import annotations
from datetime import datetime
import json
import os
from pathlib import Path
from .core import atomic_write

UI_LANGUAGES = ('system', 'ja', 'en')

DEFAULTS = {'ui_language':'system','font_size':11,'tutorial_dismissed':False,'recent_projects':[],
            'favorite_sources':[],'game_paths':[],'game_library':'','inspect_metadata':True,
            'release_repository':'','check_updates':False,'theme_mode':'system','show_tree':True,'reduce_motion':False,'daily_counts':{},
            # Read-only MOD folders; empty means auto-detect.
            'workshop_folder':'','mods_folder':'','external_mod_folders':[],
            # Where the game keeps its MOD list; empty means the native or Proton profile is searched.
            'mods_config_path':'',
            'default_translator':'','default_license':'','default_languages':['Japanese'],
            'cache_directory':'','autosave_seconds':60,
            # How many file-backend checkpoints (.history) a project keeps; 0 keeps every one.
            'backup_generations':0}
# Personal history and counters stay on this computer; everything else can move to another one.
NOT_EXPORTED = ('recent_projects','daily_counts')
STRING_KEYS = ('game_library','release_repository','workshop_folder','mods_folder','mods_config_path',
               'default_translator','default_license','cache_directory')
PATH_LIST_KEYS = ('recent_projects','favorite_sources','game_paths','external_mod_folders')
AUTOSAVE_RANGE = (10,3600)
BACKUP_GENERATIONS_MAX = 9999


def _fresh_defaults():
    return json.loads(json.dumps(DEFAULTS))


def resolve_ui_language(value, system_languages=None) -> str:
    """Turn the stored interface language ('system', 'ja' or 'en') into the language the editor shows.

    'system' follows the OS language list: English whenever English appears in it (even behind Japanese), else
    Japanese when the list has Japanese, and English for any other OS language. An unknown stored value behaves
    like 'system'. `system_languages` (BCP 47 tags, most preferred first) replaces the OS query in tests.
    """
    if value in ('ja', 'en'):
        return value
    if system_languages is None:
        from PySide6.QtCore import QLocale
        system_languages = QLocale.system().uiLanguages()
    primaries = {str(tag).replace('_', '-').split('-')[0].lower() for tag in system_languages}
    if 'en' in primaries:
        return 'en'
    return 'ja' if 'ja' in primaries else 'en'


def normalize(data: dict) -> dict:
    """Replace every invalid value with its default, in place; unknown keys never reach ``data``."""
    for field in PATH_LIST_KEYS:
        if not isinstance(data[field],list) or not all(isinstance(p,str) for p in data[field]):
            data[field] = []
    counts = data['daily_counts']
    if not isinstance(counts,dict) or not all(isinstance(k,str) and type(v) is int and v>=0 for k,v in counts.items()):
        data['daily_counts'] = {}
    for field in STRING_KEYS:
        if not isinstance(data[field],str):
            data[field] = ''
    for field in ('show_tree','tutorial_dismissed','inspect_metadata','check_updates'):
        if not isinstance(data[field],bool):
            data[field] = DEFAULTS[field]
    if not isinstance(data['reduce_motion'],bool):
        data['reduce_motion'] = False
    if not isinstance(data['theme_mode'],str) or data['theme_mode'] not in {'system','light','dark'}:
        data['theme_mode'] = 'system'
    if not isinstance(data['ui_language'],str) or data['ui_language'] not in UI_LANGUAGES:
        data['ui_language'] = DEFAULTS['ui_language']
    if type(data['font_size']) is not int or not 8<=data['font_size']<=24:
        data['font_size'] = 11
    seconds = data['autosave_seconds']
    if type(seconds) is not int or not (seconds==0 or AUTOSAVE_RANGE[0]<=seconds<=AUTOSAVE_RANGE[1]):
        data['autosave_seconds'] = 60
    generations = data['backup_generations']
    if type(generations) is not int or not 0<=generations<=BACKUP_GENERATIONS_MAX:
        data['backup_generations'] = 0
    from .languages import LANGUAGES
    languages = data['default_languages']
    # Check the element types before hashing them: ``set`` raises TypeError for a nested list or dict.
    if (not isinstance(languages,list) or not languages
            or any(not isinstance(code,str) or code not in LANGUAGES for code in languages)
            or len(set(languages))!=len(languages)):
        data['default_languages'] = ['Japanese']
    return data


class SettingsStore:
    def __init__(self, path: Path | None = None):
        if path is None and os.environ.get('RW_TRANSLATOR_SETTINGS'):
            path = Path(os.environ['RW_TRANSLATOR_SETTINGS'])
        if path is None:
            from PySide6.QtCore import QStandardPaths
            path = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))/'rimworld-translator-settings.json'
        self.path = Path(path)
        self.data = _fresh_defaults()
        self.load_error = ''
        # A broken file is moved here before defaults can be saved over it.
        self.kept_aside: Path | None = None
        if self.path.is_file():
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value,dict):
                    raise ValueError('The settings file does not hold an object')
                self.data.update({k:v for k,v in value.items() if k in self.data})
            except (ValueError,RecursionError) as exc:  # also undecodable bytes and absurdly nested JSON
                self.load_error = str(exc)
                self._keep_aside()
            except OSError as exc:
                self.load_error = str(exc)
        normalize(self.data)

    def _keep_aside(self):
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        target = self.path.with_name(f'{self.path.stem}.broken-{stamp}{self.path.suffix}')
        number = 2
        while target.exists():
            target = self.path.with_name(f'{self.path.stem}.broken-{stamp}-{number}{self.path.suffix}')
            number += 1
        try:
            os.replace(self.path,target)
            self.kept_aside = target
        except OSError:
            self.kept_aside = None

    def save(self):
        raw = (json.dumps(self.data,ensure_ascii=False,indent=2)+'\n').encode()
        if not self.path.exists() or self.path.read_bytes()!=raw:
            atomic_write(self.path,raw)

    def export_to(self, path: Path):
        """Write the portable preferences; recent projects and daily counts stay here."""
        portable = {k:v for k,v in self.data.items() if k not in NOT_EXPORTED}
        atomic_write(Path(path),(json.dumps(portable,ensure_ascii=False,indent=2)+'\n').encode())

    def import_from(self, path: Path):
        """Take known, valid preferences from an exported file and save them; the rest keeps its value."""
        path = Path(path)
        if path.stat().st_size > 1024*1024:
            raise ValueError('The settings file is too large')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except RecursionError as exc:
            raise ValueError('The settings file is nested too deeply') from exc
        if not isinstance(value,dict):
            raise ValueError('This file does not contain editor settings')
        candidate = json.loads(json.dumps(self.data))
        candidate.update({k:v for k,v in value.items() if k in candidate and k not in NOT_EXPORTED})
        self.data = normalize(candidate)
        self.save()

    def remember_project(self, path: Path):
        value = str(path.resolve())
        self.data['recent_projects'] = [value,*[p for p in self.data['recent_projects'] if p!=value]][:15]
        self.save()

    def toggle_favorite(self, path: Path):
        value = str(path.resolve())
        current = self.data['favorite_sources']
        if value in current:
            current.remove(value)
        else:
            current.append(value)
        self.save()
        return value in current


def settings_summary(data: dict) -> str:
    """Settings for a problem report: whether each folder is set and exists, never the path or the translator's name."""
    def state(value):
        if not value:
            return 'auto'
        return 'set (found)' if Path(value).expanduser().exists() else 'set (missing)'

    def folders(values):
        found = sum(1 for value in values if Path(value).expanduser().exists())
        return f'{len(values)} ({found} found)'

    lines = [f'{key}: {state(data.get(key, ""))}' for key in
             ('workshop_folder','mods_folder','mods_config_path','cache_directory','game_library')]
    lines += [f'{key}: {folders(data.get(key, []))}' for key in ('external_mod_folders','game_paths')]
    lines += [f'default_translator: {"set" if data.get("default_translator") else "empty"}',
              f'default_license: {"set" if data.get("default_license") else "empty"}',
              f'default_languages: {", ".join(data.get("default_languages", []))}',
              f'autosave_seconds: {data.get("autosave_seconds")}',
              f'inspect_metadata: {data.get("inspect_metadata")}',
              f'ui_language: {data.get("ui_language")}, theme: {data.get("theme_mode")}, font: {data.get("font_size")}']
    return '\n'.join(lines)
