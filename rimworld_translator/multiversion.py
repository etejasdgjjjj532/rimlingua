"""Sequential extraction of one MOD's declared versions, without game execution."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from collections.abc import Mapping

from .core import PACKAGE, Entry, Project, Scan, _version_key, placeholder_warning, safe_xml, scan_mod, writable_destination
from .extraction import ScanCancelled, version_tuple

if TYPE_CHECKING:
    from .dependency_profiles import DependencyPlan


@dataclass
class VersionScans:
    declared_versions: list[str]
    scans: dict[str, Scan] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


def scan_declared_versions(source: Path, *, contexts: Mapping[str, dict] | None = None,
                           progress=None, cancel=None, diagnostic_limit=1500) -> VersionScans:
    """Scan only About.xml declarations, retaining failures per version.

    Contexts maps a declared version to scan_mod options: active_mods, assumed_active, schema,
    context_sources and cache_path. No game's schema or dependency profile is
    implicitly reused for another version. Missing context uses generic static
    rules and does not establish source completeness or runtime verification.
    Progress receives (version, completed_files, total_files). Cancellation
    propagates, so callers can preserve an existing project unchanged.
    """
    source, versions, contexts = _validated_inputs(source, contexts)
    result = VersionScans(versions)
    for version in versions:
        if cancel is not None and cancel():
            raise ScanCancelled('Scan cancelled; existing project is unchanged')
        callback = None
        if progress is not None:
            callback = lambda done, total, entries, relative, current=version: progress(current, done, total)
        try:
            result.scans[version] = scan_mod(
                source, game_version=version, progress=callback, cancel=cancel,
                diagnostic_limit=diagnostic_limit, **contexts.get(version, {}))
        except ScanCancelled:
            raise
        except (OSError, ValueError, sqlite3.Error) as exc:
            result.failures[version] = f'{type(exc).__name__}: {exc}'
    return result


def declared_versions(source: Path) -> list[str]:
    """The versions About.xml declares, in numeric order."""
    return _validated_inputs(source, None)[1]


def _validated_inputs(source, contexts):
    source = Path(source)
    if source.is_symlink():
        raise ValueError('Source must not be a symbolic link')
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Source must be a directory')
    root = safe_xml(source / 'About/About.xml')
    versions = [(node.text or '').strip() for node in root.findall('supportedVersions/li')]
    if not versions or any(not re.fullmatch(r'\d+\.\d+', version) for version in versions):
        raise ValueError('About.xml must declare valid supportedVersions')
    versions = sorted(set(versions), key=version_tuple)
    if contexts is None:
        contexts = {}
    if not isinstance(contexts, Mapping) or any(version not in versions for version in contexts):
        raise ValueError('Extraction contexts must refer to declared versions')
    allowed = {'active_mods', 'assumed_active', 'schema', 'context_sources', 'cache_path'}
    for options in contexts.values():
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('Unsupported version extraction context')
        if options.get('cache_path') is not None:
            writable_destination(Path(options['cache_path']), source)
    return source, versions, contexts


@dataclass
class VersionScenarioScans:
    declared_versions: list[str]
    plans: dict[str, DependencyPlan] = field(default_factory=dict)
    scans: dict[str, dict[str, Scan]] = field(default_factory=dict)
    failures: dict[str, dict[str, str]] = field(default_factory=dict)


def scan_declared_scenarios(source: Path, *, contexts: Mapping[str, dict] | None = None,
                            max_scenarios: int = 16, progress=None, cancel=None,
                            diagnostic_limit=1500) -> VersionScenarioScans:
    """Extract bounded dependency scenarios sequentially for each declared version.

    Results remain separate: a conditional replacement can change the same key's
    source text, so an unconditional union is unsafe. Callers select one scenario
    per version explicitly before creating a Project. Plans retain unresolved
    conditions and unexamined scenarios; success never establishes completeness.
    Explicit active_mods are fixed active context, not discovered dependencies.
    Scenario-count stats are int for ordinary counts and exact exponent strings
    for huge counts, keeping Project JSON writable without relaxing integer limits.
    """
    from .dependency_profiles import plan_dependency_scenarios

    source, versions, contexts = _validated_inputs(source, contexts)
    if type(max_scenarios) is not int or not 1 <= max_scenarios <= 256:
        raise ValueError('max_scenarios must be an integer between 1 and 256')
    result = VersionScenarioScans(versions)
    for version in versions:
        if cancel is not None and cancel():
            raise ScanCancelled('Scan cancelled; existing project is unchanged')
        options = dict(contexts.get(version, {}))
        fixed_active = options.pop('active_mods', None) or ()
        try:
            # Planning and every scenario need the same metadata, including
            # when the caller supplied a one-shot iterator of source folders.
            context_sources = options.get('context_sources', ())
            if isinstance(context_sources, (str, bytes, Path)):
                raise ValueError('context_sources must be an iterable of MOD folders')
            context_sources = tuple(context_sources)
            if 'context_sources' in options:
                options['context_sources'] = context_sources
            plan = plan_dependency_scenarios(source, version, max_scenarios=max_scenarios,
                                             base_active_mods=fixed_active,
                                             context_sources=context_sources)
        except (OSError, ValueError, ET.ParseError) as exc:
            result.failures[version] = {'<planning>': f'{type(exc).__name__}: {exc}'}
            continue
        result.plans[version] = plan
        for scenario in plan.scenarios:
            if cancel is not None and cancel():
                raise ScanCancelled('Scan cancelled; existing project is unchanged')
            callback = None
            if progress is not None:
                callback = lambda done, total, entries, relative, v=version, n=scenario.name: progress(v, n, done, total)
            try:
                scenario_options = dict(options)
                if 'context_sources' in scenario_options:
                    active_sources = []
                    for dependency in scenario_options['context_sources']:
                        dependency = Path(dependency)
                        metadata = safe_xml(dependency / 'About/About.xml')
                        package = (metadata.findtext('packageId') or '').strip()
                        if not PACKAGE.fullmatch(package):
                            raise ValueError(f'Dependency source has no valid package ID: {dependency}')
                        if package.casefold() in scenario.active_mods:
                            active_sources.append(dependency)
                    scenario_options['context_sources'] = active_sources
                scan = scan_mod(source, game_version=version,
                                active_mods=sorted(scenario.active_mods), progress=callback,
                                cancel=cancel, diagnostic_limit=diagnostic_limit, **scenario_options)
                # 2**2048 has 617 decimal digits, below even Python's minimum
                # configurable 640-digit limit. Keep larger JSON counts symbolic.
                integer_counts = len(plan.optional_mods) <= 2048
                total_count = (plan.total_scenarios if integer_counts
                               else f'2^{len(plan.optional_mods)}')
                remaining_count = (plan.unexamined_scenarios if integer_counts
                                   else f'2^{len(plan.optional_mods)} - {len(plan.scenarios)}')
                scan.stats.update(dependency_scenario=scenario.name,
                                  dependency_scenarios_unexamined=remaining_count,
                                  dependency_scenarios_total=total_count)
                for diagnostic in plan.diagnostics:
                    scan.warning_count += 1
                    if diagnostic_limit is None or len(scan.diagnostics) < diagnostic_limit:
                        scan.warnings.append(diagnostic.message)
                        scan.diagnostics.append({
                            'code': diagnostic.code, 'message': diagnostic.message,
                            'source_file': diagnostic.source, 'entry_id': '',
                            'suggestion': 'Verify dependency context before treating extraction as complete.'})
                # Keep planning evidence even when the display diagnostic limit
                # is zero; profiles persist stats alongside the selected scan.
                scan.stats['dependency_plan_diagnostics'] = [
                    {'code': d.code, 'message': d.message, 'source_file': d.source}
                    for d in plan.diagnostics]
                result.scans.setdefault(version, {})[scenario.name] = scan
            except ScanCancelled:
                raise
            except (OSError, ValueError, sqlite3.Error, ET.ParseError) as exc:
                result.failures.setdefault(version, {})[scenario.name] = f'{type(exc).__name__}: {exc}'
    return result


# --- Carrying work between versions of one project ------------------------------------------------------------

@dataclass(frozen=True)
class CarryItem:
    entry_id: str
    before: str
    after: str
    review: bool          # the English differs between the versions, so the copy needs a second look
    english_differs: bool


@dataclass
class CarryPreview:
    source: str
    target: str
    language: str
    items: list[CarryItem] = field(default_factory=list)
    # reason -> number of rows left alone: missing (key absent in the target), english_differs,
    # has_translation, blocked (stale / blocked / excluded / changed target), unsafe (source text breaks placeholders)
    skipped: dict[str, int] = field(default_factory=lambda: {key: 0 for key in (
        'missing', 'english_differs', 'has_translation', 'blocked', 'unsafe')})


def _versions(project: Project, source: str, target: str) -> tuple[Project, Project]:
    _version_key(source), _version_key(target)
    if source == target:
        raise ValueError('Carry between two different versions')
    for version in (source, target):
        if version not in project.version_profiles and version != project.game_version:
            raise ValueError(f'Version has not been scanned: {version}')
    project._stash_version()
    return project._version_view(source), project._version_view(target)


def preview_carry(project: Project, source: str, target: str, language: str | None = None, overwrite: bool = False,
                  include_different_english: bool = False) -> CarryPreview:
    """Which translations of ``source`` could be copied to the same keys of ``target``; nothing is changed.

    A row is copied only when its key exists in both versions, the English is identical (or
    ``include_different_english``, in which case the copy is flagged for review), the target row has no
    translation (or ``overwrite``), and the target row is not stale, blocked, excluded or awaiting re-review.
    Source translations that break placeholders are never carried.
    """
    language = language or project.language
    source_view, target_view = _versions(project, source, target)
    targets = target_view.entry_index()
    preview = CarryPreview(source, target, language)
    for entry in source_view.entries:
        text = source_view.get_translation(entry.id, language)
        if not text.strip() or entry.stale or entry.blocked or entry.excluded:
            continue
        other = targets.get(entry.id)
        if other is None:
            preview.skipped['missing'] += 1
            continue
        if other.stale or other.blocked or other.excluded or other.changed:
            preview.skipped['blocked'] += 1
            continue
        differs = other.english != entry.english
        if differs and not include_different_english:
            preview.skipped['english_differs'] += 1
            continue
        probe = copy.copy(other)
        probe.japanese = text
        if placeholder_warning(probe):
            preview.skipped['unsafe'] += 1
            continue
        before = target_view.get_translation(entry.id, language)
        if before == text:
            continue
        if before.strip() and not overwrite:
            preview.skipped['has_translation'] += 1
            continue
        preview.items.append(CarryItem(entry.id, before, text, differs, differs))
    return preview


def apply_carry(project: Project, preview: CarryPreview) -> int:
    """Write a ``CarryPreview`` into its target version (approval is never carried); returns rows written.

    The whole selection is validated first, so a stale preview changes nothing.
    """
    source_view, target_view = _versions(project, preview.source, preview.target)
    index = target_view.entry_index()
    for item in preview.items:
        if item.entry_id not in index or target_view.get_translation(item.entry_id, preview.language) != item.before:
            raise ValueError(f'プレビュー後に訳が変わりました。もう一度プレビューしてください: {item.entry_id}')
    live = preview.target == project.game_version
    view = project if live else target_view
    if not live:
        view.version_profiles[preview.target] = copy.deepcopy(project.version_profiles[preview.target])
    for item in preview.items:
        view.set_translation(item.entry_id, item.after, preview.language)
        if item.review:
            state = view.language_states.setdefault(preview.language, {}).setdefault(item.entry_id, {})
            state.update(review=True, reviewed=False, approved=False)
            if preview.language == view.language:
                view.entry_index()[item.entry_id].review = True
    if not live:
        view._stash_version()
        project.version_profiles[preview.target] = view.version_profiles[preview.target]
    return len(preview.items)


@dataclass(frozen=True)
class RowChange:
    entry_id: str
    english_a: str = ''
    english_b: str = ''
    translation_a: str = ''
    translation_b: str = ''


@dataclass
class VersionDiff:
    version_a: str
    version_b: str
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)
    english_changed: list[RowChange] = field(default_factory=list)
    translation_differs: list[RowChange] = field(default_factory=list)
    same: int = 0

    def summary(self) -> str:
        return (f'{self.version_a} だけ {len(self.only_a)} 件 / {self.version_b} だけ {len(self.only_b)} 件 / '
                f'英文が違う {len(self.english_changed)} 件 / 訳が違う {len(self.translation_differs)} 件 / 同じ {self.same} 件')


def version_diff(project: Project, version_a: str, version_b: str, language: str | None = None) -> VersionDiff:
    """Compare two scanned versions row by row: keys only in one, changed English, differing translations."""
    language = language or project.language
    view_a, view_b = _versions(project, version_a, version_b)
    other = view_b.entry_index()
    diff = VersionDiff(version_a, version_b)
    seen = set()
    for entry in view_a.entries:
        match = other.get(entry.id)
        if match is None:
            diff.only_a.append(entry.id)
            continue
        seen.add(entry.id)
        ta, tb = view_a.get_translation(entry.id, language), view_b.get_translation(entry.id, language)
        if entry.english != match.english:
            diff.english_changed.append(RowChange(entry.id, entry.english, match.english, ta, tb))
        elif ta != tb:
            diff.translation_differs.append(RowChange(entry.id, entry.english, match.english, ta, tb))
        else:
            diff.same += 1
    diff.only_b = [entry.id for entry in view_b.entries if entry.id not in seen]
    return diff


# --- Which versions can be trusted, stated explicitly ------------------------------------------------------------

@dataclass(frozen=True)
class VersionState:
    """``status``: ready, no_library_game, unscanned or unverified_load_rules (RimWorld 1.0)."""
    version: str
    status: str
    exportable: bool
    message: str
    entries: int = 0
    translated: int = 0


def library_versions(library: Path) -> set[str]:
    """The versions that have a game folder in the user's game library (``<library>/<major.minor>/<game>/Data/Core``)."""
    from .game_library import library_game_roots
    return {root.parent.name for root in library_game_roots(Path(library))}


def version_states(project: Project, available_game_versions=None) -> list[VersionState]:
    """One explicit state per declared version, in version order, for the version list.

    ``available_game_versions`` is the set of versions that have a game to check against (see
    ``library_versions``); None means unknown and no version is called game-less. RimWorld 1.0 is always
    stated as having unverified load rules and is never formally exported.
    """
    available = None if available_game_versions is None else set(available_game_versions)
    if project.version_profiles:
        project._stash_version()
    states = []
    for version in sorted(set(project.versions), key=_version_key):
        profile = project.version_profiles.get(version)
        if profile is None and version == project.game_version and not project.version_profiles:
            rows = [entry for entry in project.entries if not entry.stale]
            scanned = True
        else:
            scanned = bool(profile and profile.get('coverage', {}).get('extracted'))
            rows = [entry for entry in (profile or {}).get('entries', []) if not entry.get('stale')]
        translated = sum(1 for entry in rows if (entry.japanese if isinstance(entry, Entry) else entry.get('japanese', '')).strip())
        if _version_key(version) == (1, 0):
            states.append(VersionState(version, 'unverified_load_rules', False,
                                       'RimWorld 1.0 のロード規則は未検証のため、正式出力から外します(抽出と編集はできます)', len(rows), translated))
        elif not scanned:
            states.append(VersionState(version, 'unscanned', False, f'{version} はまだ抽出していません', 0, 0))
        elif available is not None and version not in available:
            states.append(VersionState(version, 'no_library_game', True,
                                       f'{version} のゲームがライブラリにありません。一般的な規則で抽出したため、型情報は未検証です',
                                       len(rows), translated))
        else:
            states.append(VersionState(version, 'ready', True, '抽出済み', len(rows), translated))
    return states
