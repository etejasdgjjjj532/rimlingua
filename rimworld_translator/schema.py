"""Read CLR field metadata without loading or executing game/MOD assemblies."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import gzip
import hashlib
import json
from pathlib import Path
import re


@dataclass
class FieldSpec:
    type_name: str
    attributes: tuple[str, ...] = ()
    is_list: bool = False
    handle_priority: int = 0
    # LoadAlias names: XML may name the field by these, and the game's DefInjected lookup accepts them too.
    aliases: tuple[str, ...] = ()

    @property
    def forbidden(self):
        return any(a in self.attributes for a in ('NoTranslateAttribute', 'UnsavedAttribute'))

    @property
    def translatable(self):
        # Typed eligibility only; field semantics must also be checked by callers.
        return self.type_name == 'System.String' and not self.forbidden


@dataclass
class TypeSpec:
    name: str
    base: str = ''
    fields: dict[str, FieldSpec] = field(default_factory=dict)


@dataclass
class TranslationSchema:
    types: dict[str, TypeSpec] = field(default_factory=dict)
    assemblies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # RimWorld version of the shipped field table when game types come from it rather than an installation.
    builtin_version: str = ''
    # Def names and Keyed keys of the game itself, when its data folders are not among the scan's sources.
    known_defs: frozenset = frozenset()
    known_keyed: frozenset = frozenset()

    def find_type(self, name: str) -> TypeSpec | None:
        if name in self.types:
            return self.types[name]
        aliases = getattr(self, '_aliases', None)
        if aliases is None:
            aliases = self._aliases = {}
            for key, typ in self.types.items():
                aliases.setdefault(key.rsplit('.', 1)[-1], []).append(typ)
        found = aliases.get(name, [])
        if not found and '.' in name:
            # Game updates move types between namespaces (Verse.X -> RimWorld.X); a MOD built against the old name
            # still means the same class.
            found = aliases.get(name.rsplit('.', 1)[-1], [])
        return found[0] if len(found) == 1 else None

    def guess_base(self, type_name: str) -> str:
        """Guess the Def type an unreadable class extends from RimWorld's "Prefix + BaseName" convention.

        AlienBackstoryDef -> BackstoryDef. A name ending in Def that matches no longer suffix is read as the root Def
        (label, description), which every Def has.
        """
        last = type_name.rsplit('.', 1)[-1]
        if not last.endswith('Def'):
            return ''
        words = re.findall(r'[A-Z][a-z0-9]*', last)
        for start in range(1, len(words) - 1):
            candidate = ''.join(words[start:])
            if self.find_type(candidate):
                return candidate
        return 'Def' if self.find_type('Def') else ''

    def parent_of(self, typ: 'TypeSpec') -> 'TypeSpec | None':
        """Base class, or a convention-based guess when its assembly was not loaded (another mod's DLL)."""
        parent = self.find_type(typ.base)
        if parent is None and typ.base:
            guess = self.guess_base(typ.base)
            parent = self.find_type(guess) if guess else None
        return parent

    def chain_complete(self, name: str) -> bool:
        """Whether every base class of a type was read, so its field list is the whole list.

        A MOD class extending a game class is incomplete when the game assembly is not
        loaded: fields it inherits (label, description, ...) are then simply unknown,
        not absent.
        """
        cache = self.__dict__.setdefault('_complete_cache', {})
        if name in cache:
            return cache[name]
        visited = set()
        typ = self.find_type(name)
        complete = typ is not None
        while typ is not None and typ.name not in visited:
            visited.add(typ.name)
            if not typ.base or typ.base.startswith('System.'):
                break
            parent = self.parent_of(typ)
            if parent is None:
                complete = False
                break
            typ = parent
        cache[name] = complete
        return complete

    def fields_for(self, name: str) -> dict[str, FieldSpec]:
        cache = getattr(self, '_fields_cache', None)
        if cache is None:
            cache = self._fields_cache = {}
        if name in cache:
            return cache[name]
        result, visited = {}, set()
        typ = self.find_type(name)
        while typ is not None and typ.name not in visited:
            visited.add(typ.name)
            for key, value in typ.fields.items():
                result.setdefault(key, value)
            for value in typ.fields.values():
                for alias in value.aliases:
                    result.setdefault(alias, value)
            typ = self.parent_of(typ)
        cache[name] = result
        return result

    def field_owner(self, name: str, field_name: str) -> str:
        """Return the declaring CLR owner, following the same inheritance order."""
        visited = set()
        typ = self.find_type(name)
        while typ is not None and typ.name not in visited:
            visited.add(typ.name)
            if field_name in typ.fields or any(field_name in spec.aliases for spec in typ.fields.values()):
                return typ.name
            typ = self.parent_of(typ)
        return ''

    def is_def(self, name: str) -> bool:
        visited = set()
        typ = self.find_type(name)
        while typ and typ.name not in visited:
            if typ.name == 'Verse.Def' or typ.name == 'Def':
                return True
            visited.add(typ.name)
            typ = self.parent_of(typ)
        return False


def _compressed(data: bytes, at: int):
    b = data[at]
    if b < 0x80:
        return b, at + 1
    if b < 0xc0:
        return ((b & 0x3f) << 8) | data[at + 1], at + 2
    return ((b & 0x1f) << 24) | int.from_bytes(data[at+1:at+4], 'big'), at + 4


def translation_handle_priority(blob: bytes, constructor_signature: bytes) -> int:
    """Decode positional/named Int32 priority without executing the attribute."""
    priority = 0
    try:
        if blob[:2] != b'\x01\x00':
            return priority
        parameters, signature_at = _compressed(constructor_signature, 1)
        if constructor_signature[signature_at] != 0x01:  # Void return.
            return priority
        at = 2
        if parameters == 1 and constructor_signature[signature_at + 1:] == b'\x08':
            if len(blob) < at + 4:
                return priority
            priority = int.from_bytes(blob[at:at + 4], 'little', signed=True)
            at += 4
        elif parameters != 0:
            return priority
        if len(blob) < at + 2:
            return priority
        named_count = int.from_bytes(blob[at:at + 2], 'little')
        at += 2
        for _ in range(named_count):
            kind, value_type = blob[at:at + 2]
            at += 2
            if kind not in (0x53, 0x54) or value_type != 0x08:
                return priority
            length, at = _compressed(blob, at)
            name = blob[at:at + length].decode('utf-8')
            at += length
            if len(blob) < at + 4:
                return priority
            value = int.from_bytes(blob[at:at + 4], 'little', signed=True)
            at += 4
            if name == 'Priority':
                priority = value
    except (IndexError, UnicodeDecodeError, ValueError):
        return priority
    return priority


def load_alias(blob: bytes) -> str:
    """The string argument of a LoadAliasAttribute blob (prolog 01 00, then a SerString); '' when absent."""
    try:
        if blob[:2] != b'\x01\x00' or blob[2] == 0xff:
            return ''
        length, at = _compressed(blob, 2)
        return blob[at:at + length].decode('utf-8')
    except (IndexError, UnicodeDecodeError):
        return ''


def inspect_assembly(path: Path, cancel=None) -> dict[str, TypeSpec]:
    """Decode only the tables needed by localization (ECMA-335 metadata).

    Access raw coded indices: dnfile's eager table-reference expansion is
    prohibitively expensive for the large RimWorld assembly on older CPUs.
    """
    import dnfile
    def check():
        if cancel and cancel():
            from .extraction import ScanCancelled
            raise ScanCancelled()
    check()
    with path.open('rb') as stream:
        if stream.read(40).startswith(b'version https://git-lfs.github.com/spec/'):
            raise ValueError('Git LFS pointer, not an assembly; runtime DLL is missing from this source snapshot')
    try:
        pe = dnfile.dnPE(str(path), clr_lazy_load=True)
    except dnfile.PEFormatError as exc:
        raise ValueError(f'Invalid PE assembly: {exc}') from exc
    try:
        if not pe.net or not pe.net.mdtables:
            raise ValueError('Not a managed CLR assembly')
        md = pe.net.mdtables
        typedefs = list(md.TypeDef.rows) if md.TypeDef else []
        typerefs = list(md.TypeRef.rows) if md.TypeRef else []
        names = [f'{row.TypeNamespace}.{row.TypeName}'.strip('.') for row in typedefs]
        refs = [f'{row.TypeNamespace}.{row.TypeName}'.strip('.') for row in typerefs]
        fields = list(md.Field.rows) if md.Field else []
        method_types = {}
        for i, row in enumerate(typedefs):
            if i%500==0:
                check()
            start = row.struct.MethodList_Index
            end = typedefs[i+1].struct.MethodList_Index if i+1 < len(typedefs) else len(md.MethodDef.rows)+1
            for idx in range(start, end):
                method_types[idx] = names[i]

        def type_name(code):
            idx, tag = (code >> 2) - 1, code & 3
            if tag == 0 and 0 <= idx < len(names):
                return names[idx]
            if tag == 1 and 0 <= idx < len(refs):
                return refs[idx]
            return ''

        attrs, priorities, aliases = {}, {}, {}
        def raw_signature(row):
            signature = getattr(row, 'Signature', None)
            value = getattr(signature, 'value', None) if signature is not None else None
            return bytes(value) if isinstance(value, (bytes, bytearray)) else b''

        if md.CustomAttribute:
            for index,row in enumerate(md.CustomAttribute.rows):
                if index%500==0:
                    check()
                parent = row.struct.Parent_CodedIndex
                # HasCustomAttribute tag 1 = Field.
                if parent & 31 != 1:
                    continue
                ctor = row.struct.Type_CodedIndex
                tag, idx = ctor & 7, ctor >> 3
                attribute = ''
                constructor_row = None
                if tag == 2:
                    attribute = method_types.get(idx, '')
                    if 0 < idx <= len(md.MethodDef.rows):
                        constructor_row = md.MethodDef.rows[idx - 1]
                elif tag == 3 and md.MemberRef and 0 < idx <= len(md.MemberRef.rows):
                    member = md.MemberRef.rows[idx - 1]
                    constructor_row = member
                    cls = member.struct.Class_CodedIndex
                    if cls & 7 in (0, 1):
                        attribute = type_name(((cls >> 3) << 2) | (cls & 7))
                attribute = attribute.rsplit('.', 1)[-1]
                attrs.setdefault(parent >> 5, []).append(attribute)
                if attribute == 'LoadAliasAttribute':
                    alias = load_alias(bytes(row.Value.value))
                    if alias:
                        aliases.setdefault(parent >> 5, []).append(alias)
                if attribute == 'TranslationHandleAttribute':
                    constructor_signature = raw_signature(constructor_row) if constructor_row is not None else b''
                    priorities[parent >> 5] = translation_handle_priority(row.Value.value, constructor_signature)

        primitives = {0x0e:'System.String', 0x02:'System.Boolean', 0x08:'System.Int32', 0x0c:'System.Single', 0x0d:'System.Double', 0x1c:'System.Object'}

        def signature(data, at=1):
            if at >= len(data):
                return '', False, at
            kind, at = data[at], at + 1
            if kind in primitives:
                return primitives[kind], False, at
            if kind in (0x11, 0x12):
                code, at = _compressed(data, at)
                return type_name(code), False, at
            if kind in (0x1d, 0x10):
                name, _, at = signature(data, at)
                return name, kind == 0x1d, at
            if kind == 0x15:
                at += 1  # class/valuetype marker
                code, at = _compressed(data, at)
                count, at = _compressed(data, at)
                args = []
                for _ in range(count):
                    name, _, at = signature(data, at)
                    args.append(name)
                name = type_name(code)
                if name in ('System.Collections.Generic.List`1', 'System.Collections.Generic.IEnumerable`1', 'System.Collections.Generic.IList`1') and args:
                    return args[0], True, at
                return name + '[' + ','.join(args) + ']', False, at
            if kind in (0x1f, 0x20):
                _, at = _compressed(data, at)
                return signature(data, at)
            return '', False, at

        result = {}
        for i, row in enumerate(typedefs):
            if i%500==0:
                check()
            start = row.struct.FieldList_Index
            end = typedefs[i+1].struct.FieldList_Index if i+1 < len(typedefs) else len(fields)+1
            specs = {}
            for idx in range(start, end):
                f = fields[idx-1]
                # static fields are not serialized Def data.
                if f.struct.Flags & 0x10:
                    continue
                try:
                    name, is_list, _ = signature(f.Signature.value)
                except (IndexError, ValueError):
                    name, is_list = '', False
                specs[str(f.Name)] = FieldSpec(name, tuple(attrs.get(idx, ())), is_list, priorities.get(idx, 0),
                                               tuple(aliases.get(idx, ())))
            result[names[i]] = TypeSpec(names[i], type_name(row.struct.Extends_CodedIndex), specs)
        return result
    finally:
        pe.close()


# 2: field rows carry LoadAlias names. Older cached tables are rebuilt when the game is at hand.
GAME_TABLE_FORMAT = 2
GAME_TABLE_ATTRIBUTES = ('MustTranslateAttribute', 'MayTranslateAttribute', 'NoTranslateAttribute', 'UnsavedAttribute',
                         'TranslationHandleAttribute')
_game_tables = {}


def build_game_table(game: Path) -> dict:
    """Class names, base classes, field types and localization attributes, plus Def and Keyed names, of an installed game.

    Reads Assembly-CSharp.dll as ECMA-335 metadata only; nothing is loaded or executed. The result stays on the
    user's machine as a cache (see game_table_schema) and is never part of this program's distribution.
    Compiler-generated classes are left out.
    """
    import xml.etree.ElementTree as ET
    from .game_library import game_dll
    dll = game_dll(Path(game))
    if dll is None:
        raise FileNotFoundError(f'Assembly-CSharp.dll not found in {game}')
    types = {}
    for name, typ in sorted(inspect_assembly(dll).items()):
        if '<' in name:
            continue
        fields = {}
        for field_name, spec in typ.fields.items():
            row = [spec.type_name, [a for a in spec.attributes if a in GAME_TABLE_ATTRIBUTES], int(spec.is_list), spec.handle_priority,
                   list(spec.aliases)]
            while len(row) > 1 and not row[-1]:
                row.pop()
            fields[field_name] = row
        types[name] = [typ.base, fields]
    # Names only, from the game's own data folders (Core and the installed expansions): a value equal to one
    # of them is a reference to that Def or Keyed entry, not wording.
    from .game_library import child, descend
    def_names, keyed_keys, data_folders = set(), set(), []
    data = child(Path(game), 'Data')
    folders = sorted(p for p in data.iterdir() if p.is_dir()) if data is not None and data.is_dir() else ()
    for folder in (p for p in folders if descend(p, 'About', 'About.xml') is not None):
        data_folders.append(folder.name)
        defs, keyed = descend(folder, 'Defs'), descend(folder, 'Languages', 'English', 'Keyed')
        for file in sorted(defs.rglob('*.xml')) if defs is not None else ():
            try:
                def_names.update((node.text or '').strip() for node in ET.parse(file).getroot().iter('defName'))
            except ET.ParseError:
                continue
        for file in sorted(keyed.rglob('*.xml')) if keyed is not None else ():
            try:
                keyed_keys.update(child.tag for child in ET.parse(file).getroot() if isinstance(child.tag, str))
            except ET.ParseError:
                continue
    version_file = child(Path(game), 'Version.txt')
    return {'format': GAME_TABLE_FORMAT,
            'rimworld_version': version_file.read_text(encoding='utf-8-sig').strip() if version_file is not None and version_file.is_file() else '',
            'assembly_sha256': hashlib.sha256(dll.read_bytes()).hexdigest(), 'types': types,
            'data_folders': data_folders, 'def_names': sorted(def_names - {''}), 'keyed_keys': sorted(keyed_keys)}


def schema_from_game_table(data: dict) -> TranslationSchema:
    """A schema from build_game_table output (or the same JSON read back from the cache)."""
    key = (data.get('assembly_sha256', ''), data.get('format', 1))
    if key not in _game_tables:
        types = {name: TypeSpec(name, base, {field: FieldSpec(row[0], tuple(row[1]) if len(row) > 1 else (),
                                                              bool(row[2]) if len(row) > 2 else False,
                                                              row[3] if len(row) > 3 else 0,
                                                              tuple(row[4]) if len(row) > 4 else ())
                                             for field, row in fields.items()})
                 for name, (base, fields) in data['types'].items()}
        _game_tables[key] = (data.get('rimworld_version', ''), frozenset(data.get('def_names', ())),
                             frozenset(data.get('keyed_keys', ())), types)
    version, defs, keyed, types = _game_tables[key]
    # TypeSpec and FieldSpec are never mutated after loading, so every scan can share them.
    return TranslationSchema(types=dict(types), builtin_version=version, known_defs=defs, known_keyed=keyed)


def game_table_schema(cache_dir: Path | None, game_roots=()) -> TranslationSchema | None:
    """Game classes and their fields as read earlier from the user's own installation, for a scan of another version.

    The table is built once per game assembly from ``game_roots`` and kept under ``cache_dir`` (never inside this
    program), so later projects skip the slow assembly read. A field is looked up by its owning class, and a MOD
    class extending a game Def inherits that Def's fields. The table is one game version's; callers must say so.
    Returns None when there is no cache and no installation to read.
    """
    cache = Path(cache_dir) if cache_dir else None
    from .game_library import game_dll
    for root in game_roots:
        dll = game_dll(Path(root))
        if dll is None:
            continue
        try:
            fingerprint = hashlib.sha256(dll.read_bytes()).hexdigest()
            stored = cache / (fingerprint + '.json.gz') if cache else None
            if stored is not None and stored.is_file():
                data = json.loads(gzip.decompress(stored.read_bytes()))
                if data.get('format', 1) >= GAME_TABLE_FORMAT:
                    return schema_from_game_table(data)
            data = build_game_table(Path(root))
            if stored is not None:
                from .core import atomic_write
                from .platforms import mark_cache_folder
                # Own the folder only when this call creates it; a pre-existing folder may hold the user's files.
                if not cache.exists():
                    mark_cache_folder(cache)
                atomic_write(stored, gzip.compress(json.dumps(data, separators=(',', ':'), sort_keys=True).encode(), mtime=0))
            return schema_from_game_table(data)
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            continue
    if cache is not None and cache.is_dir():
        for stored in sorted(cache.glob('*.json.gz'), reverse=True):
            try:
                return schema_from_game_table(json.loads(gzip.decompress(stored.read_bytes())))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                continue
    return None


def schema_from_assemblies(paths, cache_dir: Path | None = None,cancel=None, base: TranslationSchema | None = None) -> TranslationSchema:
    """Read assemblies into one schema. ``base`` supplies game classes when no game assembly is among the paths."""
    result = base if base is not None else TranslationSchema()
    for value in paths:
        if cancel and cancel():
            from .extraction import ScanCancelled
            raise ScanCancelled()
        path = Path(value)
        if not path.is_file() or path.is_symlink():
            continue
        try:
            cached = None
            if cache_dir:
                fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
                # Retain old indexes but never reuse their obsolete attribute decoder.
                # v3 adds LoadAlias names; v2 indexes stay on disk but are not read.
                cached = Path(cache_dir) / 'clr-fields-v3' / (fingerprint + '.json')
            if cached and cached.exists():
                raw = json.loads(cached.read_text(encoding='utf-8'))
                types = {name: TypeSpec(name, item['base'], {f: FieldSpec(**{**v, 'attributes': tuple(v.get('attributes', ())),
                                                                              'aliases': tuple(v.get('aliases', ()))})
                                                              for f, v in item['fields'].items()}) for name, item in raw.items()}
            else:
                types = inspect_assembly(path,cancel=cancel)
                if cached:
                    from .core import atomic_write
                    atomic_write(cached, json.dumps({name:asdict(t) for name,t in types.items()}, separators=(',', ':')).encode())
            result.types.update(types)
            result.assemblies.append(str(path))
        except (OSError, ValueError, AttributeError, IndexError) as exc:
            result.warnings.append(f'{path.name}: metadata unavailable: {exc}')
    return result


def normalized_handle(value: str) -> str:
    value = value.strip().replace(' ', '_').replace('\n','_').replace('\r','').replace('\t','_').replace('.','').replace('-','')
    value = re.sub(r'\{.*?\}', '', value)
    value = re.sub(r'[^A-Za-z0-9_]', '', value)
    value = re.sub('_+', '_', value).strip('_')
    return '_' + value if value.isdigit() else value
