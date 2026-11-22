"""Read-only game/version context for source extraction."""
from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .core import PACKAGE
from .installation import ModDependency, ModMetadata, dependencies_for, read_active_mods, read_mod_metadata
from .platforms import user_data_directory


def validate_context(game_version, active_mods=None):
    match = re.fullmatch(r'(\d+\.\d+)(?:\.\d+)*', game_version or '')
    if not match:
        raise ValueError('Use a game version such as 1.6.')
    if active_mods is not None:
        if isinstance(active_mods, str) or any(not isinstance(p, str) or not PACKAGE.fullmatch(p) for p in active_mods):
            raise ValueError('Active MODs must be package IDs from About.xml.')
        active_mods = list(dict.fromkeys(p.casefold() for p in active_mods))
    return {'game_version':match.group(1), 'active_mods':active_mods}


def default_context(source, installation=None, mods_config=None, *, strict_profile=False):
    version = installation.version if installation and installation.version else '1.6'
    context = validate_context(version,None)
    config = Path(mods_config) if mods_config is not None else user_data_directory()/'Config/ModsConfig.xml'
    warning = ''
    try:
        active = read_active_mods(config) if config.is_file() else None
        if active is not None:
            if installation and 'ludeon.rimworld' not in active:
                active.insert(0,'ludeon.rimworld')
            try:
                active.append(read_mod_metadata(source).package_id)
            except (OSError, ValueError, ET.ParseError):
                pass
        context = validate_context(version,active)
    except (OSError,ValueError,ET.ParseError) as exc:
        if strict_profile:
            raise
        warning = f'Could not read game MOD settings. Choose active MODs manually: {exc}'
    if warning:
        context['warning'] = warning
    return context


@dataclass(frozen=True)
class DependencyContext:
    """The MODs a scan reads as XML parents and type information, and what could not be resolved."""
    sources: tuple[Path, ...]
    # Package IDs of every selected MOD that was found, so MayRequire/IfModActive see them as loaded.
    active_ids: tuple[str, ...]
    missing: tuple[ModDependency, ...]
    load_after: tuple[str, ...]
    # Prerequisites whose supportedVersions does not list the scanned version.
    unsupported: tuple[str, ...]
    # MOD folders whose About.xml could not be read (long paths on Windows, permissions).
    unreadable: tuple[Path, ...]
    # Expansions this game's own Data folder holds and its DLL knows, whether or not anything requires them.
    installed_dlcs: tuple[str, ...] = ()
    # The scanned MOD's own package ID.
    own_id: str = ''

    @property
    def assumed_active(self) -> tuple[str, ...]:
        """What to treat as loaded when the player's active-MOD list is unknown.

        The source, Core, the installed expansions and the prerequisites found: the game cannot load the source
        without its prerequisites, and an expansion installed with the game is normally active. Any other MOD is
        assumed absent, so IfModNotActive folders for it load and MayRequire content for it stays out.
        """
        return tuple(p for p in dict.fromkeys((self.own_id, *self.active_ids, *self.installed_dlcs)) if p)


def _mod_folders(folder):
    if folder is None or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_dir() and not p.name.startswith('.') and (p / 'About/About.xml').is_file())


def _candidate_folders(game, others, extra_mod_paths):
    """MOD folders in the order the lookup prefers: this game's own Data, then Mods and Workshop, then extras."""
    from .game_library import child, identify_game
    if game is not None:
        identity = identify_game(game.root)
        # A folder the game's DLL does not know (a DLC left by another version) is not part of this game.
        # Without a readable DLL every DLC folder counts as excluded, the safe answer.
        excluded = {p.resolve() for p in identity.excluded}
        yield from (p for p in _mod_folders(child(game.root, 'Data')) if p.resolve() not in excluded)
    for installation in ([game] if game is not None else []) + [g for g in others if g is not game]:
        for folder in (installation.mods, installation.workshop):
            yield from _mod_folders(folder)
    yield from (Path(p) for p in extra_mod_paths)


# About.xml read results by (file, modification time, size): a scan of several versions reads each MOD once.
_METADATA: dict = {}


def _metadata(path):
    """A MOD's About.xml, read where it really is (Workshop items are sometimes links); the error when unreadable."""
    about = (Path(path) / 'About/About.xml').resolve()
    try:
        stat = about.stat()
    except OSError as exc:
        return exc
    key = (str(about), stat.st_mtime_ns, stat.st_size)
    if key not in _METADATA:
        try:
            _METADATA[key] = read_mod_metadata(path, about)
        except (OSError, ValueError, ET.ParseError) as exc:
            _METADATA[key] = exc
    return _METADATA[key]


def dependency_context(game, others, source, version, active_mods, extra_mod_paths=(), cancel=None) -> DependencyContext:
    """Active MODs plus the source's prerequisites, followed transitively, found among installed MOD folders.

    Prerequisites are used even when not active: the game cannot load the source without them. loadAfter MODs are
    only reported, because entries cannot yet say which type information they came from. Nothing is written.
    ``cancel`` is checked per MOD folder, since a Workshop library can hold thousands.
    """
    from .extraction import ScanCancelled
    source = Path(source).resolve()
    own = _metadata(source)
    if isinstance(own, Exception):
        # Old or bare sources without a usable About.xml still scan; they simply declare no prerequisites.
        own = ModMetadata(source, '', source.name, (), (), ())
    index, unreadable = {}, []
    for path in _candidate_folders(game, others, extra_mod_paths):
        if cancel is not None and cancel():
            raise ScanCancelled()
        if path.resolve() == source:
            continue
        meta = _metadata(path)
        if isinstance(meta, Exception):
            unreadable.append(path)
            continue
        if meta.package_id != own.package_id:
            index.setdefault(meta.package_id, (path, meta))
    # (dependency, required): only prerequisites are reported missing; an absent active MOD is the profile's business.
    wanted = [(ModDependency('ludeon.rimworld', 'Core'), True), *((ModDependency(p, p), False) for p in (active_mods or ())),
              *((d, True) for d in dependencies_for(own, version))]
    found, missing, seen = {}, {}, set()
    while wanted:
        dependency, required = wanted.pop(0)
        if dependency.package_id == own.package_id:
            continue
        hit = next((index[p] for p in (dependency.package_id, *dependency.alternatives) if p in index), None)
        if hit is None:
            if required and (game is not None or not dependency.package_id.startswith('ludeon.rimworld')):
                missing.setdefault(dependency.package_id, dependency)
            continue
        if dependency.package_id in seen:
            continue
        seen.add(dependency.package_id)
        path, meta = hit
        if meta.package_id not in found:
            found[meta.package_id] = (path, meta)
            wanted.extend((d, True) for d in dependencies_for(meta, version))
    unsupported = tuple(p for p, (_path, meta) in found.items() if not p.startswith('ludeon.')
                        and meta.supported_versions and version not in meta.supported_versions)
    load_after = tuple(p for p in own.load_after if p in index and p not in found)
    data = None
    if game is not None:
        from .game_library import child
        data = child(game.root, 'Data')
    installed_dlcs = tuple(sorted(p for p, (path, _meta) in index.items() if p.startswith('ludeon.rimworld.')
                                  and data is not None and Path(path).parent == data))
    return DependencyContext(tuple(path for path, _meta in found.values()), tuple(found), tuple(missing.values()),
                             load_after, unsupported, tuple(unreadable), installed_dlcs, own.package_id)


def report_dependency_gaps(scan, context: DependencyContext, schema=None) -> None:
    """Tell the user which prerequisites were not read and how many unverified fields that leaves.

    A class name does not say which missing MOD defines it, so the count covers all missing MODs together.
    """
    def add(code, message, suggestion, **details):
        scan.warnings.append(message)
        scan.warning_count += 1
        scan.diagnostics.append({'code': code, 'message': message, 'source_file': '', 'entry_id': '',
                                 'suggestion': suggestion, **details})

    if context.missing:
        names = ', '.join(f'{d.display_name} ({d.package_id})' for d in context.missing)
        if schema is None:
            # Without field metadata nothing was checked, so no count would be honest.
            count, effect = None, 'fields were not checked against C# types in this scan'
        else:
            count = sum(1 for d in scan.diagnostics if d.get('code') == 'unknown-field'
                        and schema.find_type(d.get('owner_type') or '') is None)
            dropped = any('additional distinct warnings omitted' in w for w in scan.warnings)
            effect = f'{"at least " if dropped else ""}{count} fields cannot be checked'
        add('missing-dependency', f'Prerequisite MODs not installed: {names}; {effect}.',
            'Install or subscribe to the listed MODs, then scan again.',
            package_ids=[d.package_id for d in context.missing], count=count)
    for package in context.unsupported:
        add('dependency-version-unverified',
            f'Prerequisite {package} does not declare this game version; fields it defines are unverified.',
            'Check the prerequisite supports this version before exporting it.', package_ids=[package])
    if context.load_after:
        add('dependency-load-after-unused',
            f'Optional MODs read only for load order, not for field types: {", ".join(context.load_after)}.',
            'Fields that only these MODs define stay unverified.', package_ids=list(context.load_after))
    if context.unreadable:
        add('dependency-unreadable',
            f'MOD folders could not be read: {", ".join(str(p) for p in context.unreadable)}.',
            'Move the MOD to a shorter path or check its permissions, then scan again.',
            paths=[str(p) for p in context.unreadable])


def context_sources(installation, source, active_mods):
    """Supply available active XML parents and the source's prerequisites; the selected source is scanned once."""
    version = '.'.join((installation.version or '').split('.')[:2])
    return list(dependency_context(installation, (), source, version, active_mods).sources)


_WORKSHOP_ID = re.compile(r'(?:[?&]id=|/CommunityFilePage/|/filedetails/)(\d{6,16})')


@dataclass(frozen=True)
class Prerequisite:
    """One prerequisite MOD, missing or found, described for a person who has to subscribe to it."""
    package_id: str
    name: str
    workshop_id: str = ''
    url: str = ''
    folder: Path | None = None
    # Language folders the MOD itself ships (a translation of it may already exist there).
    translations: tuple[str, ...] = ()
    unsupported: bool = False
    official: bool = False


@dataclass(frozen=True)
class PrerequisiteReport:
    missing: tuple[Prerequisite, ...]
    found: tuple[Prerequisite, ...]
    # Fields the scan could not check against C# types because of missing MODs; None when no scan recorded it.
    # The C# type owner is unknown, so the count cannot be split per MOD.
    unverified_fields: int | None = None


def workshop_link(item: Prerequisite) -> str:
    """The Steam Workshop address when the id is known, else the URL About.xml gave, else ''."""
    if item.workshop_id:
        return f'https://steamcommunity.com/sharedfiles/filedetails/?id={item.workshop_id}'
    return item.url if item.url.startswith(('http://', 'https://')) else ''


def _shipped_languages(folder: Path) -> tuple[str, ...]:
    names = set()
    for pattern in ('Languages/*', '*/Languages/*'):
        names.update(p.name for p in folder.glob(pattern) if p.is_dir())
    return tuple(sorted(names))


def prerequisite_report(context: DependencyContext, diagnostics=()) -> PrerequisiteReport:
    """Describe a ``dependency_context`` result: what to subscribe to, what was found and where.

    ``diagnostics`` is the project's saved list; its missing-dependency entry supplies the unchecked-field count.
    """
    from .core import source_workshop_id
    missing = []
    for dependency in context.missing:
        match = _WORKSHOP_ID.search(dependency.url or '')
        missing.append(Prerequisite(dependency.package_id, dependency.display_name,
                                    match.group(1) if match else '', dependency.url or ''))
    found = []
    for package, path in zip(context.active_ids, context.sources):
        meta = _metadata(path)
        name = package if isinstance(meta, Exception) else meta.name
        found.append(Prerequisite(package, name, source_workshop_id(Path(path)), '', Path(path),
                                  _shipped_languages(Path(path)), package in context.unsupported,
                                  package.startswith('ludeon.')))
    counts = [d.get('count') for d in diagnostics if isinstance(d, dict) and d.get('code') == 'missing-dependency']
    count = next((c for c in counts if type(c) is int), None)
    return PrerequisiteReport(tuple(missing), tuple(found), count)
