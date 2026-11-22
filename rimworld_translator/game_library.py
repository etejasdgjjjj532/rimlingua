"""Read-only identification of RimWorld game folders and the user's game version library.

A library holds one lightweight copy per game version at ``<library>/<major.minor>/<any name>/``. Nothing here copies,
imports or executes anything: the game DLL is only searched for the UTF-16 strings the game itself contains.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Mapping
import xml.etree.ElementTree as ET

DLL = 'Assembly-CSharp.dll'
MAX_VERSION_FILE = 1024 * 1024
DLC_PREFIX = 'ludeon.rimworld.'
# The game's own file version, e.g. 1.6.9676.18xxx: major from 1, a minor, a build of four or five digits and an
# optional revision (so 127.0.0.1 or 2.0.0.0 never count).
DLL_VERSION = re.compile(rb'(?<![\d.]\x00)([1-9]\x00(?:\d\x00)*)\.\x00((?:\d\x00)+)\.\x00(?:\d\x00){4,5}'
                         rb'(?:\.\x00(?:\d\x00)+)?(?![\d.]\x00)')


@dataclass(frozen=True)
class GameIdentity:
    root: Path
    version: str
    build: str
    dll_versions: tuple[str, ...]
    dlcs: tuple[str, ...]
    excluded: tuple[Path, ...]
    problem: str


def child(folder: Path, name: str) -> Path | None:
    """The entry of ``folder`` named ``name`` in any letter case, keeping its spelling on disk."""
    exact = folder / name
    if exact.exists():
        return exact
    try:
        return next((entry for entry in folder.iterdir() if entry.name.casefold() == name.casefold()), None)
    except OSError:
        return None


def descend(folder: Path, *names: str) -> Path | None:
    for name in names:
        folder = child(folder, name) if folder is not None else None
    return folder


def game_dll(root: Path) -> Path | None:
    """The game's Assembly-CSharp.dll in the Windows, Linux or Mac layout, whichever OS this runs on."""
    root = Path(root)
    try:
        folders = sorted(entry for entry in root.iterdir() if entry.is_dir() and entry.name.casefold().endswith('_data'))
    except OSError:
        return None
    for data in [*folders, descend(root, 'RimWorldMac.app', 'Contents', 'Resources', 'Data')]:
        dll = descend(data, 'Managed', DLL) if data is not None else None
        if dll is not None and dll.is_file():
            return dll
    return None


def _version_file(root: Path) -> tuple[str, str]:
    """(major.minor, full number) from Version.txt, which may carry a BOM and CRLF; empty when unreadable."""
    path = child(root, 'Version.txt')
    try:
        if path is None or path.stat().st_size > MAX_VERSION_FILE:
            return '', ''
        match = re.search(r'\b(\d+\.\d+)(?:\.\d+)*\b', path.read_text(encoding='utf-8-sig', errors='replace'))
    except OSError:
        return '', ''
    return (match.group(1), match.group()) if match else ('', '')


def _package_id(folder: Path) -> str:
    about = descend(folder, 'About', 'About.xml')
    if about is None or not about.is_file():
        return ''
    try:
        from .core import safe_xml
        # Libraries often live behind a link (an external disk); read the file where it really is.
        return (safe_xml(about.resolve()).findtext('packageId') or '').strip().casefold()
    except (OSError, ValueError, ET.ParseError):
        return ''


# Identities by the state of the files they were read from; each scan asks several times per game.
_IDENTITIES: dict = {}


def _fingerprint(root: Path):
    parts = [str(root)]
    for path in (game_dll(root), child(root, 'Version.txt'), child(root, 'Data')):
        try:
            stat = path.stat() if path is not None else None
        except OSError:
            stat = None
        parts.append((str(path), stat.st_mtime_ns, stat.st_size) if stat else None)
    return tuple(parts)


def identify_game(root: Path) -> GameIdentity:
    """Version, build and the DLC folders this game's own DLL knows; a DLC folder left by another version is excluded."""
    root = Path(root)
    key = _fingerprint(root)
    if key not in _IDENTITIES:
        _IDENTITIES[key] = _identify(root)
    return _IDENTITIES[key]


def _identify(root: Path) -> GameIdentity:
    version, build = _version_file(root)
    dll = game_dll(root)
    try:
        content = dll.read_bytes() if dll is not None else b''
    except OSError:
        dll, content = None, b''
    dll_versions = tuple(sorted({m.group(1).decode('utf-16-le') + '.' + m.group(2).decode('utf-16-le')
                                 for m in DLL_VERSION.finditer(content)}))
    dlcs, excluded = [], []
    data = child(root, 'Data')
    try:
        folders = sorted(entry for entry in data.iterdir() if entry.is_dir()) if data is not None else []
    except OSError:
        folders = []
    for folder in folders:
        package = _package_id(folder)
        if not package.startswith(DLC_PREFIX):
            continue
        if package.encode('utf-16-le') in content:
            dlcs.append(package)
        else:
            excluded.append(folder)
    if not version:
        problem = f'Version.txt is missing or unreadable in {root}'
    elif dll is None:
        problem = f'{DLL} is missing or unreadable in {root}'
    elif dll_versions and version not in dll_versions:
        problem = f'Version.txt says {version} but {DLL} is {", ".join(dll_versions)}; the folder is broken or mixed'
    else:
        problem = ''
    return GameIdentity(root, version, build, dll_versions, tuple(sorted(dlcs)), tuple(excluded), problem)


def contradicts(identity: GameIdentity, version: str) -> bool:
    """True when the DLL names its versions and ``version`` is not among them."""
    return bool(identity.dll_versions) and version not in identity.dll_versions


def library_directory(platform: str | None = None, home: Path | None = None, environ: Mapping | None = None,
                      override: str = '') -> Path:
    """Where the user keeps game versions; kept apart from the cache because it cannot be rebuilt."""
    if override:
        return Path(override).expanduser()
    platform, home, environ = platform or sys.platform, Path(home or Path.home()), os.environ if environ is None else environ
    if platform == 'win32':
        return Path(environ.get('LOCALAPPDATA') or home / 'AppData/Local') / 'RimWorldTranslationEditor/games'
    if platform == 'darwin':
        return home / 'Library/Application Support/RimWorldTranslationEditor/games'
    return Path(environ.get('XDG_DATA_HOME') or home / '.local/share') / 'rimworld-translation-editor/games'


def library_game_roots(library: Path) -> list[Path]:
    """Game folders at ``<library>/<major.minor>/<name>/``, newest version first; anything else is ignored."""
    from .extraction import version_tuple
    found = []
    try:
        versions = [entry for entry in Path(library).iterdir() if entry.is_dir() and re.fullmatch(r'\d+\.\d+', entry.name)]
    except OSError:
        return []
    for folder in sorted(versions, key=lambda entry: version_tuple(entry.name), reverse=True):
        try:
            games = sorted(entry for entry in folder.iterdir() if entry.is_dir())
        except OSError:
            continue
        found.extend(game for game in games if descend(game, 'Data', 'Core') is not None)
    return found


def known_game_paths(settings_data: Mapping) -> list[str]:
    """Game folders the scanners consider: the user's explicit ones, then every library game, each once.

    Only scanners use this list; installing and live testing keep to explicit folders, since a library copy cannot run.
    """
    paths, seen = [], set()
    library = library_directory(override=settings_data.get('game_library', ''))
    for value in [*settings_data.get('game_paths', []), *map(str, library_game_roots(library))]:
        try:
            key = os.path.normcase(str(Path(value).expanduser().resolve()))
        except (OSError, RuntimeError):
            key = value
        if key not in seen:
            seen.add(key)
            paths.append(value)
    return paths
