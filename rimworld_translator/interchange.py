"""Sharing work: matching another translation MOD against the project, and a single-file project bundle."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
import io
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from .core import (Project, atomic_write, safe_xml, source_folder_problem, writable_destination)
from .version import __version__
from . import workflow

LICENSE_NOTE = ('他の人の翻訳MODの文章は、その作者のライセンスに従います。取り込む前に、再利用してよいか(ライセンスや許可)を確認してください。'
                '取り込んだ行は「要確認」になります。')


@dataclass
class ModMatch:
    """How another translation MOD lines up with the project (nothing is changed)."""
    about: dict[str, str] = field(default_factory=dict)
    new: list[str] = field(default_factory=list)                       # we have no translation, they do
    same: list[str] = field(default_factory=list)                      # identical translation
    different: list[tuple[str, str, str]] = field(default_factory=list)  # (id, ours, theirs)
    unknown: list[str] = field(default_factory=list)                   # their keys this project does not have
    missing: list[str] = field(default_factory=list)                   # our rows they do not translate
    total: int = 0
    license_note: str = LICENSE_NOTE

    @property
    def matched(self) -> int:
        return len(self.new) + len(self.same) + len(self.different)

    @property
    def coverage(self) -> float:
        return self.matched / self.total if self.total else 0.0


def _about(folder: Path) -> dict[str, str]:
    try:
        root = safe_xml(folder / 'About' / 'About.xml')
    except (OSError, ValueError, ET.ParseError):
        return {}
    return {tag: (root.findtext(tag) or '').strip() for tag in ('name', 'author', 'packageId', 'url')}


def match_translation_mod(project: Project, folder: Path | str, language: str | None = None) -> ModMatch:
    """Read another translation MOD (its ``Languages`` folder) and classify every row against the project."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f'翻訳MODのフォルダーがありません: {folder}')
    scratch = workflow.ImportPreview()
    incoming = workflow._read_xml(project, folder, language, scratch)
    if not incoming:
        raise ValueError('翻訳として読める XML が見つかりませんでした。Languages フォルダーのある翻訳MODを選んでください。'
                         + ''.join(' ' + warning for warning in scratch.warnings[:2]))
    entries = project.entry_index()
    match = ModMatch(about=_about(folder))
    seen = set()
    for row in incoming:
        target = language or row.language
        if row.id not in entries:
            if row.id not in match.unknown:
                match.unknown.append(row.id)
            continue
        if not row.text.strip() or (row.id, target) in seen:
            continue
        seen.add((row.id, target))
        ours = workflow._translation(project, entries[row.id], target)
        if not ours.strip():
            match.new.append(row.id)
        elif ours == row.text:
            match.same.append(row.id)
        else:
            match.different.append((row.id, ours, row.text))
    translated = {identity for identity, _ in seen}
    rows = [entry for entry in project.entries if not (entry.stale or entry.blocked or entry.excluded) and entry.english.strip()]
    match.total = len(rows)
    match.missing = [entry.id for entry in rows if entry.id not in translated]
    return match


def preview_import_mod(project: Project, folder: Path | str, language: str | None = None, overwrite: bool = False) -> workflow.ImportPreview:
    """``workflow.preview_import`` for a translation MOD, with every row marked for review.

    Another person's wording is a starting point, not a finished row, so apply it with ``workflow.apply_changes``
    and confirm each row. Existing translations are protected unless ``overwrite``.
    """
    preview = workflow.preview_import(project, Path(folder), language, overwrite)
    preview.changes = [workflow.TranslationChange(c.id, c.language, c.before, c.after, True) for c in preview.changes]
    preview.warnings.append(LICENSE_NOTE)
    return preview


# --- Project bundle: one file to hand a project to someone else -----------------------------------------------

BUNDLE_SCHEMA = 1
_MAX_BUNDLE_UNPACKED = 700 * 1024 * 1024
_MAX_OUTPUT_FILES = 2000


@dataclass(frozen=True)
class BundleInfo:
    name: str
    package_id: str
    original_package_id: str
    entries: int
    translated: int
    languages: tuple[str, ...]
    created: str
    has_output: bool
    app_version: str


def _scrub_paths(value, paths):
    """Replace this machine's absolute paths inside any string of ``value`` (diagnostics quote them) by a placeholder."""
    variants = sorted({variant for path in paths if path and str(path).strip()
                       for variant in (str(path), str(path).replace('\\', '/'), str(path).replace('/', '\\'))}, key=len, reverse=True)
    def walk(item):
        if isinstance(item, str):
            for variant in variants:
                item = item.replace(variant, '<local-path>')
            return item
        if isinstance(item, list):
            return [walk(x) for x in item]
        if isinstance(item, dict):
            return {key: walk(x) for key, x in item.items()}
        return item
    return walk(value)


def export_bundle(project: Project, path: Path | str, output_folder: Path | str | None = None) -> Path:
    """Write the project (translations, review state, glossary, notes, assignments, versions) as one zip.

    The source MOD's location on this machine is not included; the receiver chooses their own copy of the MOD.
    ``output_folder`` (a generated translation MOD) is added under ``mod/`` when given. The file is a plain zip
    with ``bundle.json`` and ``project.json``; use ``.rwtbundle`` as the extension.
    """
    path = Path(path).absolute()
    with tempfile.TemporaryDirectory(prefix='.bundle-') as scratch:
        temporary = Path(scratch) / 'project.json'
        project.save(temporary)
        data = json.loads(temporary.read_text(encoding='utf-8'))
    data['source'] = ''
    data['output_folder'] = ''
    data = _scrub_paths(data, [project.source, project.output_folder])
    project.stash_current_language()
    manifest = {'schema': BUNDLE_SCHEMA, 'app_version': __version__, 'name': project.name, 'package_id': project.package_id,
                'original_package_id': project.original_package_id, 'languages': list(project.languages),
                'entries': len(project.entries), 'translated': sum(1 for e in project.entries if e.japanese.strip()),
                'created': datetime.datetime.now().astimezone().isoformat(timespec='seconds'), 'has_output': False}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        if output_folder is not None:
            folder = Path(output_folder)
            files = [item for item in sorted(folder.rglob('*')) if item.is_file() and not item.is_symlink()
                     and not item.name.startswith('.rimworld-')]
            if len(files) > _MAX_OUTPUT_FILES:
                raise ValueError('出力フォルダーのファイルが多すぎます')
            manifest['has_output'] = bool(files)
            for item in files:
                archive.writestr('mod/' + item.relative_to(folder).as_posix(), item.read_bytes())
        archive.writestr('bundle.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        archive.writestr('project.json', json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    writable_destination(path.parent, Path(project.source))
    atomic_write(path, buffer.getvalue())
    return path


def _open(path: Path) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f'プロジェクトバンドルとして読めません: {path.name}') from exc
    names = set(archive.namelist())
    if not {'bundle.json', 'project.json'} <= names:
        archive.close()
        raise ValueError(f'プロジェクトバンドルではありません(bundle.json / project.json がありません): {path.name}')
    if sum(info.file_size for info in archive.infolist()) > _MAX_BUNDLE_UNPACKED:
        archive.close()
        raise ValueError('プロジェクトバンドルが大きすぎます')
    return archive


def _manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read('bundle.json').decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('バンドルの bundle.json を読めません') from exc
    if not isinstance(manifest, dict) or manifest.get('schema') != BUNDLE_SCHEMA:
        raise ValueError('このバージョンでは読めないバンドルです')
    return manifest


def inspect_bundle(path: Path | str) -> BundleInfo:
    """Summary of a bundle without unpacking anything."""
    with _open(Path(path)) as archive:
        manifest = _manifest(archive)
    return BundleInfo(str(manifest.get('name', '')), str(manifest.get('package_id', '')),
                      str(manifest.get('original_package_id', '')), int(manifest.get('entries', 0)),
                      int(manifest.get('translated', 0)), tuple(manifest.get('languages', ())),
                      str(manifest.get('created', '')), bool(manifest.get('has_output')), str(manifest.get('app_version', '')))


def _mod_content_allowed(relative: str) -> bool:
    """Only what an exported translation MOD contains (About/, Languages/, LoadFolders.xml) may come out of a bundle."""
    from .core import is_export_content_path
    try:
        return is_export_content_path(relative)
    except ValueError:
        return False


def import_bundle(path: Path | str, destination: Path | str, source: Path | str, overwrite: bool = False) -> Path:
    """Unpack a bundle into ``destination`` (a project folder) and point it at the receiver's own copy of the MOD.

    ``source`` must be a MOD folder whose packageId is the one the project was made for. Returns the project.json
    path. An existing project.json is kept unless ``overwrite``. Archive paths are validated; nothing is
    extracted outside ``destination``.
    """
    path, destination, source = Path(path), Path(destination).absolute(), Path(source)
    problem = source_folder_problem(source)
    if problem:
        raise ValueError(problem)
    with _open(path) as archive:
        _manifest(archive)
        try:
            data = json.loads(archive.read('project.json').decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError('バンドルの project.json を読めません') from exc
        wanted = data.get('original_package_id', '') if isinstance(data, dict) else ''
        found = (safe_xml(source / 'About' / 'About.xml').findtext('packageId') or '').strip()
        if wanted and found.casefold() != wanted.casefold():
            raise ValueError(f'このプロジェクトは {wanted} 用です。選んだ MOD は {found or "packageId なし"} です。')
        data['source'] = str(source.resolve())
        data['output_folder'] = ''  # the sender's folder means nothing here (and may be another OS's path style)
        outputs = []
        for info in archive.infolist():
            if info.filename in {'bundle.json', 'project.json'} or info.is_dir():
                continue
            relative = Path(info.filename)
            if (not info.filename.startswith('mod/') or relative.is_absolute() or '..' in relative.parts
                    or info.filename.endswith('/') or ((info.external_attr >> 16) & 0o170000) == 0o120000
                    or '\\' in info.filename or not _mod_content_allowed(info.filename[len('mod/'):])):
                raise ValueError(f'バンドルに不正なパスがあります: {info.filename}')
            outputs.append((relative, archive.read(info)))
        project = Project._from_data(data)
        target = destination / 'project.json'
        if target.exists() and not overwrite:
            raise ValueError(f'すでにプロジェクトがあります: {target}。上書きする場合は明示してください。')
        if not overwrite:
            clashes = [str(relative) for relative, _ in outputs if (destination / relative).exists()]
            if clashes:
                raise ValueError(f'すでにあるファイルを上書きしません: {", ".join(clashes[:5])}。上書きする場合は明示してください。')
        project.save(target)
        for relative, payload in outputs:
            atomic_write(destination / relative, payload)
    return target
