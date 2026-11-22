"""Version-aware XML localization engine with cancellable incremental parsing."""
from __future__ import annotations
import copy
from collections import Counter, OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from lxml import etree as LX
from .schema import TranslationSchema, normalized_handle
from .field_semantics import nonlocalizable_reason
from .text_semantics import DISPLAY_NAME, INTERNAL, ValueVerdict, classify_value, field_leaf

_TREE_CACHE = OrderedDict()
_TREE_CACHE_BYTES = 0
_TREE_CACHE_LIMIT = 32 * 1024 * 1024


class ScanCancelled(Exception):
    """The user cancelled before any project/export mutation."""


def version_tuple(value: str):
    return tuple(int(v) for v in value.lstrip('v').split('.') if v.isdigit())


def condition_matches(attributes: dict, active_mods: set[str] | None, warn, context: str, assumed=False) -> bool:
    """Whether a MayRequire/IfModActive-style condition holds; ``assumed`` marks a guessed active-MOD set."""
    for name, value in attributes.items():
        key = name.casefold()
        if key not in {'ifmodactive', 'ifmodactiveall', 'ifmodactiveany', 'ifmodnotactive', 'ifmodnotactiveall', 'mayrequire', 'mayrequireanyof'}:
            if key.startswith('ifmod'):
                warn('unknown-condition', f'Unknown load condition {name}; excluded: {context}', context)
                return False
            continue
        if active_mods is None:
            warn('conditional-context', f'Choose active MODs to resolve {name}={value}: {context}', context)
            return False
        if assumed:
            warn('conditional-assumed', f'Active MOD list unknown; {name}="{value}" was judged with the installed '
                 'expansions and found prerequisites as active', context)
        packages = [p.strip().casefold() for p in re.split('[,;]', value) if p.strip()]
        present = [p in active_mods for p in packages]
        matched = any(present) if key in {'ifmodactiveany', 'mayrequireanyof', 'ifmodactive', 'ifmodnotactive'} else all(present)
        if key.startswith('ifmodnot'):
            matched = not matched
        if not matched:
            return False
    return True


def resolve_load_folders(source: Path, game_version='1.6', active_mods=None, warn=lambda *args: None, assumed=False) -> list[Path]:
    from .core import safe_xml
    active = None if active_mods is None else {p.casefold() for p in active_mods}
    file = source / 'LoadFolders.xml'
    if file.exists():
        try:
            root = safe_xml(file)
            branches = {e.tag.lstrip('v'):e for e in root}
            chosen = branches.get(game_version)
            if chosen is None:
                older = [v for v in branches if re.fullmatch(r'\d+(?:\.\d+)+',v) and version_tuple(v) <= version_tuple(game_version)]
                chosen = branches[max(older, key=version_tuple)] if older else branches.get('default')
            if chosen is not None:
                selected = []
                for item in chosen:
                    if item.tag != 'li' or not condition_matches(item.attrib, active, warn, 'LoadFolders.xml', assumed):
                        continue
                    relative = (item.text or '').strip().replace('\\', '/').strip('/')
                    rel = Path(relative)
                    if rel.is_absolute() or '..' in rel.parts:
                        warn('load-path', f'Invalid load folder: {relative}', 'LoadFolders.xml')
                        continue
                    folder = source / rel
                    if folder.is_dir() and not folder.is_symlink():
                        selected.append(folder)
                    else:
                        warn('missing-folder', f'Load folder missing: {relative}', 'LoadFolders.xml')
                return list(dict.fromkeys(reversed(selected)))
            warn('version-fallback', f'LoadFolders has no branch for {game_version}; using engine default folders', 'LoadFolders.xml')
        except (OSError, ValueError, ET.ParseError) as exc:
            warn('loadfolders', f'LoadFolders.xml: {exc}', 'LoadFolders.xml')
    versions = [p for p in source.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)+',p.name)]
    eligible = [p for p in versions if version_tuple(p.name) <= version_tuple(game_version)]
    best = max(eligible, key=lambda p:version_tuple(p.name)) if eligible else (min(versions,key=lambda p:version_tuple(p.name)) if versions else None)
    return [p for p in [best, source/'Common', source] if p is not None and p.is_dir()]


def content_files(folders: list[Path], category: str, suffix='.xml') -> list[Path]:
    """Engine precedence: the first file with a relative content path wins."""
    selected = {}
    for folder in folders:
        base = folder / category
        if not base.is_dir() or base.is_symlink():
            continue
        for directory, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory)/d).is_symlink())
            for name in sorted(names):
                p = Path(directory)/name
                if p.suffix.casefold() == suffix:
                    selected.setdefault(p.relative_to(base).as_posix(), p)
    return list(selected.values())


def _copy_with_text_sources(node, text_sources):
    """Copy XML while preserving the author of each element's text."""
    result = copy.deepcopy(node)
    if text_sources is not None:
        for original, copied in zip(node.iter(), result.iter()):
            if original in text_sources:
                text_sources[copied] = text_sources[original]
    return result


def merge_inherited(parent, child, text_sources=None):
    """Merge named XML children and append li lists; Inherit=False replaces."""
    if child.get('Inherit', child.get('inherit', '')).casefold() == 'false':
        return _copy_with_text_sources(child, text_sources)
    result = _copy_with_text_sources(parent, text_sources)
    result.tag = child.tag
    result.attrib.clear()
    result.attrib.update(child.attrib)
    if child.text and child.text.strip():
        result.text = child.text
        if text_sources is not None:
            text_sources.pop(result, None)
            if child in text_sources:
                text_sources[result] = text_sources[child]
    for node in child:
        old = next((e for e in result if e.tag == node.tag), None) if node.tag != 'li' else None
        if old is None:
            result.append(_copy_with_text_sources(node, text_sources))
        elif len(old) and (len(node) or not (node.text or '').strip()):
            index = result.index(old)
            result.remove(old)
            result.insert(index, merge_inherited(old, node, text_sources))
        else:
            index = result.index(old)
            result.remove(old)
            result.insert(index, _copy_with_text_sources(node, text_sources))
    return result



# Why an entry is a translation target. Codes, so tools and the GUI can count and filter them.
REASONS = {
    'keyed': 'English Keyed catalog (the game UI string route)',
    'strings-resource': 'English nested Strings resource',
    'english-catalog': "The MOD's English DefInjected catalog names this key",
    'must-translate': 'CLR MustTranslate attribute on the field',
    'may-translate': 'CLR MayTranslate attribute on the field',
    'string-field': 'Unattributed CLR string field',
    'shape:ambiguous': 'Single plain word; could be a label or a tag',
    'field-name': 'Field named like display text in a class that could not be read',
    'own-translation': "The MOD's own non-English translation has this key",
    'official-pattern': 'Official RimWorld translations translate this Def type and field',
}


def entry_reasons(entry, own_translations=frozenset()) -> list[str]:
    """Reason codes of one extracted entry, from how it was found."""
    if entry.kind == 'Keyed':
        reasons = ['keyed']
    elif entry.kind == 'Strings':
        reasons = ['strings-resource']
    elif entry.confidence == 'catalog':
        reasons = ['english-catalog']
    elif entry.confidence == 'heuristic':
        reasons = ['field-name']
    else:
        attributes = next((item.split(': ', 1)[1] for item in entry.evidence
                           if item.startswith('CLR ') and ': ' in item and not item.startswith('CLR List')), '')
        reasons = ['must-translate' if 'MustTranslateAttribute' in attributes
                   else 'may-translate' if 'MayTranslateAttribute' in attributes else 'string-field']
        if any(item.startswith('Unattributed string field;') for item in entry.evidence):
            reasons.append('shape:ambiguous')
    if entry.confidence != 'catalog' and 'Existing English catalog match' in entry.evidence:
        reasons.append('english-catalog')
    if (entry.kind, entry.key.casefold()) in own_translations:
        reasons.append('own-translation')
    return reasons


def own_translation_keys(folders) -> set[tuple[str, str]]:
    """(kind, key casefolded) the MOD's own non-English DefInjected/Keyed files translate. Read only."""
    from .core import MAX_XML
    parser = LX.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
    keys = set()
    for folder in folders:
        languages = folder / 'Languages'
        if not languages.is_dir() or languages.is_symlink():
            continue
        for language in sorted(languages.iterdir()):
            if not language.is_dir() or language.is_symlink() or language.name.casefold().startswith('english'):
                continue
            for kind in ('DefInjected', 'Keyed'):
                for file in content_files([language], kind):
                    try:
                        if file.stat().st_size > MAX_XML:
                            continue
                        raw = file.read_bytes()
                        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                            continue
                        root = LX.fromstring(raw, parser)
                    except (OSError, LX.XMLSyntaxError):
                        continue
                    keys.update((kind, child.tag.casefold()) for child in root
                                if isinstance(child.tag, str) and (child.text or '').strip())
    return keys


def mark_official(entries, patterns) -> None:
    """Add 'official-pattern' to DefInjected entries whose (Def type, first field, leaf field) the official
    translations translate (see official_translations.official_field_patterns)."""
    for entry in entries:
        if entry.kind != 'DefInjected':
            continue
        fields = [part for part in entry.key.split('.')[1:] if re.fullmatch(r'[a-z][A-Za-z0-9_]*', part)]
        if fields and (entry.group.rsplit('.', 1)[-1], fields[0], fields[-1]) in patterns:
            if 'official-pattern' not in entry.reasons:
                entry.reasons.append('official-pattern')


_CODE_FINGERPRINT = []


def _code_fingerprint() -> str:
    """The extraction rules themselves: a result cached by older code is never reused."""
    if not _CODE_FINGERPRINT:
        package = Path(__file__).parent
        digest = hashlib.sha256()
        for name in ('extraction.py', 'text_semantics.py', 'field_semantics.py', 'il_candidates.py', 'schema.py',
                     'string_resources.py', 'core.py', 'assets/field_contracts.json'):
            try:
                digest.update(name.encode() + (package / name).read_bytes())
            except OSError:
                digest.update(name.encode())
        _CODE_FINGERPRINT.append(digest.hexdigest())
    return _CODE_FINGERPRINT[0]


def _tree_state(root: Path) -> list:
    """(relative path, size, modification time) of every file under a MOD folder; links are not followed."""
    state = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for name in sorted(names):
            path = Path(directory) / name
            try:
                stat = path.lstat()
            except OSError:
                continue
            state.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return state


def _schema_fingerprint(schema) -> str:
    if schema is None:
        return 'none'
    cached = schema.__dict__.get('_fingerprint')
    if cached is None:
        digest = hashlib.sha256(schema.builtin_version.encode())
        for name in sorted(schema.types):
            typ = schema.types[name]
            digest.update(f'{name}<{typ.base}'.encode())
            for field, spec in sorted(typ.fields.items()):
                digest.update(f'{field}:{spec.type_name}:{spec.attributes}:{spec.is_list}:{spec.handle_priority}:'
                              f'{spec.aliases}'.encode())
        # The names themselves, not just their counts: a changed name at an equal count must not reuse a stale scan.
        for label, names in (('defs', schema.known_defs), ('keyed', schema.known_keyed)):
            digest.update(f'|{label}:{len(names)}|'.encode())
            digest.update('\0'.join(sorted(map(str, names))).encode('utf-8', 'surrogatepass'))
        digest.update(str(sorted(schema.warnings)).encode())
        cached = schema.__dict__['_fingerprint'] = digest.hexdigest()
    return cached


def _cached_assembly_result(cache_path, file: Path, kind: str, compute):
    """compute(file), stored per assembly content and kind in the scan cache; returns (value, reused)."""
    if not cache_path:
        return compute(file), False
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    database = sqlite3.connect(cache_path)
    try:
        database.execute('CREATE TABLE IF NOT EXISTS assembly_evidence_v1 (sha TEXT, kind TEXT, code TEXT, value TEXT, '
                         'PRIMARY KEY (sha, kind))')
        row = database.execute('SELECT code, value FROM assembly_evidence_v1 WHERE sha=? AND kind=?',
                               (digest, kind)).fetchone()
        if row and row[0] == _code_fingerprint():
            return json.loads(row[1]), True
        value = compute(file)
        database.execute('INSERT OR REPLACE INTO assembly_evidence_v1 VALUES (?,?,?,?)',
                         (digest, kind, _code_fingerprint(), json.dumps(value)))
        database.commit()
        return value, False
    finally:
        database.close()


def _scan_from_json(text: str):
    from .core import Entry, Scan
    data = json.loads(text)
    data['entries'] = [Entry(**entry) for entry in data['entries']]
    return Scan(**data)


def _text_variant(tag: str) -> bool:
    """A grammatical variant of a field name RimWorld uses for shown text: titleShort, titleFemale, labelPlural."""
    from .core import FIELDS
    match = re.fullmatch(r'([a-z][A-Za-z]*?)((?:Short|Plural|Female|Male|Singular)+)', tag)
    return bool(match and match.group(1) in FIELDS)


def base_type_by_name(schema, type_name: str) -> str:
    """Guess the base Def type of an unreadable subclass; see TranslationSchema.guess_base."""
    return schema.guess_base(type_name)


def scan(source: Path, game_version='1.6', active_mods=None, cache_path=None, progress=None, cancel=None, schema: TranslationSchema | None=None, context_sources=(), diagnostic_limit=1500, assumed_active=None):
    """Extract the translation keys of one MOD for one game version.

    ``active_mods`` None means the player's active-MOD list is unknown. ``assumed_active`` then names the MODs to
    treat as loaded for MayRequire/IfModActive conditions (see scan_context.DependencyContext.assumed_active); the
    result still records the profile as unknown.
    """
    global _TREE_CACHE_BYTES
    from .core import Entry, Scan, KEY, PACKAGE, FIELDS, MAX_XML, safe_xml
    start = time.perf_counter()
    if not isinstance(game_version,str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)*',game_version):
        raise ValueError('Use a game version such as 1.6.')
    game_version = '.'.join(game_version.split('.')[:2])
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Source must be a directory')
    active = None if active_mods is None else {p.casefold() for p in active_mods}
    result = Scan(name=source.name)
    distinct, omitted = set(), 0

    def warn(code, text, relative='', entry_id='', suggestion='', **details):
        nonlocal omitted
        result.warning_count += 1
        if text in distinct:
            return
        distinct.add(text)
        if diagnostic_limit is None or len(result.warnings) < diagnostic_limit:
            result.warnings.append(text)
            result.diagnostics.append({'code':code, 'message':text, 'source_file':relative, 'entry_id':entry_id, 'suggestion':suggestion or 'Check source context; exclude uncertain candidates or add a verified manual key.', **details})
        else:
            omitted += 1

    def check_cancel():
        if cancel is not None and cancel():
            raise ScanCancelled('Scan cancelled; existing project is unchanged')

    check_cancel()
    about = source/'About/About.xml'
    if about.exists():
        try:
            node = safe_xml(about)
            result.name = node.findtext('name') or source.name
            package = (node.findtext('packageId') or '').strip()
            result.package_id = package if PACKAGE.fullmatch(package) else ''
            result.versions = [e.text.strip() for e in node.findall('supportedVersions/li') if e.text and re.fullmatch(r'\d+\.\d+', e.text.strip())]
        except (OSError, ValueError, ET.ParseError) as exc:
            warn('about', f'About/About.xml: {exc}', 'About/About.xml')
    profile = active
    assumed = active is None and assumed_active is not None
    if assumed:
        active = {p.casefold() for p in assumed_active} | ({result.package_id.casefold()} if result.package_id else set())
    folders = resolve_load_folders(source, game_version, active, warn, assumed)
    result.selected_folders = [str(p.relative_to(source)) for p in folders]
    defs = content_files(folders, 'Defs')
    keyed = content_files(folders, 'Languages/English/Keyed')
    patches = content_files(folders, 'Patches')
    catalog_files = content_files(folders, 'Languages/English/DefInjected')
    string_files = content_files(folders, 'Languages/English/Strings', '.txt')
    contexts = []
    context_roots = [Path(value).resolve() for value in context_sources]
    active_names, named_packages, context_packages = set(), set(), set()
    for context in [source, *context_roots]:
        metadata = context/'About/About.xml'
        if metadata.exists():
            try:
                node = safe_xml(metadata)
                package = (node.findtext('packageId') or '').strip().casefold()
                name = node.findtext('name')
                if PACKAGE.fullmatch(package):
                    context_packages.add(package)
                if name and PACKAGE.fullmatch(package):
                    named_packages.add(package)
                    if context == source or (active is not None and package in active):
                        active_names.add(name)
            except (OSError, ValueError, ET.ParseError) as exc:
                warn('about', f'{metadata}: {exc}', str(metadata))
    context_keyed = []
    for context in context_roots:
        context_folders = resolve_load_folders(context, game_version, active, warn, assumed)
        contexts.extend(content_files(context_folders, 'Defs'))
        # Dependency Keyed keys are only used to recognise values that name them, never as entries.
        context_keyed.extend(content_files(context_folders, 'Languages/English/Keyed'))
    files = [*contexts, *context_keyed, *defs, *keyed, *patches, *catalog_files]
    reuse_slot = fingerprint = None
    if cache_path:
        # The whole result is reused only when no input changed: the rules, every file of the source and of each
        # context MOD, the type information and the load conditions. Patches and inheritance cross files, so a
        # partial change re-extracts everything, still reusing each unchanged file's parsed XML and DLL evidence.
        reuse_slot = hashlib.sha256(json.dumps([str(source), game_version]).encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps([
            _code_fingerprint(), sorted(profile) if profile is not None else None, sorted(active) if assumed else None,
            diagnostic_limit, _schema_fingerprint(schema), _tree_state(source),
            [(str(root), _tree_state(root)) for root in context_roots]]).encode()).hexdigest()
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(cache_path)
        try:
            database.execute('CREATE TABLE IF NOT EXISTS scan_result_v1 (slot TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)')
            row = database.execute('SELECT fingerprint, result FROM scan_result_v1 WHERE slot=?', (reuse_slot,)).fetchone()
        finally:
            database.close()
        if row and row[0] == fingerprint:
            try:
                previous = _scan_from_json(row[1])
            except (ValueError, TypeError, KeyError):
                previous = None
            if previous is not None:
                # No file was read again: every one counts as served from a cache layer.
                previous.stats.update(parsed_files=0, cached_files=len(files),
                                      memory_hits=sum(str(file) in _TREE_CACHE for file in files))
                previous.stats['reuse'] = {'result_reused': True, 'files_reused': len(files), 'files_parsed': 0,
                                           'assemblies_reused': previous.stats.get('dlls', 0), 'assemblies_read': 0}
                previous.stats['seconds'] = round(time.perf_counter() - start, 4)
                message = 'Nothing changed since the last scan; its result was reused.'
                previous.warnings.append(message)
                previous.warning_count += 1
                previous.diagnostics.append({'code': 'scan-reused', 'message': message, 'source_file': '',
                                             'entry_id': '', 'suggestion': 'Change a file or the scan context to re-extract.'})
                if progress:
                    progress(len(files), len(files), len(previous.entries), 'Complete')
                return previous
    assemblies_seen = {'reused': 0, 'read': 0}
    stats = result.stats = {'files':len(files), 'parsed_files':0, 'cached_files':0, 'memory_hits':0, 'active_version':game_version, 'active_mods':sorted(profile) if profile is not None else None, 'assumed_active':sorted(active) if assumed else None, 'patches_applied':0, 'inherited_defs':0, 'catalog_candidates':0, 'catalog_matches':0, 'dlls':0}
    database = None
    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(cache_path)
        # v2 omitted XML tails. Keep its rows intact, but rebuild from source
        # into v3 so old lossy payloads cannot change XPath patch conditions.
        database.execute('CREATE TABLE IF NOT EXISTS xml_index_v3 (path TEXT PRIMARY KEY, sha TEXT, tree BLOB)')
    parser = LX.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
    trees = {}
    def tree_data(node):
        # PI tags are lxml callables, not JSON strings. Preserve them as inert
        # nodes so XPath string(), node() and sibling positions stay intact.
        # Existing v3 element payloads are unchanged; they could not store PIs.
        if isinstance(node, LX._ProcessingInstruction):
            return [None, node.target, node.text, node.tail, []]
        return [node.tag, dict(node.attrib), node.text, node.tail, [tree_data(child) for child in node]]
    def cached_tree(data):
        node = LX.ProcessingInstruction(data[1], data[2]) if data[0] is None else LX.Element(data[0], data[1])
        node.text = data[2]
        node.tail = data[3]
        for child in data[4]:
            node.append(cached_tree(child))
        return node
    try:
        for count, file in enumerate(files, 1):
            check_cancel()
            relative = str(file.relative_to(source)) if source in file.parents else str(file)
            try:
                if file.stat().st_size > MAX_XML or any(p.is_symlink() for p in (file,*file.parents)):
                    raise ValueError('Symbolic link or oversized XML')
                raw = file.read_bytes()
                normalized = raw.replace(b'\x00',b'').upper()
                if b'<!DOCTYPE' in normalized or b'<!ENTITY' in normalized:
                    raise ValueError('DTD / ENTITY declarations are prohibited')
                digest = hashlib.sha256(raw).hexdigest()
                memory = _TREE_CACHE.get(str(file)) if cache_path else None
                cached = database.execute('SELECT tree FROM xml_index_v3 WHERE path=? AND sha=?', (str(file),digest)).fetchone() if database and (not memory or memory[0]!=digest) else None
                if memory and memory[0]==digest:
                    trees[file] = memory[1]
                    _TREE_CACHE.move_to_end(str(file))
                    stats['cached_files'] += 1
                    stats['memory_hits'] += 1
                elif cached:
                    trees[file] = cached_tree(json.loads(cached[0]))
                    stats['cached_files'] += 1
                else:
                    tree = LX.fromstring(raw, parser)
                    trees[file] = tree
                    stats['parsed_files'] += 1
                    if database:
                        database.execute('INSERT OR REPLACE INTO xml_index_v3 VALUES (?,?,?)', (str(file),digest,json.dumps(tree_data(tree),separators=(',',':'))))
                if cache_path and (not memory or memory[0]!=digest):
                    old_memory = _TREE_CACHE.pop(str(file),None)
                    if old_memory:
                        _TREE_CACHE_BYTES -= old_memory[2]
                    _TREE_CACHE[str(file)] = (digest,trees[file],len(raw))
                    _TREE_CACHE_BYTES += len(raw)
                    while _TREE_CACHE_BYTES > _TREE_CACHE_LIMIT and _TREE_CACHE:
                        _,old_memory = _TREE_CACHE.popitem(last=False)
                        _TREE_CACHE_BYTES -= old_memory[2]
            except (OSError, ValueError, LX.XMLSyntaxError) as exc:
                warn('xml', f'{relative}: {exc}', relative)
            if progress:
                progress(count, len(files), len(result.entries), relative)
        if database:
            database.commit()
    finally:
        if database:
            database.close()

    document = LX.Element('Defs')
    provenance, original_owned, text_sources = {}, set(), {}
    for file in [*contexts, *defs]:
        root = trees.get(file)
        if root is None:
            continue
        if root.tag != 'Defs':
            # The game reads the children of whatever the root element is called, so these Defs do load.
            warn('xml-root', f'Root element is {root.tag}, not Defs; reading its children as Defs like the game: {file}', str(file))
        for node in root:
            if not isinstance(node.tag, str):
                continue
            if not condition_matches(node.attrib, active, warn, str(file), assumed):
                continue
            value = copy.deepcopy(node)
            document.append(value)
            provenance[value] = str(file.relative_to(source)) if source in file.parents else str(file)
            if file in defs:
                original_owned.add(value)
                text_sources.update((element, provenance[value]) for element in value.iter())
    patch_evidence = []

    def patch(operation, file):
        check_cancel()
        if not condition_matches(operation.attrib, active, warn, file, assumed):
            # An unloaded operation is absent from the sequence, not a failure.
            return True
        success = (operation.findtext('success') or 'Normal').strip()
        if success not in {'Normal', 'Invert', 'Always', 'Never'}:
            warn('patch-success', f'{file}: unknown success mode {success}; effects require manual review', file)
            return None
        outcome = patch_worker(operation, file)
        # Unknown effects must remain unknown, even under Always or Invert.
        if outcome is None:
            return None
        if success == 'Always':
            return True
        if success == 'Never':
            return False
        return not outcome if success == 'Invert' else outcome

    def patch_worker(operation, file):
        kind = operation.get('Class', '').rsplit('.',1)[-1]
        if kind == 'PatchOperationSequence':
            children = operation.find('operations')
            if children is None:
                warn('patch-value', f'{file}: sequence has no operations', file)
                return None
            for op in children:
                if not isinstance(op.tag, str):
                    continue
                outcome = patch(op, file)
                if outcome is not True:
                    return outcome
            return True
        xpath = operation.findtext('xpath')
        selected = []
        if xpath:
            try:
                expression = '/' + xpath if xpath.startswith('Defs') else xpath
                selected = document.xpath(expression)
            except LX.XPathError as exc:
                warn('patch-xpath', f'{file}: invalid XPath: {exc}', file)
                return None
        if kind == 'PatchOperationConditional':
            branch = operation.find('match' if selected else 'nomatch')
            return patch(branch,file) if branch is not None else True
        if kind == 'PatchOperationFindMod':
            names = [n.text for n in operation.findall('mods/li') if n.text]
            matched = any(name in active_names for name in names)
            if active is None or (not matched and active - named_packages):
                warn('patch-context', f'{file}: FindMod needs active MOD display-name metadata: {", ".join(names)}', file)
                return None
            branch = operation.find('match' if matched else 'nomatch')
            return patch(branch,file) if branch is not None else True
        supported = {'PatchOperationAdd', 'PatchOperationReplace', 'PatchOperationRemove', 'PatchOperationInsert', 'PatchOperationTest', 'PatchOperationAttributeAdd', 'PatchOperationAttributeSet', 'PatchOperationAttributeRemove'}
        if kind not in supported:
            warn('patch-unsupported', f'{file}: unsupported {kind or "PatchOperation"}; effects require manual review', file)
            return None
        if not selected:
            if kind != 'PatchOperationTest':
                warn('patch-context', f'{file}: target absent from scan context: {xpath}; add dependency MODs for an accurate patch result', file)
            return False
        value = operation.find('value')
        attributes_changed = False
        for node in selected:
            if not isinstance(node,LX._Element):
                warn('patch-xpath', f'{file}: non-element XPath result; manual review', file)
                return None
            if kind == 'PatchOperationRemove':
                parent = node.getparent()
                if parent is not None:
                    # DOM RemoveChild removes the selected node, while its
                    # following text is an independent sibling. lxml calls
                    # that text tail, so retain it on the preceding position.
                    if node.tail:
                        previous = node.getprevious()
                        if previous is None:
                            parent.text = (parent.text or '') + node.tail
                        else:
                            previous.tail = (previous.tail or '') + node.tail
                    parent.remove(node)
            elif kind in {'PatchOperationAdd', 'PatchOperationReplace', 'PatchOperationInsert'}:
                if value is None:
                    warn('patch-value', f'{file}: {kind} has no value',file)
                    return None
                if kind == 'PatchOperationAdd':
                    order = (operation.findtext('order') or 'Append').strip()
                    if order not in {'Append', 'Prepend'}:
                        warn('patch-order', f'{file}: unknown Add order {order}; effects require manual review', file)
                        return None
                    # lxml stores XML text children in .text and .tail rather
                    # than in the element iterator used below.
                    old_text = node.text
                    if order == 'Prepend':
                        node.text = value.text
                    elif value.text:
                        if len(node):
                            node[-1].tail = (node[-1].tail or '') + value.text
                        else:
                            node.text = (node.text or '') + value.text
                    # Direct text may follow an inert PI rather than precede
                    # the first child; that tail also belongs to the target.
                    if (value.text or '').strip() or any((child.tail or '').strip() for child in value):
                        text_sources[node] = file
                    for index,child in enumerate(value):
                        added = copy.deepcopy(child)
                        text_sources.update((element, file) for element in added.iter())
                        if order == 'Prepend':
                            node.insert(index,added)
                        else:
                            node.append(added)
                        if node is document:
                            original_owned.add(added)
                            provenance[added] = file
                    if order == 'Prepend' and old_text:
                        if len(value):
                            last = node[len(value)-1]
                            last.tail = (last.tail or '') + old_text
                        else:
                            node.text = (node.text or '') + old_text
                else:
                    parent = node.getparent()
                    if parent is None:
                        warn('patch-root', f'{file}: cannot replace/remove root',file)
                        return None
                    order = (operation.findtext('order') or 'Prepend').strip()
                    if kind == 'PatchOperationInsert' and order not in {'Append', 'Prepend'}:
                        warn('patch-order', f'{file}: unknown Insert order {order}; effects require manual review', file)
                        return None
                    # System.Xml treats direct text and element/PI children as
                    # separate siblings. Detach lxml tails before arranging the
                    # imported nodes, otherwise the text moves with its anchor.
                    children = []
                    if value.text is not None:
                        children.append(value.text)
                    for child in value:
                        added = copy.deepcopy(child)
                        added.tail = None
                        children.append(added)
                        if child.tail is not None:
                            children.append(child.tail)
                    if kind == 'PatchOperationInsert':
                        # The game's Insert worker repeatedly uses the same
                        # anchor for Append, and iterates backwards for Prepend.
                        children.reverse()
                    after = kind == 'PatchOperationInsert' and order == 'Append'
                    index = parent.index(node) + int(after)
                    following_text = node.tail if after or kind == 'PatchOperationReplace' else None
                    if after or kind == 'PatchOperationReplace':
                        node.tail = None
                    for child in children:
                        if isinstance(child, str):
                            if index:
                                previous = parent[index - 1]
                                previous.tail = (previous.tail or '') + child
                            else:
                                parent.text = (parent.text or '') + child
                            if child.strip():
                                text_sources[parent] = file
                        else:
                            text_sources.update((element, file) for element in child.iter())
                            parent.insert(index, child)
                            if parent is document:
                                original_owned.add(child)
                                provenance[child] = file
                            index += 1
                    if kind == 'PatchOperationReplace':
                        parent.remove(node)
                    if following_text:
                        if index:
                            previous = parent[index - 1]
                            previous.tail = (previous.tail or '') + following_text
                        else:
                            parent.text = (parent.text or '') + following_text
            elif kind.startswith('PatchOperationAttribute'):
                attribute = operation.findtext('attribute')
                if not attribute:
                    warn('patch-value', f'{file}: {kind} has no attribute', file)
                    return None
                present = attribute in node.attrib
                if kind.endswith('Remove'):
                    if present:
                        del node.attrib[attribute]
                        attributes_changed = True
                elif kind.endswith('Set') or not present:
                    node.set(attribute, operation.findtext('value') or '')
                    attributes_changed = True
        if kind.startswith('PatchOperationAttribute') and not attributes_changed:
            return False
        stats['patches_applied'] += 1
        patch_evidence.append(file)
        return True

    for file in patches:
        root = trees.get(file)
        if root is not None:
            for operation in root:
                if not isinstance(operation.tag, str):
                    continue
                patch(operation, str(file.relative_to(source)))
    parents = {}
    for node in document:
        if node.get('Name'):
            parents.setdefault(node.get('Name'), []).append(node)
    resolved, unresolved = {}, set()

    def inherit(node, trail=()):
        check_cancel()
        if node in resolved:
            return resolved[node]
        parent_name = node.get('ParentName')
        if parent_name:
            candidates = parents.get(parent_name, [])
            if len(candidates) != 1 or parent_name in trail:
                unresolved.add(node)
                warn('inheritance', f'Unresolved inheritance {parent_name}: {provenance.get(node, "context")}',provenance.get(node,''))
                merged = _copy_with_text_sources(node, text_sources)
            else:
                parent = inherit(candidates[0], (*trail,parent_name))
                merged = merge_inherited(parent,node,text_sources)
                if candidates[0] in unresolved:
                    unresolved.add(node)
                stats['inherited_defs'] += 1
        else:
            merged = _copy_with_text_sources(node, text_sources)
        resolved[node] = merged
        return merged

    seen = {}
    forbidden_paths = {}
    relevant = {}
    # Names that exist in the scanned content; a value equal to one is a reference, not text.
    known_defs = {(node.findtext('defName') or '').strip() for node in document if isinstance(node.tag, str)} - {''}
    known_keyed = {child.tag for file in [*keyed, *context_keyed] for child in (trees.get(file) if trees.get(file) is not None else ())
                   if isinstance(child.tag, str)}
    if schema is not None:
        # Without the game's data folders as context, its Def and Keyed names come with the shipped table.
        known_defs |= schema.known_defs
        known_keyed |= schema.known_keyed

    def has_target_text(node, trail=()):
        # Avoid resolving/copying every dependency Def when only a few fields
        # were patched. Named-parent contributions still reach their children.
        if node in relevant:
            return relevant[node]
        if any(element in text_sources for element in node.iter()):
            relevant[node] = True
            return True
        parent_name = node.get('ParentName')
        candidates = parents.get(parent_name, [])
        if len(candidates) == 1 and parent_name not in trail:
            value = has_target_text(candidates[0], (*trail, parent_name))
        else:
            value = False
        relevant[node] = value
        return value

    def could_be_text(text, tag):
        """Whether an unknown field's value is worth a person's review as possible wording.

        Numbers, flags and values equal to a Def name or Keyed key fill the list of unextracted items without
        ever being translatable; the diagnostic limit is better spent on the rest. Identifier-looking tokens
        that match nothing known stay listed: only a person can tell what they are.
        """
        value = text.strip()
        if re.fullmatch(r'[-+\d.,~%()\s]+|true|false', value, re.IGNORECASE):
            return False
        return classify_value(value, tag, defs=known_defs, keyed=known_keyed).kind not in {'reference', 'data'}

    own_translations = own_translation_keys(folders)
    game_names = bool(schema is not None and schema.known_defs) or 'ludeon.rimworld' in context_packages
    # String fields the MOD's assemblies, taken together, read only to compare: IL evidence that a one-word value
    # is a matching token. Uses are combined over ALL assemblies (a field declared in one may be shown by another);
    # an unreadable assembly voids the evidence. Read as metadata only; nothing is executed.
    compared_fields = set()
    if schema is not None:
        from . import il_candidates
        evidences, readable = [], True
        for file in content_files(folders, 'Assemblies', '.dll'):
            check_cancel()
            try:
                evidence, reused = _cached_assembly_result(
                    cache_path, file, 'field-uses', lambda path: il_candidates.assembly_field_evidence(path, check_cancel))
            except (OSError, ValueError, sqlite3.Error):
                readable = False
                continue
            evidences.append(evidence)
            assemblies_seen['reused' if reused else 'read'] += 1
        if readable:
            compared_fields = il_candidates.compared_only_from_evidence(evidences)
    # The game copies `untranslatedX` from `X` after loading; that is only known for a game of the scanned version.
    handle_copy = schema is not None and (not schema.builtin_version
                                          or schema.builtin_version.split('.')[:2] == game_version.split('.')[:2])
    # (group, handle-form path) -> the index-form path older scans wrote for the same list item.
    legacy_prefixes = {}

    def legacy_key(group, key):
        parts = key.split('.')
        for end in range(len(parts), 0, -1):
            legacy = legacy_prefixes.get((group, '.'.join(parts[:end])))
            if legacy is not None:
                return '.'.join([legacy, *parts[end:]])
        return key

    def add(kind, group, key, text, file, review=False, confidence='heuristic', evidence=(), *, owner_type='', attributes=(),
            list_item=False):
        if not text or not text.strip():
            return
        if not KEY.fullmatch(key) or not KEY.fullmatch(group):
            warn('invalid-key', f'Invalid key skipped: {file}: {key}', file)
            return
        identity = f'{kind}:{group}:{key}'
        reason = nonlocalizable_reason(kind, group, key, owner_type=owner_type, attributes=attributes)
        if kind == 'DefInjected' and not reason:
            reason = next((why for path, why in forbidden_paths.get(group, {}).items()
                           if key == path or key.startswith(path + '.')), '')
        if reason:
            if kind == 'DefInjected' and owner_type:
                forbidden_paths.setdefault(group, {})[key] = reason
            warn('non-localizable-field', f'Internal field excluded: {identity}: {reason}', file, identity,
                 'Keep this internal value unchanged; CLR string type does not establish localization safety.')
            return
        declared = {attribute.rsplit('.', 1)[-1] for attribute in attributes}
        if kind == 'DefInjected' and confidence != 'catalog' and 'MustTranslateAttribute' not in declared:
            # Only MustTranslate states that a field is wording. MayTranslate merely permits translation (grammar
            # symbols, name-file paths), and other fields say nothing: judge the value itself.
            may = 'MayTranslateAttribute' in declared
            field = field_leaf(key)
            verdict = classify_value(text, field, defs=known_defs, keyed=known_keyed)
            if (kind, key.casefold()) in own_translations and verdict.kind == 'ambiguous':
                # The MOD's own translators translate this key: the word is shown, whatever the code looks like.
                pass
            elif (verdict.kind not in INTERNAL and not may and owner_type and not re.search(r'\s', text.strip())
                    and f'{owner_type}.{field}' in compared_fields):
                verdict = ValueVerdict('identifier', 'one word in a field its own assembly only compares or null-checks')
            elif (verdict.kind == 'ambiguous' and not may and list_item and not DISPLAY_NAME.search(field)
                  and game_names):
                # Only with the game's name list at hand (shipped table or the game's Core read as context):
                # without it a game Def name and a label look alike, so the word stays a candidate for review.
                verdict = ValueVerdict('identifier', 'one word in a plain string list; such lists hold matching tokens')
            if verdict.kind in INTERNAL:
                warn('internal-value', f'Likely internal value, not extracted: {identity} = {text.strip()[:60]!r} ({verdict.reason})',
                     file, identity, 'String field whose value looks like an asset path, tag, key, Def name or layout data. '
                     'Add a manual key only after confirming the game displays it.',
                     safety='likely-internal', value_kind=verdict.kind)
                return
            if verdict.kind == 'ambiguous' and not may:
                # Plain words are ordinary labels far more often than tags, so keep them
                # as normal entries and only record why the evidence is weaker.
                evidence = [*evidence, f'Unattributed string field; {verdict.reason}']
        if identity in seen:
            first = seen[identity]
            if not first.blocked and first.english.strip() == text.strip():
                # The game keeps the first Def under this name (DefDatabase renames a later duplicate) and the
                # first Keyed value; with equal English either way, one entry translates both.
                warn('duplicate-identical', f'Duplicate active key with the same English kept once: {identity} ({file})',
                     file, identity, 'Both definitions have the same English; the first entry translates the key.')
                return
            seen[identity].blocked = True
            warn('duplicate', f'Duplicate active key blocked: {identity} ({file})',file,identity,'Check duplicate definitions in active folders; choose the correct version before rescanning.')
            return
        entry = Entry(identity,kind,group,key,text,file,review=review,confidence=confidence,evidence=list(evidence),is_new=True)
        legacy = legacy_key(group, key) if kind == 'DefInjected' else key
        if legacy != key:
            entry.legacy_keys = [f'{kind}:{group}:{legacy}']
        seen[identity] = entry
        result.entries.append(entry)

    for number,original in enumerate(document):
        check_cancel()
        if original.get('Abstract','').casefold()=='true':
            continue
        # ObjectFromXml checks the original Def before resolving inheritance or
        # invoking a custom loader. Keep null named parents as XML templates.
        if original.get('IsNull', '').casefold() == 'true':
            continue
        if original not in original_owned and not has_target_text(original):
            continue
        definition = inherit(original)
        owned_definition = original in original_owned
        if not owned_definition and not any(element in text_sources for element in definition.iter()):
            continue
        name = definition.findtext('defName')
        relative = provenance.get(original,'(patch context)')
        if not name or not KEY.fullmatch(name.strip()):
            warn('unnamed', f'Unnamed/abstract definition skipped: {relative}', relative)
            continue
        name = name.strip()
        group = definition.tag
        base_evidence = [f'Active folders: {", ".join(result.selected_folders)}; RimWorld {game_version}']
        if original.get('ParentName'):
            base_evidence.append('XML parent: ' + original.get('ParentName'))
        if patch_evidence:
            base_evidence.append('Patch context: ' + ', '.join(patch_evidence[:4]))

        def walk(node, prefix, typ, allowed=True, indexed=False):
            fields = schema.fields_for(typ) if schema else {}
            known_type = schema.find_type(typ) if schema else None
            # A readable class whose base class is not: inherited fields are unknown, not absent.
            partial_type = known_type is not None and (not schema.chain_complete(typ) or (not prefix and root_unresolved))
            for child in node:
                check_cancel()
                if not isinstance(child.tag, str):
                    continue
                if child.get('IsNull', '').casefold() == 'true':
                    continue
                field_spec = fields.get(child.tag)
                attributes = child.attrib
                if (field_spec and field_spec.translatable and not field_spec.is_list
                        and not any(isinstance(c.tag, str) for c in child)):
                    # Plain strings are parsed directly: MayRequire only gates
                    # Def references and list items in DirectXmlToObject.
                    attributes = {key: value for key, value in attributes.items()
                                  if key.casefold() not in {'mayrequire', 'mayrequireanyof'}}
                if not condition_matches(attributes,active,warn,relative,assumed):
                    continue
                if child.tag in {'defName','class','Class','texPath','graphicClass','sound','soundCast','thingClass'}:
                    continue
                path = prefix + '.' + child.tag if prefix else child.tag
                eligible = allowed and not (field_spec and field_spec.forbidden)
                if not eligible:
                    if field_spec and field_spec.forbidden:
                        forbidden_paths.setdefault(group, {})[f'{name}.{path}'] = (
                            'CLR attribute excludes localization: ' + ', '.join(field_spec.attributes))
                    continue
                target_type = child.get('Class') or (field_spec.type_name if field_spec else '')
                if field_spec and schema.is_def(field_spec.type_name):
                    continue
                elements = [c for c in child if isinstance(c.tag, str)]
                if elements:
                    if all(c.tag=='li' for c in elements):
                        # DirectXmlToObject excludes unavailable list items before
                        # adding objects; indexes and duplicate handles must use
                        # that same loaded list rather than the original XML.
                        items = [item for item in elements if condition_matches(item.attrib,active,warn,relative,assumed)]
                        handles, copied = [], []
                        for item in items:
                            copied.append(False)
                            if item.get('IsNull', '').casefold() == 'true':
                                handles.append('')
                                continue
                            item_type = item.get('Class') or target_type
                            item_fields = schema.fields_for(item_type) if schema else {}
                            handle = ''
                            for tag, spec in sorted(item_fields.items(),key=lambda kv:kv[1].handle_priority,reverse=True):
                                if 'TranslationHandleAttribute' in spec.attributes:
                                    handle_node = item.find(tag)
                                    raw = (item.findtext(tag) if handle_node is not None
                                           and handle_node.get('IsNull', '').casefold() != 'true' else None)
                                    item_spec = schema.find_type(item_type)
                                    body_part = bool(item_spec and item_spec.name == 'Verse.BodyPartRecord')
                                    source_tag = tag[len('untranslated'):]
                                    source_tag = source_tag[:1].lower() + source_tag[1:]
                                    if (raw is None and tag.startswith('untranslated') and source_tag in item_fields
                                            and (handle_copy or body_part)):
                                        # PostLoad copies the XML label into `untranslatedX`
                                        # before canonical handles are generated.
                                        source_node = item.find(source_tag)
                                        raw = (item.findtext(source_tag) if source_node is not None
                                               and source_node.get('IsNull', '').casefold() != 'true' else None)
                                        # Entries of body parts were already keyed by handle; only the
                                        # newly recognised items had an index key before.
                                        copied[-1] = bool(raw) and not body_part
                                    if raw is None and tag.casefold() == 'compclass':
                                        # Constructor defaults cannot be recovered from metadata alone.
                                        continue
                                    if raw:
                                        handle = normalized_handle(raw)
                                        break
                            handles.append(handle)
                        counts,occurrences = Counter(handles),Counter()
                        for index,item in enumerate(items):
                            # Null list values still occupy their loaded index.
                            if item.get('IsNull', '').casefold() == 'true':
                                continue
                            handle = handles[index]
                            if handle and counts[handle]>1:
                                suffix = occurrences[handle]
                                occurrences[handle] += 1
                                handle += '-' + str(suffix)
                            segment = handle or str(index)
                            if copied[index] and handle:
                                legacy_prefixes[(group, f'{name}.{path}.{segment}')] = legacy_key(
                                    group, f'{name}.{path}') + '.' + str(index)
                            item_text = ''.join(item.itertext())
                            if any(isinstance(c.tag, str) for c in item):
                                walk(item, path+'.'+segment, item.get('Class') or target_type,eligible,indexed or not handle)
                            elif field_spec and field_spec.translatable and field_spec.is_list:
                                if owned_definition or item in text_sources:
                                    owner = schema.field_owner(typ, child.tag)
                                    add('DefInjected',group,f'{name}.{path}.{segment}',item_text,relative if owned_definition else text_sources[item],original in unresolved or not handle,'schema',[*base_evidence,'CLR List<string>; index '+str(index), f'CLR {owner}.{child.tag}: {", ".join(field_spec.attributes) or "string field"}'], owner_type=owner, attributes=field_spec.attributes, list_item=True)
                            elif (field_spec is None and (known_type is None or partial_type) and len(item_text.split()) >= 2
                                  and DISPLAY_NAME.search(child.tag) is not None and (owned_definition or item in text_sources)
                                  and child.tag not in {'rulesStrings','labels','messages'}):
                                # A list of phrases in a display-named field of an unreadable class: unverified wording.
                                add('DefInjected',group,f'{name}.{path}.{segment}',item_text,relative if owned_definition else text_sources[item],True,'heuristic',[*base_evidence,'Field-name heuristic; validate in game; index '+str(index)])
                            elif child.tag in {'rulesStrings','labels','messages'} and item_text:
                                if owned_definition or item in text_sources:
                                    add('DefInjected',group,f'{name}.{path}.{segment}',item_text,relative if owned_definition else text_sources[item],True,'heuristic',[*base_evidence,'Unverified textual list; index '+str(index)])
                            elif (field_spec is None and item_text.strip() and item in text_sources
                                  and classify_value(item_text, child.tag).kind != 'data'):
                                origin = text_sources[item]
                                warn('unknown-field',f'Field absent from CLR schema: {origin}: {name}.{path}.{segment}',origin,
                                     suggestion='Unverified XML value; inspect the source and CLR owner before treating it as translatable. Not a translation entry.',
                                     owner_type=typ, field_path=f'{name}.{path}.{segment}', source_text=item_text[:4096],
                                     source_text_length=len(item_text), source_text_truncated=len(item_text) > 4096,
                                     safety='unverified')
                            else:
                                warn('list-skipped', f'List skipped: {relative}: {name}.{path}',relative)
                    else:
                        walk(child,path,target_type,eligible,indexed)
                else:
                    text = ''.join(child.itertext())
                    schema_string = bool(field_spec and field_spec.translatable and not field_spec.is_list)
                    # Inside a nested object whose class we cannot read (comps, modExtensions), player-facing text is still
                    # named the way RimWorld names it. Top-level fields of an unknown Def stay diagnostics only.
                    # The Def's own unreadable class (often from a missing prerequisite) counts as such an object too:
                    # helpText, endMessage, shortLabel with several words are wording, though unverified.
                    fallback = (known_type is None or (partial_type and field_spec is None)) and (
                        child.tag in FIELDS or (partial_type and field_spec is None and _text_variant(child.tag)) or (
                        (bool(prefix) or partial_type) and field_spec is None
                        and DISPLAY_NAME.search(child.tag) is not None and len(text.split()) >= 2))
                    if (schema_string or fallback) and text.strip() and not re.fullmatch(r'[-+\d.\s]+',text):
                        confidence = 'schema' if schema_string else 'heuristic'
                        owner = schema.field_owner(typ, child.tag) if schema_string else ''
                        evidence = [*base_evidence, f'CLR {owner}.{child.tag}: {", ".join(field_spec.attributes) or "string field"}' if schema_string else 'Field-name heuristic; validate in game']
                        # A parent the scan cannot see (often in a missing prerequisite) leaves inherited fields
                        # unknown, but a top-level MustTranslate field written in this Def is its own name or
                        # description under the same key either way: no review for that alone.
                        own_text = not prefix and (
                            (schema_string and 'MustTranslateAttribute' in field_spec.attributes)
                            or (field_spec is None and child.tag in {'label', 'description'}))
                        unverified_name = fallback and not prefix and child.tag not in FIELDS
                        if owned_definition or child in text_sources:
                            add('DefInjected',group,f'{name}.{path}',text,relative if owned_definition else text_sources[child],(original in unresolved and not own_text) or indexed or unverified_name,confidence,evidence, owner_type=owner, attributes=field_spec.attributes if field_spec else ())
                    elif field_spec is None and text.strip() and child in text_sources and could_be_text(text, child.tag):
                        # Review only target-owned text, including patches and XML
                        # inheritance. Dependency-only text has no target source.
                        origin = text_sources.get(child, relative)
                        warn('unknown-field',f'Field absent from CLR schema: {origin}: {name}.{path}',origin,
                             suggestion='Unverified XML value; inspect the source and CLR owner before treating it as translatable. Not a translation entry.',
                             owner_type=typ, field_path=f'{name}.{path}', source_text=text[:4096],
                             source_text_length=len(text), source_text_truncated=len(text) > 4096,
                             safety='unverified')
        root_type = definition.get('Class') or definition.tag
        # The Def's own class is unreadable and stands in as its base: fields it declares itself are unknown, not absent.
        root_unresolved = False
        if schema and schema.find_type(root_type) is None:
            # The subclass lives in an assembly we cannot read; it still has every field of the Def type it extends.
            base = (definition.tag if definition.get('Class') and schema.find_type(definition.tag)
                    else base_type_by_name(schema, root_type))
            if base:
                warn('unresolved-class', f'Class {root_type} not found; reading {name} as {base}', relative,
                     suggestion='Fields declared by the custom class itself cannot be checked until its assembly is available.')
                root_type = base
                root_unresolved = True
        walk(definition,'',root_type)
        if progress and number%100==0:
            progress(len(files),len(files),len(result.entries),'Extracting: '+relative)
    for file in keyed:
        root = trees.get(file)
        if root is None:
            continue
        relative = str(file.relative_to(source))
        if root.tag != 'LanguageData':
            warn('keyed-root', f'{relative}: Expected LanguageData',relative)
            continue
        for child in root:
            if not isinstance(child.tag, str):
                continue
            if any(isinstance(node.tag, str) for node in child):
                warn('nested-keyed',f'Nested Keyed entry skipped: {relative}: {child.tag}',relative)
            else:
                add('Keyed','Keyed',child.tag,''.join(child.itertext()),relative,confidence='catalog',evidence=['Source English Keyed catalog'])
    by_legacy_key = {legacy: entry for entry in seen.values() for legacy in entry.legacy_keys}
    # List items keyed by index because their handle (often a constructor-set compClass) is not in the
    # XML: (group, key with one index segment as '*') -> entries. The catalog may name the real handle.
    by_index_pattern, by_item = {}, {}
    for entry in seen.values():
        if entry.kind != 'DefInjected' or entry.confidence == 'catalog':
            continue
        parts = entry.key.split('.')
        for position in range(1, len(parts) - 1):
            if parts[position].isdigit():
                pattern = '.'.join([*parts[:position], '*', *parts[position + 1:]])
                by_index_pattern.setdefault((entry.group, pattern), []).append((entry, position))
                by_item.setdefault((entry.group, '.'.join(parts[:position + 1])), []).append(entry)

    def rename_item(group, prefix, handle_prefix):
        """Move every entry of one list item from its index path to the handle path the catalog names.

        All or nothing: if any new key is taken or invalid, the item keeps its index keys."""
        moves = []
        for entry in by_item.get((group, prefix), ()):
            if not entry.key.startswith(prefix + '.') or seen.get(entry.id) is not entry:
                continue
            key = handle_prefix + entry.key[len(prefix):]
            identity = f'DefInjected:{group}:{key}'
            if identity in seen or not KEY.fullmatch(key):
                return False
            moves.append((entry, key, identity))
        for entry, key, identity in moves:
            del seen[entry.id]
            if entry.id not in entry.legacy_keys:
                entry.legacy_keys = [*entry.legacy_keys, entry.id]
            by_legacy_key[entry.id] = entry
            entry.id, entry.key = identity, key
            seen[identity] = entry
        return bool(moves)

    def catalog_handle_match(group, key, text):
        parts = key.split('.')
        for position in range(1, len(parts) - 1):
            if parts[position].isdigit():
                continue
            pattern = '.'.join([*parts[:position], '*', *parts[position + 1:]])
            candidates = [(entry, at) for entry, at in by_index_pattern.get((group, pattern), ())
                          if entry.id in seen and entry.key.split('.')[at].isdigit()
                          and entry.english.strip() == text.strip()]
            if len(candidates) == 1:
                entry, at = candidates[0]
                if rename_item(group, '.'.join(entry.key.split('.')[:at + 1]), '.'.join(parts[:position + 1])):
                    return entry
        return None

    # The game resolves a DefInjected folder name as a type name, so `DiseaseDef/` names `Mod.DiseaseDef` too.
    by_short_type = {}
    for entry in seen.values():
        if entry.kind == 'DefInjected':
            by_short_type.setdefault((entry.group.rsplit('.', 1)[-1], entry.key), []).append(entry)
    for file in catalog_files:
        root = trees.get(file)
        if root is None or root.tag != 'LanguageData':
            continue
        catalog_path = next(file.relative_to(folder/'Languages/English/DefInjected')
                            for folder in folders if file.is_relative_to(folder/'Languages/English/DefInjected'))
        group = catalog_path.parts[0]
        if len(catalog_path.parts) == 1:
            warn('legacy-catalog', f'Legacy catalog lacks Def type folder: {file.name}; type inferred from filename',str(file.relative_to(source)))
            group = file.stem
        for child in root:
            if not isinstance(child.tag, str):
                continue
            key = f'DefInjected:{group}:{child.tag}'
            stats['catalog_candidates'] += 1
            # A catalog written before handle keys names a handle-keyed item by its index.
            match = seen.get(key) or by_legacy_key.get(key)
            if match is None:
                same_type = [entry for entry in by_short_type.get((group.rsplit('.', 1)[-1], child.tag), ())
                             if seen.get(entry.id) is entry]
                match = same_type[0] if len(same_type) == 1 else None
            if match is None and child.text and not len(child):
                match = catalog_handle_match(group, child.tag, child.text)
            if match is not None:
                stats['catalog_matches'] += 1
                match.evidence.append('Existing English catalog match')
            elif child.text and not len(child):
                add('DefInjected',group,child.tag,child.text,str(file.relative_to(source)),True,'catalog',['English DefInjected catalog; source field not resolved'])
    from .string_resources import decode_strings, parse_strings, validate_string_entry
    for file in string_files:
        check_cancel()
        relative = file.relative_to(source).as_posix()
        resource_path = next(file.relative_to(folder / 'Languages/English/Strings').as_posix()
                             for folder in folders
                             if file.is_relative_to(folder / 'Languages/English/Strings'))
        if not validate_string_entry(resource_path, 'line_0'):
            warn('strings-unsupported', f'Strings file is outside the supported nested TXT format: {relative}', relative)
            continue
        try:
            if file.stat().st_size > MAX_XML or any(p.is_symlink() for p in (file, *file.parents)):
                raise ValueError('Symbolic link or oversized Strings resource')
            text = decode_strings(file.read_bytes())
            for index, value in enumerate(parse_strings(text)):
                key = f'line_{index}'
                identity = f'Strings:{resource_path}:{key}'
                result.entries.append(Entry(identity, 'Strings', resource_path, key, value, relative,
                                            confidence='catalog', is_new=True,
                                            evidence=['English nested Strings resource; Verse.LoadedLanguage.LoadFromFile_Strings',
                                                      'Verse.GenText.LinesFromString; logical index ' + str(index)]))
        except (OSError, UnicodeError, ValueError) as exc:
            warn('strings-read', f'{relative}: {exc}', relative)
    # WordInfo is grammar metadata, not a Strings list or an XML translation key.
    # Enumerate selected target files only; do not read or infer their contents.
    for file in content_files(folders, 'Languages/English/WordInfo', '.txt'):
        check_cancel()
        relative = file.relative_to(source).as_posix()
        resource = next(file.relative_to(folder / 'Languages/English/WordInfo')
                        for folder in folders
                        if file.is_relative_to(folder / 'Languages/English/WordInfo'))
        if file.is_symlink() or any(p.is_symlink() for p in file.parents):
            warn('wordinfo-unsupported', f'Symbolic WordInfo resource excluded: {relative}', relative,
                 suggestion='Inspect a regular source file; do not generate an XML key for WordInfo.')
        elif resource.as_posix() in {'Gender/Male.txt', 'Gender/Female.txt', 'Gender/Neuter.txt'}:
            warn('wordinfo-gender-unsupported', f'WordInfo gender metadata uses raw physical lines, not translated Strings indexes: {relative}',
                 relative, suggestion='Verify target-language term ownership and gender metadata before dedicated WordInfo output; do not generate an XML key.')
        elif len(resource.parts) == 1 and resource.suffix == '.txt':
            warn('wordinfo-lut-unverified', f'Potential WordInfo lookup table; registration and semicolon field meanings are unverified: {relative}',
                 relative, suggestion='Verify the RegisterLut name, lookup-key ownership, and field semantics before dedicated WordInfo output; do not translate every field or generate XML keys.')
        else:
            warn('wordinfo-unsupported', f'Unverified WordInfo resource layout excluded: {relative}', relative,
                 suggestion='Establish the format and reader contract before dedicated output; do not generate an XML key.')
    for folder in folders:
        for category in ('Strings', 'WordLists', 'Languages/English/WordLists', 'Languages/English/WordInfo'):
            base = folder / category
            if base.is_dir() and not base.is_symlink():
                warn('strings-unsupported', f'Unverified text resource format excluded: {base.relative_to(source)}',
                     base.relative_to(source).as_posix(),
                     suggestion=('Verify the dedicated WordInfo reader and output contract; do not generate XML keys.'
                                 if category == 'Languages/English/WordInfo' else ''))
    for file in content_files(folders,'Assemblies','.dll'):
        stats['dlls'] += 1
        warn('dll-text', f'{file.relative_to(source)}: DLL may generate text/Defs at runtime. CLR fields can be inspected; hard-coded text needs author/Keyed review.',str(file.relative_to(source)))
        check_cancel()
        from . import il_candidates
        relative = file.relative_to(source).as_posix()
        try:
            try:
                calls, reused = _cached_assembly_result(
                    cache_path, file, 'translate-calls',
                    lambda path: [list(call) for call in il_candidates.inspect_translate_calls(path, check_cancel)])
            except sqlite3.Error as exc:
                raise ValueError(f'cache unavailable: {exc}') from exc
            if schema is None:
                assemblies_seen['reused' if reused else 'read'] += 1
            for method_index, method_name, offset, literal in calls:
                warn('dll-translate-candidate',
                     f'Unverified direct Translate(string) key {literal!r}: MethodDef {method_index} {method_name}, IL_{offset:04x}: {relative}',
                     relative, suggestion='Inspect the target English Keyed catalog and runtime caller; a literal key is not English source text and is not exported.')
        except (OSError, ValueError) as exc:
            warn('dll-il-unverified', f'IL inspection unavailable: {relative}: {exc}', relative,
                 suggestion='Inspect assembly metadata manually; no DLL was executed and no XML key was generated.')
    for entry in result.entries:
        entry.reasons = entry_reasons(entry, own_translations)
    if schema:
        for warning in schema.warnings:
            warn('metadata',warning)
    if omitted:
        result.warnings.append(f'{omitted} additional distinct warnings omitted (total events {result.warning_count}); inspect source context manually')
    stats.update(entries=len(result.entries), blocked=sum(e.blocked for e in result.entries), schema_fields=sum(e.confidence=='schema' for e in result.entries), seconds=round(time.perf_counter()-start,4))
    stats['reuse'] = {'result_reused': False, 'files_reused': stats['cached_files'], 'files_parsed': stats['parsed_files'],
                      'assemblies_reused': assemblies_seen['reused'], 'assemblies_read': assemblies_seen['read']}
    if reuse_slot is not None:
        from dataclasses import asdict
        try:
            stored = json.dumps(asdict(result), ensure_ascii=False)
            database = sqlite3.connect(cache_path)
            try:
                database.execute('INSERT OR REPLACE INTO scan_result_v1 VALUES (?,?,?)', (reuse_slot, fingerprint, stored))
                database.commit()
            finally:
                database.close()
        except (TypeError, ValueError, sqlite3.Error):
            pass  # an unstorable result only costs the next scan its shortcut
    if progress:
        progress(len(files),len(files),len(result.entries),'Complete')
    return result
