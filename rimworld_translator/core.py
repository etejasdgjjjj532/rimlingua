"""Conservative XML extraction and translation-only persistence."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
import copy
from .languages import validate_language, validate_languages
from .preview import make_preview_bytes
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET


MAX_XML = 8 * 1024 * 1024
# RimWorld reads the literal value "TODO" as an untranslated placeholder.
PLACEHOLDER = "TODO"
FIELDS = {"label", "description", "labelPlural", "jobString", "reportString", "verb", "gerund", "pawnLabel", "inspectString", "deathMessage", "labelShort", "text", "title"}
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
PACKAGE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
TOKENS = re.compile(r"\{(?:\d+|[A-Za-z_]\w*)(?:[^{}]*)\}")
INVALID_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def safe_xml(path: Path) -> ET.Element:
    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > MAX_XML:
        raise ValueError("Symbolic link or oversized XML")
    data = path.read_bytes()
    normalized = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        raise ValueError("DTD / ENTITY declarations are prohibited")
    return ET.fromstring(data)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing symbolic link: {path}")
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


# Read-only MOD folders the user added in Preferences (Workshop and extra folders): never a write target.
_PROTECTED_FOLDERS: tuple = ()


def set_protected_folders(folders) -> None:
    """Replace the user's read-only MOD folders that writable_destination refuses to overlap."""
    global _PROTECTED_FOLDERS
    _PROTECTED_FOLDERS = tuple(Path(f).expanduser() for f in folders if f)


def writable_destination(path: Path, source: Path) -> Path:
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Destination contains a symbolic link")
    dest, src = path.resolve(), source.resolve()
    if dest == src or src in dest.parents or dest in src.parents:
        raise ValueError("Source and destination must be separate directories")
    if "steamapps" in [p.lower() for p in dest.parts]:
        raise ValueError("Writing inside installed Steam content is prohibited")
    for folder in _PROTECTED_FOLDERS:
        try:
            protected = folder.resolve()
        except (OSError, RuntimeError):
            continue
        if dest == protected or protected in dest.parents or dest in protected.parents:
            raise ValueError(f"Writing inside a read-only MOD folder from Preferences is prohibited: {folder}")
    return dest


@dataclass
class Entry:
    id: str
    kind: str
    group: str
    key: str
    english: str
    source_file: str
    japanese: str = ""
    review: bool = False
    changed: bool = False
    stale: bool = False
    previous_english: str = ""
    blocked: bool = False
    reviewed: bool = False
    approved: bool = False
    excluded: bool = False
    confidence: str = 'heuristic'
    evidence: list[str] = field(default_factory=list)
    is_new: bool = False
    classification: str = ''
    # Entry ids this entry had before its key changed; a rescan moves the old entry's work onto it.
    legacy_keys: list[str] = field(default_factory=list)
    # Machine-readable reasons this entry is a target (extraction.REASONS); empty for entries saved before them.
    reasons: list[str] = field(default_factory=list)
    @property
    def status(self) -> str:
        if self.stale:
            return 'stale'
        if self.changed:
            return 'changed'
        if self.review or self.blocked or placeholder_warning(self):
            return 'needs-review'
        return 'translated' if self.japanese.strip() else 'untranslated'


def placeholder_warning(entry: Entry) -> str:
    if entry.japanese.strip() and sorted(TOKENS.findall(entry.english)) != sorted(TOKENS.findall(entry.japanese)):
        return 'プレースホルダーが一致しません'
    return ''


@dataclass
class Scan:
    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    name: str = "Translation"
    package_id: str = ""
    versions: list[str] = field(default_factory=list)
    warning_count: int = 0
    diagnostics: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    selected_folders: list[str] = field(default_factory=list)


def scan_mod(source: Path, game_version='1.6', active_mods=None, cache_path=None, progress=None, cancel=None, schema=None, context_sources=(), diagnostic_limit=1500, **options) -> Scan:
    from .extraction import scan
    return scan(source, game_version, active_mods, cache_path, progress, cancel, schema, context_sources, diagnostic_limit, **options)


@dataclass
class Project:
    source: str
    name: str
    package_id: str
    original_package_id: str
    versions: list[str]
    entries: list[Entry]
    warnings: list[str]
    schema: int = 1
    language: str = 'Japanese'
    translations: dict[str, dict[str, str]] = field(default_factory=dict)
    languages: list[str] = field(default_factory=lambda: ["Japanese"])
    language_states: dict[str, dict[str, dict]] = field(default_factory=dict)
    glossary: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    game_version: str = '1.6'
    active_mods: list[str] = field(default_factory=list)
    active_mods_known: bool = False
    diagnostics: list[dict] = field(default_factory=list)

    version_profiles: dict[str, dict] = field(default_factory=dict)
    # Where the translation MOD is written; empty means <project folder>/mod (see output_paths).
    output_folder: str = ''
    # Per-row sticky notes ({entry id: {'text', 'flag'}}) and per-file translator names; see notes.py.
    notes: dict[str, dict[str, str]] = field(default_factory=dict)
    assignments: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, source: Path, scan: Scan, languages: list[str] | None = None) -> Project:
        selection = validate_languages(list(languages) if languages is not None else ["Japanese"])
        # Scan evidence can be reused by independent projects. Never give a
        # project ownership of its mutable entries, diagnostics or context.
        scan = copy.deepcopy(scan)
        return cls(str(source.resolve()), scan.name, f"local.translation.multi{uuid.uuid4().hex}",
                   scan.package_id, scan.versions, scan.entries, scan.warnings,
                   language=selection[0], languages=selection, diagnostics=scan.diagnostics,
                   game_version=scan.stats.get('active_version','1.6'),
                   active_mods=scan.stats.get('active_mods') or [],
                   active_mods_known=scan.stats.get('active_mods') is not None)


    @classmethod
    def create_versions(cls, source: Path, scans: dict[str, Scan], languages: list[str] | None = None) -> Project:
        """Create independent profiles from explicitly supplied version-specific scans.

        Callers supply each version's schema and dependency context while scanning;
        this method does not infer verification from another version's game data.
        Missing declared versions remain unscanned, rather than silently copied.
        """
        if not scans:
            raise ValueError('At least one version scan is required')
        ordered = sorted(scans, key=_version_key)
        project = cls.create(source, copy.deepcopy(scans[ordered[0]]), languages)
        declared = sorted(set(project.versions), key=_version_key)
        if any(version not in declared for version in scans):
            raise ValueError('A scan version is not declared by the source MOD')
        project.versions = declared
        for version in ordered:
            project.add_version_scan(version, scans[version])
        project.switch_version(ordered[0])
        return project

    def _stash_version(self) -> None:
        self.stash_current_language()
        profile = self.version_profiles.setdefault(self.game_version, {
            'selected_folders': [], 'stats': {'active_version': self.game_version},
            'coverage': {'extracted': True, 'source_verified': False, 'game_tested': False}})
        profile.update({name: copy.deepcopy(getattr(self, name)) for name in _PROFILE_FIELDS})
        profile['entries'] = [asdict(entry) for entry in self.entries]

    def _version_view(self, version: str) -> Project:
        """Build an independent single-version view without copying other profiles."""
        profile = self.version_profiles[version]
        view = copy.copy(self)
        view.version_profiles = {}
        for name in _PROFILE_FIELDS:
            setattr(view, name, copy.deepcopy(profile[name]))
        view.entries = [Entry(**copy.deepcopy(entry)) for entry in profile['entries']]
        view.game_version = version
        view.__dict__.pop('_index_identity', None)
        view.__dict__.pop('_indexed_entries', None)
        view.__dict__.pop('_entry_index', None)
        view.switch_language(self.language)
        return view

    def switch_version(self, version: str) -> None:
        _version_key(version)
        if version not in self.version_profiles:
            raise ValueError(f'Version has not been scanned: {version}')
        language = self.language
        self._stash_version()
        profile = self.version_profiles[version]
        for name in _PROFILE_FIELDS:
            setattr(self, name, copy.deepcopy(profile[name]))
        self.entries = [Entry(**copy.deepcopy(entry)) for entry in profile['entries']]
        self.game_version = version
        self.switch_language(language)

    def add_version_scan(self, version: str, scan: Scan, *, extend_declared_versions: bool = False) -> None:
        """Add or refresh a version without importing another version's text.

        Explicit extension accepts a newly declared version only when the source
        retains every previous declaration. Other newly declared versions remain
        unscanned and continue to block the all-version test exporter.
        """
        _version_key(version)
        if type(extend_declared_versions) is not bool:
            raise ValueError('Version extension flag must be bool')
        if version not in scan.versions:
            raise ValueError('Version is not declared by the source MOD')
        if scan.package_id != self.original_package_id or scan.stats.get('active_version') != version:
            raise ValueError('Scan source or version does not match the profile')
        if extend_declared_versions:
            if version in self.versions or not set(self.versions) < set(scan.versions):
                raise ValueError('Version extension must add a new version and retain all previous declarations')
            declared = sorted(set(scan.versions), key=_version_key)
        else:
            if version not in self.versions or set(scan.versions) != set(self.versions):
                raise ValueError('Declared versions differ between scans')
            declared = self.versions
        if self.game_version not in declared:
            raise ValueError('Current version is not declared; retain its history before migration')
        self.versions = declared
        self._stash_version()
        if version in self.version_profiles:
            self.switch_version(version)
            self.rescan(copy.deepcopy(scan))
        else:
            fresh = Project.create(Path(self.source), copy.deepcopy(scan), self.languages)
            fresh.language = self.language
            self.entries = copy.deepcopy(fresh.entries)
            for name in _PROFILE_FIELDS:
                setattr(self, name, copy.deepcopy(getattr(fresh, name)))
            self.game_version = version
        self._stash_version()
        self.version_profiles[version].update(
            selected_folders=list(scan.selected_folders), stats=copy.deepcopy(scan.stats),
            coverage={'extracted': True, 'source_verified': False, 'game_tested': False})
        self.versions = sorted(set(self.versions), key=_version_key)
        self.schema = 2

    def stash_current_language(self) -> None:
        validate_language(self.language)
        self.translations[self.language] = {
            entry.id: entry.japanese for entry in self.entries if entry.japanese
        }
        states = self.language_states.setdefault(self.language, {})
        for entry in self.entries:
            state = {name: getattr(entry, name) for name in ('reviewed', 'approved', 'review', 'changed')}
            state['new'] = entry.is_new
            if any(state.values()) or entry.id in states:
                states[entry.id] = state

    def translation_share_versions(self, entry_id: str) -> list[str]:
        """Offer only empty, matching, safe scanned targets; never change state."""
        source = self.entry_index().get(entry_id)
        def eligible(entry):
            return entry is not None and not any((entry.blocked, entry.stale,
                entry.excluded, entry.changed, entry.review))
        if not eligible(source) or not source.japanese.strip() or placeholder_warning(source):
            return []
        versions = []
        for version in sorted(self.version_profiles, key=_version_key):
            if version == self.game_version:
                continue
            target = self._version_view(version).entry_index().get(entry_id)
            if eligible(target) and target.english == source.english and not target.japanese:
                versions.append(version)
        return versions

    def share_translation(self, entry_id: str, versions: list[str]) -> None:
        """Copy a translation only to an explicit validated selection, without approval.

        Existing translations, changed sources and review state are never replaced.
        Validate the entire selection before writing any version profile.
        """
        candidates = self.translation_share_versions(entry_id)
        if (not isinstance(versions, list) or not versions
                or any(not isinstance(version, str) or version not in candidates for version in versions)
                or len(set(versions)) != len(versions)):
            raise ValueError('Select eligible scanned versions explicitly before sharing')
        text = self.entry_index()[entry_id].japanese
        updates = {}
        for version in versions:
            view = self._version_view(version)
            view.version_profiles[version] = copy.deepcopy(self.version_profiles[version])
            view.set_translation(entry_id, text)
            view._stash_version()
            updates[version] = view.version_profiles[version]
        self.version_profiles.update(updates)

    def sync_language_state(self) -> None:
        states = self.language_states.get(self.language, {})
        for entry in self.entries:
            state = states.get(entry.id, {})
            entry.reviewed = bool(state.get('reviewed', False))
            entry.approved = bool(state.get('approved', False))
            entry.review = bool(state.get('review', entry.review))
            entry.changed = bool(state.get('changed', entry.changed))
            entry.is_new = bool(state.get('new', entry.is_new))

    def get_translation(self, entry_id: str, language: str | None = None) -> str:
        language = language or self.language
        if language == self.language:
            entry = self.entry_index().get(entry_id)
            return entry.japanese if entry else ''
        return self.translations.get(language, {}).get(entry_id, '')

    def set_translation(self, entry_id: str, text: str, language: str | None = None) -> None:
        from .field_semantics import entry_nonlocalizable_reason
        language = validate_language(language or self.language)
        entry = self.entry_index().get(entry_id)
        if entry is None:
            raise ValueError(f'Unknown translation entry: {entry_id}')
        if language not in self.languages:
            raise ValueError(f'Language is not selected: {language}')
        if not isinstance(text, str):
            raise ValueError('Translation must be text')
        unsafe_reason = entry_nonlocalizable_reason(entry)
        if unsafe_reason:
            raise ValueError('Non-localizable internal field: ' + unsafe_reason)
        if self.get_translation(entry_id, language) == text:
            return
        self.translations.setdefault(language, {})[entry_id] = text
        state = self.language_states.setdefault(language, {}).setdefault(entry_id, {})
        state.update(reviewed=False, approved=False)
        if language == self.language:
            entry.japanese = text
            entry.reviewed = entry.approved = False

    def mark_reviewed(self, entry_id: str, approved: bool = False) -> None:
        from .field_semantics import entry_nonlocalizable_reason
        entry = self.entry_index()[entry_id]
        unsafe_reason = entry_nonlocalizable_reason(entry)
        if unsafe_reason:
            raise ValueError('Non-localizable internal field: ' + unsafe_reason)
        if entry.blocked or entry.stale or entry.excluded:
            raise ValueError('Blocked, removed or excluded entries cannot be approved')
        if not entry.japanese.strip():
            raise ValueError('Enter a translation before marking it reviewed')
        from .qa import review_blockers
        blockers = review_blockers(entry, entry.japanese, self.glossary)
        if blockers:
            raise ValueError('QAエラーがあるため確認済みにできません: ' + ' / '.join(blockers))
        entry.reviewed, entry.approved = True, approved
        entry.review = entry.changed = entry.is_new = False
        self.stash_current_language()

    def entry_index(self) -> dict[str, Entry]:
        identity = (id(self.entries), len(self.entries))
        if (getattr(self, '_indexed_entries', None) is not self.entries
                or getattr(self, '_index_identity', None) != identity):
            self._indexed_entries = self.entries
            self._index_identity = identity
            self._entry_index = {e.id:e for e in self.entries}
        return self._entry_index

    def switch_language(self, language: str) -> None:
        validate_language(language)
        if language not in self.languages:
            proposed = [*self.languages, language]
            validate_languages(proposed)
            self.languages = proposed
        if language == self.language:
            return
        self.stash_current_language()
        self.language = language
        stored = self.translations.get(language, {})
        for entry in self.entries:
            entry.japanese = stored.get(entry.id, '')
        self.sync_language_state()

    def rescan(self, scan: Scan) -> int:
        """Merge a fresh scan; returns how many entries took over the work of an entry whose key changed."""
        if scan.package_id != self.original_package_id:
            raise ValueError('Rescan does not match the source MOD')
        if scan.stats.get('active_version', self.game_version) != self.game_version:
            raise ValueError('Rescan does not match the current game version')
        if self.version_profiles and (scan.stats.get('active_version') != self.game_version
                                      or set(scan.versions) != set(self.versions)):
            raise ValueError('Rescan does not match the current version profile')
        self.stash_current_language()
        previous = {e.id: e for e in self.entries}
        # An entry whose key changed (index to handle) takes over the old entry's work, unless two scan
        # entries claim the same old key: then nothing is guessed and the old entry stays stale.
        scan_ids = {e.id for e in scan.entries}
        claims = Counter(legacy for e in scan.entries for legacy in e.legacy_keys)
        contested = sorted(legacy for legacy, count in claims.items()
                           if count > 1 and legacy in previous and legacy not in scan_ids)
        adopted: dict[str, str] = {}
        merged = []
        # Review and translation state belongs to this project, not the scan
        # evidence that may also be used to refresh another project.
        for entry in copy.deepcopy(scan.entries):
            old = previous.pop(entry.id, None)
            if old is None:
                candidates = [legacy for legacy in entry.legacy_keys
                              if legacy in previous and legacy not in scan_ids and claims[legacy] == 1]
                if len(candidates) == 1:
                    old = previous.pop(candidates[0])
                    adopted[old.id] = entry.id
            if old:
                entry.japanese = old.japanese
                entry.changed = old.changed or old.stale or entry.english != old.english
                entry.previous_english = old.english if entry.english != old.english else old.previous_english
                entry.review = entry.review or old.review or entry.changed or old.stale
                entry.excluded, entry.classification = old.excluded, old.classification
                entry.reviewed, entry.approved = old.reviewed, old.approved
                entry.is_new = old.is_new
                if entry.english != old.english or old.stale:
                    entry.reviewed = entry.approved = False
                    # Deselected languages retain their saved work, so source
                    # changes must also invalidate their old approval state.
                    for language in set(self.languages) | self.translations.keys() | self.language_states.keys():
                        state = self.language_states.setdefault(language, {}).setdefault(entry.id, {})
                        state.update(reviewed=False, approved=False, changed=True, review=True)
            else:
                entry.is_new = True
            merged.append(entry)
        for entry in previous.values():
            entry.stale = entry.source_file != "(manual)"
            merged.append(entry)
        self.entries = merged
        self.warnings, self.diagnostics = copy.deepcopy((scan.warnings, scan.diagnostics))
        self.warnings.extend(f'Several entries claim the previous key {legacy}; its translation stays on the old entry '
                             'and was not moved. Copy it by hand.' for legacy in contested)
        # Other languages keep their text and review state under the new id.
        for language in set(self.translations) | set(self.language_states):
            for table in (self.translations.get(language), self.language_states.get(language)):
                for old_id, new_id in adopted.items():
                    if table is not None and old_id in table:
                        table.setdefault(new_id, table.pop(old_id))
        self.name, self.original_package_id = scan.name, scan.package_id
        self.versions = list(scan.versions)
        self.active_mods = copy.deepcopy(scan.stats.get('active_mods') or [])
        self.active_mods_known = scan.stats.get('active_mods') is not None
        self.stash_current_language()
        if self.version_profiles:
            self.versions = sorted(set(self.versions), key=_version_key)
            self._stash_version()
            self.version_profiles[self.game_version].update(
                selected_folders=list(scan.selected_folders), stats=copy.deepcopy(scan.stats),
                coverage={'extracted': True, 'source_verified': False, 'game_tested': False})
        return len(adopted)

    def save(self, path: Path) -> None:
        validate_languages(self.languages)
        if self.language not in self.languages:
            raise ValueError('Current language is not selected')
        if self.version_profiles:
            self._stash_version()
            # Language selection is global. Keep inactive snapshots loadable
            # after a language is deselected, while retaining its saved work.
            for version, profile in self.version_profiles.items():
                if profile['language'] not in self.languages:
                    view = self._version_view(version)
                    view.stash_current_language()
                    profile.update({name: copy.deepcopy(getattr(view, name)) for name in _PROFILE_FIELDS})
                    profile['entries'] = [asdict(entry) for entry in view.entries]
            self.schema = 2
        else:
            self.stash_current_language()
        writable_destination(path.parent, Path(self.source))
        if path.is_symlink():
            raise ValueError("Project file is a symbolic link")
        # Strings and metadata are immutable/read-only during this synchronous
        # save. Avoid deep-copying every multilingual value before encoding.
        data_fields = {f.name:getattr(self,f.name) for f in fields(self)}
        entry_fields = tuple(f.name for f in fields(Entry))
        data_fields['entries'] = [{name:getattr(entry,name) for name in entry_fields} for entry in self.entries]
        text = json.dumps(data_fields,ensure_ascii=False,separators=(',', ':'))+'\n'
        # JSON decoders combine escaped surrogate pairs, losing the original
        # code units. Keep those invalid strings rejected rather than repair them.
        if re.search('[\ud800-\udbff][\udc00-\udfff]', text):
            raise ValueError('Cannot losslessly save adjacent surrogate pairs')
        data = text.encode('utf-8', errors='backslashreplace')
        if not path.exists() or path.read_bytes() != data:
            atomic_write(path, data)

    @classmethod
    def load(cls, path: Path) -> Project:
        if path.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("Project file too large")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError('top-level value is not an object')
        except (ValueError, UnicodeDecodeError) as exc:
            # Unreadable JSON in a real project file is not something another version could open: keep the bytes,
            # never overwrite them. Any other file (the open dialog accepts any *.json) is left exactly as it is.
            if path.name != PROJECT_FILE_NAME and path.resolve() not in _KNOWN_PROJECT_FILES:
                raise ProjectFileError(f'プロジェクトファイルではありません(JSON として読めません): {path.name}。ファイルには触れていません。原因: {exc}', path, None) from exc
            raise _keep_aside(path, exc) from exc
        _KNOWN_PROJECT_FILES.add(path.resolve())
        return cls._from_data(data)

    @classmethod
    def _from_data(cls, data: dict) -> Project:
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data.get("schema") not in (1, 2):
            raise ValueError("Unsupported project schema")
        for name in ("source", "name", "package_id", "original_package_id"):
            if not isinstance(data.get(name), str):
                raise ValueError(f"Invalid project field: {name}")
        for name in ("versions", "warnings"):
            if not isinstance(data.get(name), list) or not all(isinstance(x, str) for x in data[name]):
                raise ValueError(f"Invalid project field: {name}")
        if not isinstance(data.get("entries"), list) or len(data["entries"]) > 100000:
            raise ValueError("Invalid or oversized entry list")
        data["entries"] = [Entry(**item) for item in data["entries"]]
        project = cls(**data)
        if (not isinstance(project.game_version,str) or not re.fullmatch(r'\d+\.\d+',project.game_version)
                or type(project.active_mods_known) is not bool or not isinstance(project.active_mods,list)
                or any(not isinstance(p,str) or not PACKAGE.fullmatch(p) for p in project.active_mods)):
            raise ValueError('Invalid extraction context')
        if not isinstance(project.output_folder, str) or (project.output_folder and not Path(project.output_folder).is_absolute()):
            raise ValueError('Invalid output folder')
        if not isinstance(project.language_states, dict) or not isinstance(project.glossary, dict) or not isinstance(project.metadata, dict):
            raise ValueError('Invalid project settings')
        for language, states in project.language_states.items():
            validate_language(language)
            if not isinstance(states, dict) or any(not isinstance(s, dict) or any(type(v) is not bool for v in s.values()) for s in states.values()):
                raise ValueError('Invalid per-language review state')
        if not all(isinstance(k, str) and isinstance(v, str) for mapping in (project.glossary, project.metadata) for k, v in mapping.items()):
            raise ValueError('Invalid glossary or metadata')
        if (not isinstance(project.notes, dict) or not isinstance(project.assignments, dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in project.assignments.items())
                or not all(isinstance(k, str) and isinstance(v, dict) and all(
                    isinstance(a, str) and isinstance(b, str) for a, b in v.items()) for k, v in project.notes.items())):
            raise ValueError('Invalid notes or assignments')
        if "languages" not in data and project.language != "Japanese":
            project.languages = list(dict.fromkeys(["Japanese", project.language]))
        validate_languages(project.languages)
        validate_language(project.language)
        if project.language not in project.languages:
            raise ValueError("Current language must be selected")
        if not isinstance(project.translations, dict) or len(project.translations) > 160:
            raise ValueError('Invalid translation languages')
        for language, entries in project.translations.items():
            validate_language(language)
            if not isinstance(entries, dict) or len(entries) > 100000:
                raise ValueError('Invalid language translation map')
            if not all(isinstance(key, str) and len(key) <= 1000 and isinstance(value, str)
                       for key, value in entries.items()):
                raise ValueError('Invalid translated entry')
        if not PACKAGE.fullmatch(project.package_id) or (project.original_package_id and not PACKAGE.fullmatch(project.original_package_id)):
            raise ValueError("Invalid package ID")
        seen = set()
        from .string_resources import validate_string_entry
        for entry in project.entries:
            if not all(isinstance(getattr(entry, name), str) for name in ("id", "kind", "group", "key", "english", "source_file", "japanese", "previous_english", "confidence", "classification")) or not all(type(getattr(entry, name)) is bool for name in ("review", "changed", "stale", "blocked", "reviewed", "approved", "excluded", "is_new")) or not isinstance(entry.evidence, list) or not all(isinstance(v, str) for v in entry.evidence) or not isinstance(entry.legacy_keys, list) or not all(isinstance(v, str) for v in entry.legacy_keys) or not isinstance(entry.reasons, list) or not all(isinstance(v, str) for v in entry.reasons):
                raise ValueError("Invalid entry field types")
            valid_key = (validate_string_entry(entry.group, entry.key) if entry.kind == 'Strings'
                         else entry.kind in {'Keyed', 'DefInjected'}
                         and KEY.fullmatch(entry.group) and KEY.fullmatch(entry.key))
            if not valid_key or entry.id in seen:
                raise ValueError("Invalid or duplicate entry")
            if entry.id != f"{entry.kind}:{entry.group}:{entry.key}":
                raise ValueError("Invalid stable ID")
            seen.add(entry.id)
        if not isinstance(project.version_profiles, dict):
            raise ValueError('Invalid version profiles')
        if project.version_profiles and project.schema != 2:
            raise ValueError('Version profiles require schema 2')
        for version, profile in project.version_profiles.items():
            _version_key(version)
            if version not in project.versions or not isinstance(profile, dict):
                raise ValueError('Invalid or undeclared version profile')
            required = {'entries', *_PROFILE_FIELDS, 'selected_folders', 'stats', 'coverage'}
            if set(profile) != required:
                raise ValueError('Invalid version profile fields')
            if (not isinstance(profile['selected_folders'], list)
                    or not all(isinstance(folder, str) and not Path(folder).is_absolute()
                               and '..' not in Path(folder).parts for folder in profile['selected_folders'])
                    or not isinstance(profile['stats'], dict)
                    or not isinstance(profile['coverage'], dict)
                    or set(profile['coverage']) != {'extracted', 'source_verified', 'game_tested'}
                    or not all(type(value) is bool for value in profile['coverage'].values())):
                raise ValueError('Invalid profile coverage or folders')
            if profile['stats'].get('active_version') != version:
                raise ValueError('Invalid profile scan version')
            child = {key: copy.deepcopy(value) for key, value in data.items()
                     if key not in {'entries', 'version_profiles'}}
            child.update(copy.deepcopy(profile))
            for key in ('selected_folders', 'stats', 'coverage'):
                child.pop(key)
            child.update(game_version=version, schema=1, version_profiles={})
            cls._from_data(child)
        if project.version_profiles and project.game_version not in project.version_profiles:
            raise ValueError('Current version has no profile')
        return project


PROJECT_FILE_NAME = 'project.json'
# Files that loaded successfully as projects earlier in this process; if they later turn corrupt they are kept aside.
_KNOWN_PROJECT_FILES: set[Path] = set()


class ProjectFileError(ValueError):
    """The project file is not valid JSON. ``kept_at`` is where the unreadable file was moved to (None if that failed)."""
    def __init__(self, message: str, path: Path, kept_at: Path | None):
        super().__init__(message)
        self.path, self.kept_at = path, kept_at


def _keep_aside(path: Path, cause: Exception) -> ProjectFileError:
    """Move an unreadable project file next to itself as ``<name>.corrupt-<time>`` so it can be inspected and is never overwritten."""
    import datetime
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    kept = path.with_name(f'{path.name}.corrupt-{stamp}')
    number = 1
    while kept.exists():
        number += 1
        kept = path.with_name(f'{path.name}.corrupt-{stamp}-{number}')
    try:
        os.replace(path, kept)
    except OSError:
        kept = None
    where = f'壊れたファイルは {kept} に退避しました。' if kept else '壊れたファイルを退避できませんでした。そのまま残しています。'
    return ProjectFileError(f'プロジェクトファイルを読み込めません(JSON が壊れています): {path.name}。{where}'
                            f'バックアップ履歴から復元できる場合があります。原因: {cause}', path, kept)


_PROFILE_FIELDS = ('warnings', 'language', 'translations', 'language_states',
                   'active_mods', 'active_mods_known', 'diagnostics')


def _version_key(version: str) -> tuple[int, int]:
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+', version):
        raise ValueError('Invalid game version')
    return tuple(int(part) for part in version.split('.'))


def english_comment(english: str) -> str:
    """The ' EN: source ' comment RimWorld's own translation cleaner writes before each entry."""
    text = english.replace("\r\n", "\n").replace("\n", "\\n")
    # '--' may not appear inside an XML comment, nor may it end with '-'.
    while "--" in text:
        text = text.replace("--", "- -")
    return f" EN: {text} "


def xml_bytes(root: ET.Element) -> bytes:
    for node in root.iter():
        for text in [node.text or "", *node.attrib.values()]:
            if INVALID_XML.search(text):
                raise ValueError("Invalid XML character")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class ExportBlocked(ValueError):
    """Formal output refused because entries are unsafe or need re-review (Q19 C).

    ``entries`` lists every blocking row as (language, entry id, reason), so the
    editor can list and jump to them instead of stopping at the first one.
    """
    def __init__(self, message: str, entries: list[tuple[str, str, str]]):
        super().__init__(message)
        self.entries = entries


EMPTY_OUTPUT_NOTICE = '出力できる訳が1件もないため、翻訳MODには About だけが入っています（ゲームでは何も変わりません）。'


def source_folder_problem(source: Path | str) -> str:
    """Why ``source`` is not a MOD folder (no About/About.xml), or '' when it is one.

    A folder that merely contains MODs is named so the caller can suggest the right one.
    """
    source = Path(source)
    about = source / 'About' / 'About.xml'
    if about.is_file():
        return ''
    if not source.is_dir():
        return f'フォルダーがありません: {source}。About/About.xml がある MOD のフォルダーを選んでください。'
    inner = sorted(child.name for child in source.iterdir()
                   if child.is_dir() and (child / 'About' / 'About.xml').is_file())[:5]
    hint = f' 中にある MOD: {", ".join(inner)}。どれか1つを選んでください。' if inner else ''
    return f'MOD のフォルダーではありません（About/About.xml がありません）: {source}。{hint}'.rstrip()


def export_mod(project: Project, target: Path, *, test_only: bool = False) -> list[str]:
    """Export a single-version project.

    Formal output (default) refuses with ``ExportBlocked`` while any row is unsafe or
    needs re-review (Q19 C). ``test_only=True`` writes a clearly marked test package
    that leaves those rows out and reports each one in the returned warnings.
    A project with no entries, or with nothing translated, is refused rather than
    producing an empty MOD.
    """
    if project.version_profiles:
        raise ValueError('Version-profile projects require export_versions (formal multi-version output) or export_versions_test')
    if not project.entries:
        problem = source_folder_problem(project.source)
        raise ValueError('翻訳する項目が0件のため、翻訳MODを作りませんでした。'
                         + (problem or '元 MOD に翻訳できる文章が見つかりませんでした。'))
    payloads, warnings = _export_payloads(project, test_only=test_only)
    if not any(relative.startswith('Languages/') for relative in payloads):
        # Saving regenerates output, so an untranslated project is not an error; say so plainly instead.
        warnings.insert(0, EMPTY_OUTPUT_NOTICE)
    _publish_export(project, target, payloads, single_test=test_only)
    return warnings


_WORKSHOP_ID = re.compile(r"[1-9][0-9]{5,15}")


def source_workshop_id(source: Path) -> str:
    """The source MOD's Steam Workshop id: About/PublishedFileId.txt, else the folder name of
    a Workshop download (``.../workshop/content/294100/<id>``). '' when unknown."""
    workshop_file = source / "About" / "PublishedFileId.txt"
    if workshop_file.is_file() and not workshop_file.is_symlink() and workshop_file.stat().st_size < 1024:
        text = workshop_file.read_text(encoding="utf-8", errors="replace").strip()
        if _WORKSHOP_ID.fullmatch(text):
            return text
    parts = [part.casefold() for part in source.parts]
    if (len(parts) >= 4 and parts[-2] == "294100" and parts[-3] == "content" and parts[-4] == "workshop"
            and _WORKSHOP_ID.fullmatch(source.name)):
        return source.name
    return ""


def source_download_url(source: Path) -> str:
    """An http(s) <url> from the source MOD's About.xml, or ''."""
    about = source / "About" / "About.xml"
    if not about.is_file():
        return ""
    try:
        url = (safe_xml(about).findtext("url") or "").strip()
    except (ValueError, OSError, ET.ParseError):
        return ""
    return url if re.fullmatch(r"https?://[^\s<>\"]{3,500}", url) else ""


def _export_payloads(project: Project, *, test_only: bool = False) -> tuple[dict[str, bytes], list[str]]:
    from .qa import qa_entry
    validate_languages(project.languages)
    project.stash_current_language()
    if not PACKAGE.fullmatch(project.package_id):
        raise ValueError("Invalid translation package ID")
    about = ET.Element("ModMetaData")
    if project.languages == ['Japanese']:
        friendly_suffix = ' 日本語翻訳'
    elif len(project.languages) == 1:
        friendly_suffix = f' {project.languages[0]} 翻訳'
    else:
        friendly_suffix = ' 多言語翻訳'
    description = project.metadata.get('description') or 'Community translations. Requires the original mod. Untranslated entries fall back to source language.'
    if project.metadata.get('license'):
        description += '\n\nTranslation license: '+project.metadata['license']
    disclaimer = 'Unofficial community translation. Not affiliated with or endorsed by Ludeon Studios or the original mod author.'
    if disclaimer not in description:
        description += '\n\n' + disclaimer
    for tag, value in (("name", project.metadata.get('name') or project.name + friendly_suffix), ("author", (project.metadata.get('author') or '').strip()), ("packageId", project.package_id), ("description", description)):
        # An empty translator name is left out; the game then shows its own "Anonymous" instead of a made-up one.
        if tag == 'author' and not value:
            continue
        ET.SubElement(about, tag).text = value
    versions = ET.SubElement(about, "supportedVersions")
    # Keys come from one selected version branch, so do not advertise other
    # versions merely because the original MOD supports them.
    for version in [project.game_version]:
        if not re.fullmatch(r"\d+\.\d+", version):
            raise ValueError("Invalid game version")
        ET.SubElement(versions, "li").text = version
    if project.original_package_id:
        if not PACKAGE.fullmatch(project.original_package_id):
            raise ValueError("Invalid dependency package ID")
        item = ET.SubElement(ET.SubElement(about, "modDependencies"), "li")
        ET.SubElement(item, "packageId").text = project.original_package_id
        ET.SubElement(item, "displayName").text = project.name
        # RimWorld warns about a dependency without <downloadUrl> or <steamWorkshopUrl>.
        workshop_id = source_workshop_id(Path(project.source))
        if workshop_id:
            ET.SubElement(item, "steamWorkshopUrl").text = (
                "https://steamcommunity.com/sharedfiles/filedetails/?id=" + workshop_id
            )
        else:
            download = source_download_url(Path(project.source))
            if download:
                ET.SubElement(item, "downloadUrl").text = download
        ET.SubElement(ET.SubElement(about, "loadAfter"), "li").text = project.original_package_id
        ET.SubElement(ET.SubElement(about, "forceLoadAfter"), "li").text = project.original_package_id
    payloads = {"About/About.xml": xml_bytes(about)}
    badge_languages = project.languages
    payloads["About/Preview.png"] = make_preview_bytes(Path(project.source), project.name, badge_languages,use_source=project.metadata.get('use_source_preview','false')=='true')
    warnings = []
    blocking = []
    for language in project.languages:
        translated = project.translations.get(language, {})
        groups = {}
        seen = set()
        for entry in project.entries:
            if entry.kind == 'Strings':
                continue
            translation = translated.get(entry.id, '')
            if not translation.strip() or entry.stale or entry.blocked or entry.excluded:
                continue
            if entry.kind not in {"Keyed", "DefInjected"} or not KEY.fullmatch(entry.group) or not KEY.fullmatch(entry.key):
                raise ValueError("Unsafe XML entry")
            ident = (entry.kind, entry.group, entry.key)
            if ident in seen:
                raise ValueError("Duplicate export key")
            seen.add(ident)
            issues = qa_entry(entry,translation,glossary=project.glossary)
            errors = [issue.message for issue in issues if issue.severity == 'error']
            if INVALID_XML.search(translation):
                errors.append('XMLで使用できない文字が含まれています')
            if errors:
                if test_only:
                    warnings.append(f"危険な訳を試験出力から除外: {language} / {entry.key}: {'; '.join(errors)}")
                    continue
                # Report every blocking entry in one pass instead of stopping at the first.
                blocking.append((language, entry.id, f"{language} / {entry.key}: {'; '.join(errors)}"))
                continue
            warnings.extend(f'{language} / {entry.key}: {issue.message}' for issue in issues if issue.severity != 'error')
            state = project.language_states.get(language,{}).get(entry.id,{})
            if not test_only and state.get('changed', entry.changed):
                blocking.append((language, entry.id, f'Source changed; review required: {language} / {entry.key}'))
                continue
            if state.get('review',entry.review) or state.get('changed',entry.changed):
                warnings.append(f"Review needed: {language} / {entry.key}")
            root = groups.setdefault((entry.kind, entry.group), ET.Element("LanguageData"))
            if entry.english.strip():
                root.append(ET.Comment(english_comment(entry.english)))
            ET.SubElement(root, entry.key).text = translation
        for (kind, group), root in groups.items():
            relative = f"Languages/{language}/DefInjected/{group}/Translations.xml" if kind == 'DefInjected' else f"Languages/{language}/Keyed/{group}.xml"
            payloads[relative] = xml_bytes(root)
        string_payloads, string_warnings = _export_string_payloads(project, language, translated, test_only=test_only)
        payloads.update(string_payloads)
        warnings.extend(string_warnings)
    if blocking:
        shown = [message for _, _, message in blocking[:30]]
        if len(blocking) > len(shown):
            shown.append(f'...他 {len(blocking) - len(shown)} 件')
        raise ExportBlocked('\n'.join(shown), blocking)
    return payloads, warnings


def _export_string_payloads(project: Project, language: str, translated: dict[str, str],
                            *, test_only: bool) -> tuple[dict[str, bytes], list[str]]:
    from .qa import qa_entry
    from .string_resources import serialize_string_entries, validate_string_entry
    groups = {}
    for entry in project.entries:
        if entry.kind == 'Strings' and not entry.stale:
            if (not validate_string_entry(entry.group, entry.key)
                    or entry.id != f'Strings:{entry.group}:{entry.key}'):
                raise ValueError('Unsafe Strings entry')
            groups.setdefault(entry.group, []).append(entry)
    payloads, warnings = {}, []
    for group, entries in groups.items():
        if not any(translated.get(entry.id, '').strip() for entry in entries):
            continue
        try:
            if any(entry.blocked or entry.excluded for entry in entries):
                raise ValueError('Strings file contains blocked or excluded entries')
            # Partial files change the positional resource layout. The pending
            # untranslated fallback policy must not be inferred by this writer.
            if any(not translated.get(entry.id, '').strip() for entry in entries):
                raise ValueError('Incomplete Strings file; untranslated fallback policy is undecided')
            for entry in entries:
                text = translated[entry.id]
                issues = qa_entry(entry, text, glossary=project.glossary)
                errors = [issue.message for issue in issues if issue.severity == 'error']
                if errors:
                    raise ValueError('; '.join(errors))
                state = project.language_states.get(language, {}).get(entry.id, {})
                if not test_only and state.get('changed', entry.changed):
                    raise ValueError('Source changed; review required')
                if state.get('review', entry.review) or state.get('changed', entry.changed):
                    warnings.append(f'Review needed: {language} / Strings/{group} / {entry.key}')
                warnings.extend(f'{language} / Strings/{group} / {entry.key}: {issue.message}'
                                for issue in issues if issue.severity != 'error')
            payloads[f'Languages/{language}/Strings/{group}'] = serialize_string_entries(entries, translated)
        except ValueError as exc:
            if not test_only:
                raise ValueError(f'{language} / Strings/{group}: {exc}') from exc
            warnings.append(f'Stringsファイルを試験出力から除外: {language} / {group}: {exc}')
    return payloads, warnings


@dataclass
class VersionExportResult:
    """Outcome of a formal multi-version export (Q17 A: finished versions first)."""
    exported: list[str]
    held: dict[str, str]
    warnings: list[str]


def _ready_versions(project: Project, versions: list[str] | None):
    """Per-version payloads of the declared versions that may be formally exported, and why the others may not."""
    declared = sorted(set(project.versions), key=_version_key)
    if not declared:
        raise ValueError('No declared versions to export')
    requested = declared if versions is None else sorted(set(versions), key=_version_key)
    unknown = [version for version in requested if version not in declared]
    if unknown:
        raise ValueError('Not declared by the source MOD: ' + ', '.join(unknown))
    project._stash_version()
    held = {version: '出力対象に指定されていません' for version in declared if version not in requested}
    ready = {}
    for version in requested:
        if _version_key(version) == (1, 0):
            held[version] = 'RimWorld 1.0のロード規則は未検証です'
            continue
        if not project.version_profiles.get(version, {}).get('coverage', {}).get('extracted'):
            held[version] = '未抽出です'
            continue
        try:
            branch, branch_warnings = _export_payloads(project._version_view(version), test_only=False)
        except ValueError as exc:
            held[version] = str(exc)
            continue
        if not any(relative.startswith('Languages/') for relative in branch):
            held[version] = '出力できる訳が1件もありません'
            continue
        ready[version] = (branch, branch_warnings)
    if not ready:
        raise ValueError('No version is ready for formal output:\n'
                         + '\n'.join(f'{version}: {reason}' for version, reason in held.items()))
    return ready, held


def export_versions(project: Project, target: Path, versions: list[str] | None = None) -> VersionExportResult:
    """Formally export only the declared versions that are ready (Q17 A, Q19 C).

    A version is held back, with a recorded reason, when it is unscanned, is
    RimWorld 1.0 (load rules unverified), has no translations, or still has any
    dangerous/unreviewed entry. Held versions are never advertised in
    About.xml/LoadFolders.xml and never receive output. Other versions are
    still exported. Untranslated keys are omitted, never filled in.
    ``versions`` narrows the candidate set; omitted versions are held.
    """
    ready, held = _ready_versions(project, versions)
    exported = list(ready)
    payloads = {}
    warnings = [f'保留: {version} は正式出力から除外しました（{reason.splitlines()[0]}）'
                for version, reason in sorted(held.items(), key=lambda item: _version_key(item[0]))]
    first = ready[exported[0]][0]
    about = ET.fromstring(first['About/About.xml'])
    declared_node = about.find('supportedVersions')
    declared_node.clear()
    folders = ET.Element('loadFolders')
    for version in exported:
        branch, branch_warnings = ready[version]
        ET.SubElement(declared_node, 'li').text = version
        warnings.extend(f'{version} / {warning}' for warning in branch_warnings)
        for relative, data in branch.items():
            if relative.startswith('Languages/'):
                payloads[f'{version}/{relative}'] = data
        ET.SubElement(ET.SubElement(folders, f'v{version}'), 'li').text = version
    payloads['About/About.xml'] = xml_bytes(about)
    payloads['About/Preview.png'] = first['About/Preview.png']
    payloads['LoadFolders.xml'] = xml_bytes(folders)
    _publish_export(project, target, payloads, formal_versions=(exported, held))
    return VersionExportResult(exported, held, warnings)


def export_shared(project: Project, target: Path, versions: list[str] | None = None) -> VersionExportResult:
    """Formally export one translation set that every ready version reads.

    The ready versions are decided exactly as in ``export_versions``. Their per-version output is merged into the
    root ``Languages/`` folder: the keys are the union over the versions, and where a key carries different texts the
    newest version's text is used and a notice is recorded. No version folders and no LoadFolders.xml are written, so
    the game loads the root for every version. A key the running game does not know is ignored by the game; an item
    keyed by index in one version and by handle in another keeps both keys (the game applies the handle key where it
    knows handles and the index key otherwise). Held versions contribute nothing and are not advertised.
    """
    ready, held = _ready_versions(project, versions)
    exported = list(ready)
    warnings = [f'保留: {version} は正式出力から除外しました（{reason.splitlines()[0]}）'
                for version, reason in sorted(held.items(), key=lambda item: _version_key(item[0]))]
    merged: dict[str, dict[str, tuple]] = {}
    strings: dict[str, bytes] = {}
    for version in exported:
        branch, branch_warnings = ready[version]
        warnings.extend(f'{version} / {warning}' for warning in branch_warnings)
        for relative, data in branch.items():
            if not relative.startswith('Languages/'):
                continue
            if '/Strings/' in relative:
                strings[relative] = data      # positional resource files cannot be merged; the newest version wins
                continue
            table = merged.setdefault(relative, {})
            comment = None
            for node in ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))):
                if node.tag is ET.Comment:
                    comment = node.text
                    continue
                previous = table.get(node.tag)
                if previous is not None and previous[0] != node.text:
                    warnings.append(f'版により訳が違います: {node.tag}（{previous[2]}: 「{previous[0]}」→ {version}: 「{node.text}」を採用）')
                table[node.tag] = (node.text, comment, version)
                comment = None
    first = ready[exported[0]][0]
    about = ET.fromstring(first['About/About.xml'])
    declared_node = about.find('supportedVersions')
    declared_node.clear()
    for version in exported:
        ET.SubElement(declared_node, 'li').text = version
    payloads = {'About/About.xml': xml_bytes(about), 'About/Preview.png': first['About/Preview.png'], **strings}
    for relative, table in merged.items():
        root = ET.Element('LanguageData')
        for key, (text, comment, _) in table.items():
            if comment is not None:
                root.append(ET.Comment(comment))
            ET.SubElement(root, key).text = text
        payloads[relative] = xml_bytes(root)
    _publish_export(project, target, payloads, formal_versions=(exported, held), shared=True)
    # A per-version layout published earlier leaves empty version folders; the game loads a folder named after its
    # version when there is no LoadFolders.xml, so do not leave them behind.
    for folder in sorted((p for p in Path(target).rglob('*') if p.is_dir() and not p.is_symlink()),
                         key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    return VersionExportResult(exported, held, warnings)


def export_versions_test(project: Project, target: Path) -> list[str]:
    """Export explicitly unverified, independent version trees for local testing.

    This does not decide the pending formal-release policy for incomplete versions.
    As with the legacy exporter, empty translations are omitted, never filled in.
    Like the formal exporter, RimWorld 1.0 (load rules unverified) and unscanned
    versions are held with a notice, recorded as ``held_versions`` in the marker,
    and the other versions are still exported; nothing exportable is an error.
    """
    declared = sorted(set(project.versions), key=_version_key)
    held = {}
    for version in declared:
        if _version_key(version) == (1, 0):
            held[version] = 'RimWorld 1.0のロード規則は未検証です'
        elif not project.version_profiles.get(version, {}).get('coverage', {}).get('extracted'):
            held[version] = '未抽出です'
    versions = [version for version in declared if version not in held]
    if not versions:
        raise ValueError('No version can be test-exported:\n'
                         + '\n'.join(f'{version}: {reason}' for version, reason in held.items()))
    project._stash_version()
    payloads = {}
    warnings = ['試験出力: 全バージョンの型情報・実機動作は未検証です。正式出力ではありません。']
    warnings.extend(f'保留: {version} は試験出力から除外しました（{reason}）' for version, reason in held.items())
    about = None
    folders = ET.Element('loadFolders')
    # Build and validate every payload before touching the destination.
    for version in versions:
        # Copy only this profile, rather than every version once per branch.
        view = project._version_view(version)
        branch, branch_warnings = _export_payloads(view, test_only=True)
        warnings.extend(f'{version} / {warning}' for warning in branch_warnings)
        if about is None:
            about = ET.fromstring(branch['About/About.xml'])
            declared = about.find('supportedVersions')
            declared.clear()
            for declared_version in versions:
                ET.SubElement(declared, 'li').text = declared_version
            payloads['About/About.xml'] = xml_bytes(about)
            payloads['About/Preview.png'] = branch['About/Preview.png']
        for relative, data in branch.items():
            if relative.startswith('Languages/'):
                payloads[f'{version}/{relative}'] = data
        ET.SubElement(ET.SubElement(folders, f'v{version}'), 'li').text = version
    payloads['LoadFolders.xml'] = xml_bytes(folders)
    _publish_export(project, target, payloads, test_versions=versions, test_held=held)
    return warnings


def _publish_export(project: Project, target: Path, payloads: dict[str, bytes],
                    test_versions: list[str] | None = None,
                    formal_versions: tuple[list[str], dict[str, str]] | None = None, shared: bool = False,
                    single_test: bool = False, test_held: dict[str, str] | None = None) -> None:
    target = writable_destination(target, Path(project.source))
    marker = target / ".rimworld-translator.json"
    old = []
    if target.exists() and any(target.iterdir()):
        if not marker.is_file() or marker.is_symlink():
            raise ValueError("Export directory is not owned by this editor; choose an empty folder")
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        if metadata.get("package_id") != project.package_id:
            raise ValueError("Export belongs to a different project")
        old = metadata.get("files", [])
        if not isinstance(old, list) or not all(isinstance(x, str) for x in old):
            raise ValueError("Invalid export manifest")
    for relative in [*payloads, *old, ".rimworld-translator.json"]:
        if not isinstance(relative, str):
            raise ValueError("Invalid manifest")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or not (relative == ".rimworld-translator.json" or is_export_content_path(relative)):
            raise ValueError("Unsafe export manifest path")
        destination = target / rel
        if destination.exists() and not destination.is_file():
            raise ValueError("Export file conflicts with an existing path")
        if relative in payloads and relative not in old and destination.exists():
            raise ValueError("Export would overwrite a file not owned by this editor")
        for part in (destination, *destination.parents):
            if part.is_symlink():
                raise ValueError("Export contains a symbolic link")
            if part != destination and part.exists() and not part.is_dir():
                raise ValueError("Export parent conflicts with an existing path")
    _validate_export_case_aliases(target, [*payloads, *old, '.rimworld-translator.json'])
    marker_data = (json.dumps({"package_id": project.package_id, "files": sorted(payloads),
                               **({"test_only": True} if single_test else {}),
                               **({"test_only": True, "unverified_versions": test_versions} if test_versions is not None else {}),
                               **({"held_versions": test_held} if test_held else {}),
                               **({"formal": True, "exported_versions": formal_versions[0], "held_versions": formal_versions[1]} if formal_versions is not None else {}),
                               **({"shared": True} if shared else {})}, indent=2) + "\n").encode()
    desired = {**payloads, '.rimworld-translator.json': marker_data}
    writes = {relative: data for relative, data in desired.items()
              if not (target / relative).exists() or (target / relative).read_bytes() != data}
    removals = [relative for relative in dict.fromkeys(old)
                if relative not in desired and (target / relative).exists()]
    if not writes and not removals:
        return
    _publish_transaction(target, writes, removals)


def _validate_export_case_aliases(target: Path, relatives: list[str]) -> None:
    """Reject portable path aliases before staging or removing any output."""
    from .string_resources import WINDOWS_DEVICE
    spellings = {}
    children = {}
    for relative in relatives:
        parent = target
        for part in Path(relative).parts:
            if (part.endswith((' ', '.'))
                    or WINDOWS_DEVICE.fullmatch(part.split('.', 1)[0].rstrip(' '))):
                raise ValueError('Export path is not portable across filesystems')
            destination = parent / part
            folded = str(destination).casefold()
            previous = spellings.setdefault(folded, str(destination))
            if previous != str(destination):
                raise ValueError('Export paths conflict on a case-insensitive filesystem')
            if parent not in children:
                children[parent] = ({child.name for child in parent.iterdir()}
                                    if parent.is_dir() else set())
            if any(name != part and name.casefold() == part.casefold()
                   for name in children[parent]):
                raise ValueError('Export path conflicts with an existing case-insensitive alias')
            parent = destination


def is_export_content_path(relative: str) -> bool:
    """True for the relative paths an exported translation MOD may contain (About/, Languages/, LoadFolders.xml)."""
    return bool(relative in ("About/About.xml", "About/Preview.png", "LoadFolders.xml") or _safe_string_export_path(relative)
                or re.fullmatch(r"(?:\d+\.\d+/)?Languages/[A-Za-z][A-Za-z0-9]*/(?:DefInjected/[A-Za-z_][A-Za-z0-9_.]*/Translations|DefInjected/[A-Za-z_][A-Za-z0-9_.]*|Keyed/[A-Za-z_][A-Za-z0-9_.]*)\.xml", relative))


def _safe_string_export_path(relative: str) -> bool:
    from .string_resources import validate_string_entry
    match = re.fullmatch(r'(?:\d+\.\d+/)?Languages/([A-Za-z][A-Za-z0-9]*)/Strings/(.+)', relative)
    if match is None:
        return False
    validate_language(match.group(1))
    return validate_string_entry(match.group(2), 'line_0')


def _publish_transaction(target: Path, writes: dict[str, bytes], removals: list[str]) -> None:
    """Stage all bytes and recover from caught publication errors.

    This is exception recovery, not atomic visibility across files or durable
    recovery from process termination. Keep backups if restoration itself fails.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.rimworld-export-', dir=target.parent))
    marker_name = '.rimworld-translator.json'
    changed = [relative for relative in writes if relative != marker_name]
    changed.extend(removals)
    if marker_name in writes:
        changed.append(marker_name)
    backups = {}
    applied = []
    created_directories = set()
    retain_backups = False
    try:
        # Every write and backup is completed before modifying the output tree.
        for number, relative in enumerate(changed):
            destination = target / relative
            if destination.exists():
                backup = staging / 'before' / str(number)
                atomic_write(backup, destination.read_bytes())
                backups[relative] = backup
            if relative in writes:
                atomic_write(staging / 'after' / relative, writes[relative])
        recovery = {'target': str(target), 'writes': list(writes), 'removals': removals,
                    'backups': {relative: path.relative_to(staging).as_posix()
                                for relative, path in backups.items()}}
        atomic_write(staging / 'recovery.json',
                     (json.dumps(recovery, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        try:
            for relative in changed:
                destination = target / relative
                if relative in writes:
                    for parent in destination.parents:
                        if parent.exists():
                            break
                        created_directories.add(parent)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging / 'after' / relative, destination)
                else:
                    destination.unlink()
                applied.append(relative)
        except BaseException as publication_error:
            # An interrupt or unexpected error during recovery must never
            # make the outer finally discard the remaining original bytes.
            retain_backups = True
            recovery_errors = []
            for relative in reversed(applied):
                try:
                    if relative in backups:
                        os.replace(backups[relative], target / relative)
                    else:
                        (target / relative).unlink(missing_ok=True)
                except OSError as exc:
                    recovery_errors.append(f'{relative}: {exc}')
            for directory in sorted(created_directories, key=lambda path: len(path.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass  # Preserve directories containing unrelated or unrecovered files.
            if recovery_errors:
                raise OSError(f'Export recovery incomplete; backups retained at {staging}: '
                              + '; '.join(recovery_errors)) from publication_error
            retain_backups = False
            raise
    finally:
        if not retain_backups:
            shutil.rmtree(staging, ignore_errors=True)
