"""What an export would change in the output folder, computed without touching it."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .core import (Project, export_mod, export_shared, export_versions, export_versions_test)

_MARKER = '.rimworld-translator.json'


@dataclass
class FileChange:
    """One output file. For translation XML, the keys that were added, removed or given a different text."""
    path: str
    keys_added: list[str] = field(default_factory=list)
    keys_removed: list[str] = field(default_factory=list)
    keys_changed: list[str] = field(default_factory=list)


@dataclass
class ExportDiff:
    added: list[FileChange] = field(default_factory=list)
    removed: list[FileChange] = field(default_factory=list)
    changed: list[FileChange] = field(default_factory=list)
    unchanged: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def summary(self) -> str:
        return f'追加 {len(self.added)} ファイル / 削除 {len(self.removed)} ファイル / 変更 {len(self.changed)} ファイル / 変更なし {self.unchanged} ファイル'


def _keys(data: bytes) -> dict[str, str] | None:
    if not data.lstrip().startswith(b'<?xml') and not data.lstrip().startswith(b'<'):
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if root.tag != 'LanguageData':
        return None
    return {node.tag: ''.join(node.itertext()) for node in root if isinstance(node.tag, str)}


def _walk(folder: Path, names: list[str] | None = None) -> dict[str, bytes]:
    files = {}
    for path in sorted(folder.rglob('*')):
        if path.is_file() and not path.is_symlink() and path.name != _MARKER:
            relative = path.relative_to(folder).as_posix()
            if names is None or relative in names:
                files[relative] = path.read_bytes()
    return files


def export_diff(project: Project, target: Path, mode: str | None = None, versions: list[str] | None = None) -> ExportDiff:
    """Compare the output the next export would write with what is in ``target`` now.

    The export runs for real into a scratch folder, so its blocking rules apply: ``ExportBlocked`` or
    ``ValueError`` propagate exactly as they would from the export. Nothing in ``target`` is changed.
    ``mode``: 'single' (``export_mod``), 'test' (``export_mod`` test package), 'versions', 'shared',
    'versions_test'; by default 'shared' for a multi-version project and 'single' otherwise.
    Only files this editor owns (listed in the folder's marker) count as removed; a non-empty folder the
    editor does not own is refused, as the export itself would.
    """
    target = Path(target)
    mode = mode or ('shared' if project.version_profiles else 'single')
    owned: list[str] = []
    if target.exists() and any(target.iterdir()):
        marker = target / _MARKER
        if not marker.is_file() or marker.is_symlink():
            raise ValueError('Export directory is not owned by this editor; choose an empty folder')
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        if metadata.get('package_id') != project.package_id:
            raise ValueError('Export belongs to a different project')
        owned = [name for name in metadata.get('files', []) if isinstance(name, str)]
    scratch = Path(tempfile.mkdtemp(prefix='.rimworld-diff-'))
    try:
        staged = scratch / 'mod'
        if mode == 'single':
            warnings = export_mod(project, staged)
        elif mode == 'test':
            warnings = export_mod(project, staged, test_only=True)
        elif mode == 'versions':
            warnings = export_versions(project, staged, versions).warnings
        elif mode == 'shared':
            warnings = export_shared(project, staged, versions).warnings
        elif mode == 'versions_test':
            warnings = export_versions_test(project, staged)
        else:
            raise ValueError(f'Unknown export mode: {mode}')
        new = _walk(staged)
        old = _walk(target, owned) if owned else {}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    diff = ExportDiff(warnings=list(warnings))
    for path, data in new.items():
        if path not in old:
            added = _keys(data)
            diff.added.append(FileChange(path, keys_added=sorted(added) if added else []))
        elif old[path] == data:
            diff.unchanged += 1
        else:
            before, after = _keys(old[path]), _keys(data)
            change = FileChange(path)
            if before is not None and after is not None:
                change.keys_added = sorted(set(after) - set(before))
                change.keys_removed = sorted(set(before) - set(after))
                change.keys_changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
            diff.changed.append(change)
    for path in old:
        if path not in new:
            before = _keys(old[path])
            diff.removed.append(FileChange(path, keys_removed=sorted(before) if before else []))
    return diff
