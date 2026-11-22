"""Translations that prerequisite MODs already ship, as read-only reference for the editor's suggestions.

Only ``Languages/<language>/DefInjected`` and ``Keyed`` of MODs that were found as prerequisites are read, from
the folders the game would load for the project's version. Nothing is written or applied automatically.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

from .core import MAX_XML

_PLACEHOLDER = 'TODO'


@dataclass(frozen=True)
class PrerequisiteTranslation:
    mod: str
    key: str
    text: str
    # True when the key is another field of the same Def (same Def type and defName), not the row's own key.
    same_def: bool = False


@dataclass
class PrerequisiteTranslations:
    by_key: dict = field(default_factory=lambda: defaultdict(list))
    by_def: dict = field(default_factory=lambda: defaultdict(list))
    count: int = 0

    def add(self, mod: str, kind: str, group: str, key: str, text: str) -> None:
        text = text.strip()
        if not text or text == _PLACEHOLDER:
            return
        group = group if kind == 'DefInjected' else ''
        self.by_key[(kind, group, key)].append(PrerequisiteTranslation(mod, key, text))
        if kind == 'DefInjected':
            self.by_def[(group, key.split('.', 1)[0])].append(PrerequisiteTranslation(mod, key, text, True))
        self.count += 1

    def lookup(self, entry, limit: int = 4) -> list[PrerequisiteTranslation]:
        """The same key first, then other fields of the same Def (same Def type and defName)."""
        group = entry.group if entry.kind == 'DefInjected' else ''
        found = list(self.by_key.get((entry.kind, group, entry.key), ()))
        if entry.kind == 'DefInjected':
            found += [hit for hit in self.by_def.get((group, entry.key.split('.', 1)[0]), ()) if hit.key != entry.key]
        return found[:limit]


def _language_folders(folder: Path, language: str):
    languages = folder / 'Languages'
    if not languages.is_dir() or languages.is_symlink():
        return
    for item in sorted(languages.iterdir()):
        if item.is_dir() and not item.is_symlink() and item.name.partition(' (')[0].strip() == language:
            yield item


def _read_file(index: PrerequisiteTranslations, mod: str, kind: str, group: str, path: Path) -> None:
    from .core import safe_xml
    try:
        root = safe_xml(path)
    except (OSError, ValueError, ET.ParseError):
        return
    if root.tag != 'LanguageData':
        return
    for node in root:
        if not isinstance(node.tag, str):
            continue
        items = [child for child in node if child.tag == 'li']
        if items:
            for number, item in enumerate(items):
                index.add(mod, kind, group, f'{node.tag}.{number}', item.text or '')
        elif not len(node):
            index.add(mod, kind, group, node.tag, node.text or '')


def read_prerequisite_translations(found, language: str, game_version: str, active_mods=None, cancel=None) -> PrerequisiteTranslations:
    """Index the DefInjected and Keyed files of ``language`` in every found prerequisite (``scan_context.Prerequisite``)."""
    from .extraction import ScanCancelled, resolve_load_folders
    index = PrerequisiteTranslations()
    active = {*(active_mods or ()), *(item.package_id for item in found)}
    for item in found:
        if item.folder is None:
            continue
        # Folders in the engine's order: a later (more specific) load folder is read first and so is listed first.
        for load in resolve_load_folders(Path(item.folder), game_version, active):
            for folder in _language_folders(load, language):
                for kind in ('DefInjected', 'Keyed'):
                    base = folder / kind
                    if not base.is_dir() or base.is_symlink():
                        continue
                    for path in sorted(base.rglob('*.xml')):
                        if cancel is not None and cancel():
                            raise ScanCancelled()
                        if path.is_symlink() or path.stat().st_size > MAX_XML:
                            continue
                        relative = path.relative_to(base).parts
                        group = relative[0] if kind == 'DefInjected' and len(relative) > 1 else ''
                        if kind == 'DefInjected' and not group:
                            continue
                        _read_file(index, item.name, kind, group, path)
    return index
