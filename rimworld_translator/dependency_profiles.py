"""Bounded dependency contexts for static extraction of one target MOD.

This module enumerates hypotheses, not installed/verified load orders. It never
loads dependency content or merges scenario results into translation state.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, islice
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .core import safe_xml
from .extraction import condition_matches, content_files, resolve_load_folders, version_tuple

_PACKAGE = re.compile(r'[a-z0-9_][a-z0-9_.-]*', re.IGNORECASE)
_CONDITIONS = {'ifmodactive', 'ifmodactiveall', 'ifmodactiveany',
               'ifmodnotactive', 'ifmodnotactiveall', 'mayrequire', 'mayrequireanyof'}


@dataclass(frozen=True)
class DependencyDiagnostic:
    code: str
    message: str
    source: str


@dataclass(frozen=True)
class DependencyScenario:
    name: str
    active_mods: frozenset[str]


@dataclass(frozen=True)
class DependencyPlan:
    game_version: str
    required_mods: tuple[str, ...]
    optional_mods: tuple[str, ...]
    scenarios: tuple[DependencyScenario, ...]
    total_scenarios: int
    unexamined_scenarios: int
    diagnostics: tuple[DependencyDiagnostic, ...]


def plan_dependency_scenarios(source: Path, game_version: str, *, max_scenarios=16,
                              base_active_mods=(), max_xml_files=2000,
                              context_sources=()) -> DependencyPlan:
    """Plan capped, deterministic contexts for one declared game version.

    Versioned About dependencies replace the base list only on an exact match
    (the owned game's ModUpdating.txt documents this override rule). Conditions
    in the version's potential LoadFolders/Defs/Patches contribute optional IDs.
    Potentially active supplied context sources are inspected under the same
    shared XML-file limit for their Defs; their own content is not a translation
    target, and dependency PatchOperations are not applied by the extractor.
    FindMod display names resolve through the target and context_sources About
    metadata using case-sensitive exact names. Unknown names remain diagnosed.
    Fixed IDs are never toggled. Every scenario is a hypothesis: dependency
    availability, transitive requirements and load order remain unverified.
    """
    if type(max_scenarios) is not int or not 1 <= max_scenarios <= 256:
        raise ValueError('max_scenarios must be an integer between 1 and 256')
    if type(max_xml_files) is not int or not 1 <= max_xml_files <= 100000:
        raise ValueError('max_xml_files must be an integer between 1 and 100000')
    source = Path(source)
    if any(p.is_symlink() for p in (source, *source.parents)):
        raise ValueError('Source must not contain symbolic links')
    source = source.resolve(strict=True)
    about = safe_xml(source / 'About/About.xml')
    versions = [(n.text or '').strip() for n in about.findall('supportedVersions/li')]
    if not versions or any(not re.fullmatch(r'\d+\.\d+', v) for v in versions):
        raise ValueError('About.xml must declare valid supportedVersions')
    if game_version not in versions:
        raise ValueError('Dependency context must refer to a declared version')
    diagnostics = []

    def warn(code, message, location):
        diagnostic = DependencyDiagnostic(code, str(message), str(location))
        if diagnostic not in diagnostics:
            diagnostics.append(diagnostic)

    def package(value, location):
        value = value.strip().casefold()
        if not _PACKAGE.fullmatch(value):
            warn('invalid-package', f'Invalid package ID: {value}', location)
            return None
        return value

    dependencies = about.find(f'modDependenciesByVersion/v{game_version}')
    if dependencies is None:
        dependencies = about.find('modDependencies')
    required = set()
    if dependencies is not None:
        for node in dependencies.findall('li'):
            ident = package(node.findtext('packageId') or '', 'About/About.xml')
            if ident:
                required.add(ident)
    fixed = set(required)
    if isinstance(base_active_mods, (str, bytes)):
        raise ValueError('base_active_mods must be an iterable of package IDs')
    for value in base_active_mods:
        if not isinstance(value, str) or not _PACKAGE.fullmatch(value.strip()):
            raise ValueError('Invalid fixed active package ID')
        fixed.add(value.strip().casefold())
    own_id = package(about.findtext('packageId') or '', 'About/About.xml')
    if own_id:
        fixed.add(own_id)
    optional = set()
    # FindMod uses exact display names, not package IDs. Supplied metadata is
    # evidence for possible contexts; it does not activate every supplied MOD.
    names_to_packages = {}
    if own_id and about.findtext('name'):
        names_to_packages.setdefault(about.findtext('name'), set()).add(own_id)
    if isinstance(context_sources, (str, bytes, Path)):
        raise ValueError('context_sources must be an iterable of MOD folders')
    contexts = {}
    for value in context_sources:
        context = Path(value)
        if any(p.is_symlink() for p in (context, *context.parents)):
            raise ValueError('Dependency source must not contain symbolic links')
        context = context.resolve(strict=True)
        metadata = safe_xml(context / 'About/About.xml')
        ident = package(metadata.findtext('packageId') or '', str(context / 'About/About.xml'))
        if ident is None:
            raise ValueError(f'Dependency source has no valid package ID: {context}')
        contexts.setdefault(ident, []).append(context)
        name = metadata.findtext('name')
        if name:
            names_to_packages.setdefault(name, set()).add(ident)

    def conditions(root, location, *, defs=False, patches=False, owner_id=None, folder_guards=None):
        if (defs and root.tag == 'Defs') or patches:
            # The extractor checks direct Defs and every dispatched operation.
            # Only recognized operation containers dispatch nested operations;
            # arbitrary fields and PatchOperation values keep their own rules.
            def operation_nodes(operation, ancestors=()):
                rejected = [(name, value) for name, value in operation.attrib.items()
                            if name.casefold().startswith('ifmod')
                            and name.casefold() not in _CONDITIONS]
                if rejected:
                    for name, value in rejected:
                        warn('unknown-condition',
                             f'Unexamined condition {name}={value}', location)
                    return
                if not any(not impossible_load_conditions(operation.attrib, owner_id, guard, ancestors)
                           for guard in folder_guards or ({},)):
                    return
                success = (operation.findtext('success') or 'Normal').strip()
                if success not in {'Normal', 'Invert', 'Always', 'Never'}:
                    warn('patch-success',
                         f'Unexamined patch success mode: {success}', location)
                    # The extractor stops before dispatching unknown modes.
                    # A nested operation still controls its sequence: retain
                    # its own guards, which may skip that unknown outcome.
                    if ancestors:
                        yield operation
                    return
                kind = operation.get('Class', '').rsplit('.', 1)[-1]
                supported = {'PatchOperationSequence', 'PatchOperationConditional',
                    'PatchOperationFindMod', 'PatchOperationAdd', 'PatchOperationReplace',
                    'PatchOperationRemove', 'PatchOperationInsert', 'PatchOperationTest',
                    'PatchOperationAttributeAdd', 'PatchOperationAttributeSet',
                    'PatchOperationAttributeRemove'}
                if kind not in supported:
                    warn('patch-unsupported',
                         f'Unexamined patch operation: {kind or "PatchOperation"}', location)
                    # Unsupported effects never dispatch the operation's body.
                    # Its own guard may still skip an unknown sequence outcome.
                    if ancestors:
                        yield operation
                    return
                if kind in {'PatchOperationAdd', 'PatchOperationInsert'}:
                    default_order = 'Append' if kind == 'PatchOperationAdd' else 'Prepend'
                    order = (operation.findtext('order') or default_order).strip()
                    if order not in {'Append', 'Prepend'}:
                        warn('patch-order', f'Unexamined patch order: {order}', location)
                        # An invalid order never publishes the value subtree.
                        # Retain nested guards that can skip this unknown effect.
                        if ancestors:
                            yield operation
                        return
                nested_nodes = []
                dispatched = False
                reachable = False
                lineage = (*ancestors, operation.attrib)
                findmod_names = [item.text for item in operation.findall('mods/li') if item.text]
                findmod_packages = set().union(*(names_to_packages.get(name, set())
                    for name in findmod_names))
                # An exact named MOD may also be required by this operation,
                # an ancestor or every reachable folder route. Prove that all
                # mapped alternatives being absent contradicts those guards.
                guaranteed_findmod_match = (kind == 'PatchOperationFindMod' and
                    bool(findmod_packages) and all(impossible_load_conditions(
                        {'IfModNotActive': ','.join(sorted(findmod_packages))},
                        owner_id, guard, lineage)
                        for guard in folder_guards or ({},)))
                # Conversely, known display names cannot match when every
                # mapped package is excluded by each reachable guard route.
                # An unresolved name keeps the match branch possible.
                guaranteed_findmod_nomatch = (kind == 'PatchOperationFindMod' and
                    bool(findmod_names) and all(name in names_to_packages for name in findmod_names) and
                    all(impossible_load_conditions(
                        {'IfModActive': ','.join(sorted(findmod_packages))},
                        owner_id, guard, lineage)
                        for guard in folder_guards or ({},)))
                for child in operation:
                    if kind == 'PatchOperationSequence' and child.tag == 'operations':
                        dispatched = True
                        nested_nodes.append(child)
                        for nested in child:
                            nodes = list(operation_nodes(nested, lineage))
                            reachable |= bool(nodes)
                            nested_nodes.extend(nodes)
                    elif kind in {'PatchOperationConditional', 'PatchOperationFindMod'} and child.tag in {'match', 'nomatch'}:
                        dispatched = True
                        # A guaranteed, exactly named active MOD selects match.
                        # Its nomatch branch cannot reveal target translations.
                        # Keep the container itself for sequence outcome control.
                        if child.tag == 'nomatch' and guaranteed_findmod_match:
                            continue
                        if child.tag == 'match' and guaranteed_findmod_nomatch:
                            continue
                        nodes = list(operation_nodes(child, lineage))
                        reachable |= bool(nodes)
                        nested_nodes.extend(nodes)
                    elif kind not in {'PatchOperationRemove', 'PatchOperationTest',
                            'PatchOperationAttributeAdd', 'PatchOperationAttributeSet',
                            'PatchOperationAttributeRemove'}:
                        # These terminal operations never publish child XML or
                        # evaluate its guards. Their own guards still matter
                        # when the operation controls a surrounding sequence.
                        nested_nodes.extend(child.iter())
                # Empty top-level containers cannot affect later independent
                # operations. Nested containers may control a surrounding
                # sequence: only a Normal/Always Sequence with all children
                # absent is known to return True like a skipped operation.
                # Conditional/FindMod can also fail while resolving context.
                neutral_sequence = (kind == 'PatchOperationSequence' and
                    (operation.findtext('success') or 'Normal').strip() in {'Normal', 'Always'})
                if dispatched and not reachable and (not ancestors or neutral_sequence):
                    return
                yield operation
                yield from nested_nodes

            def reachable_nodes():
                for child in root:
                    if patches:
                        yield from operation_nodes(child)
                        continue
                    rejected = [(name, value) for name, value in child.attrib.items()
                                if name.casefold().startswith('ifmod')
                                and name.casefold() not in _CONDITIONS]
                    if rejected:
                        # The extractor excludes unknown IfMod conditions on
                        # direct Defs/operations, as on LoadFolders entries.
                        for name, value in rejected:
                            warn('unknown-condition',
                                 f'Unexamined condition {name}={value}', location)
                        continue
                    # A folder may have several alternative LoadFolders entries.
                    # The child is reachable if any entry can hold together with
                    # its own guards. Keep equal-named ANY clauses separate.
                    if any(not impossible_load_conditions(child.attrib, owner_id, guard)
                           for guard in folder_guards or ({},)):
                        yield from child.iter()
            nodes = reachable_nodes()
        else:
            nodes = root.iter()
        for node in nodes:
            for name, value in node.attrib.items():
                key = name.casefold()
                if key not in _CONDITIONS:
                    if key.startswith(('ifmod', 'mayrequire')):
                        warn('unknown-condition', f'Unexamined condition {name}={value}', location)
                    continue
                identifiers = set()
                for part in re.split('[,;]', value):
                    if part.strip():
                        ident = package(part, location)
                        if ident:
                            identifiers.add(ident)
                # An ANY clause already satisfied by fixed IDs cannot change
                # when another alternative is toggled. Keep its alternatives
                # only if some other clause also needs them. A supplied owner's
                # ID is fixed locally while inspecting its active content.
                minimum = fixed | ({owner_id} if owner_id else set())
                if key in {'ifmodactive', 'ifmodactiveany', 'mayrequireanyof'} and identifiers & minimum:
                    continue
                optional.update(identifiers)
            if node.get('Class', '').rsplit('.', 1)[-1] == 'PatchOperationFindMod':
                names = [item.text for item in node.findall('mods/li') if item.text]
                if not names:
                    warn('findmod-context', 'FindMod has no display names to resolve', location)
                alternatives = set()
                for name in names:
                    matches = names_to_packages.get(name, set())
                    if not matches:
                        warn('findmod-context', f'FindMod display name has no package mapping: {name}', location)
                    else:
                        alternatives.update(matches)
                        if len(matches) > 1:
                            warn('findmod-ambiguous-name',
                                 f'FindMod display name maps to multiple packages: {name}', location)
                # FindMod matches any listed display name. A known fixed
                # match makes all other alternatives irrelevant to this
                # operation, without suppressing their metadata diagnostics.
                minimum = fixed | ({owner_id} if owner_id else set())
                if not alternatives & minimum:
                    optional.update(alternatives)

    seen_files = set()
    limited = False

    def impossible_load_conditions(attributes, owner_id, folder_attributes=None, ancestors=()):
        # Match the resolver's ANY/ALL semantics, but only reject provable
        # contradictions. Propagate forced single choices without branching
        # over optional package combinations.
        required = set(fixed)
        # A supplied context contributes content only in scenarios where its
        # own package is active. This assumption is local to its inspection;
        # an optional context must not become globally required.
        if owner_id:
            required.add(owner_id)
        forbidden = set()
        positive_any = []
        negative_all = []
        clauses = list(attributes.items())
        if folder_attributes is not None:
            clauses.extend(folder_attributes.items())
        # Keep repeated ANY clauses separate: merging attribute dictionaries
        # would silently replace an ancestor's condition with its child's.
        for ancestor in ancestors:
            clauses.extend(ancestor.items())
        for name, value in clauses:
            key = name.casefold()
            packages = {part.strip().casefold() for part in re.split('[,;]', value)
                        if part.strip()}
            if key in {'ifmodactiveall', 'mayrequire'}:
                required.update(packages)
            elif key == 'ifmodnotactive':
                forbidden.update(packages)
            elif key in {'ifmodactive', 'ifmodactiveany', 'mayrequireanyof'}:
                positive_any.append(packages)
            elif key == 'ifmodnotactiveall':
                negative_all.append(packages)
        while True:
            if required & forbidden:
                return True
            previous = (len(required), len(forbidden))
            for packages in positive_any:
                if packages & required:
                    continue
                available = packages - forbidden
                if not available:
                    return True
                if len(available) == 1:
                    required.update(available)
            for packages in negative_all:
                if packages & forbidden:
                    continue
                available = packages - required
                if not available:
                    return True
                if len(available) == 1:
                    forbidden.update(available)
            if previous == (len(required), len(forbidden)):
                return False

    def inspect(owner, owner_id=None):
        nonlocal limited

        def location(file):
            return file.relative_to(source).as_posix() if owner == source else str(file)

        load_file = owner / 'LoadFolders.xml'
        folders = None
        folder_guards = {}
        folder_routes = []
        explicit_folders = False
        if load_file.exists():
            try:
                root = safe_xml(load_file)
                branches = {node.tag.lstrip('v'): node for node in root}
                branch = branches.get(game_version)
                if branch is None:
                    older = [v for v in branches if re.fullmatch(r'\d+(?:\.\d+)+', v)
                             and version_tuple(v) <= version_tuple(game_version)]
                    branch = branches[max(older, key=version_tuple)] if older else branches.get('default')
                if branch is not None:
                    folders = []
                    explicit_folders = True
                    for item in branch:
                        if item.tag != 'li':
                            continue
                        rejected = [(name, value) for name, value in item.attrib.items()
                                    if name.casefold().startswith('ifmod')
                                    and name.casefold() not in _CONDITIONS]
                        if rejected:
                            # The resolver excludes these folders in every
                            # context; their conditions cannot reveal keys.
                            for name, value in rejected:
                                warn('unknown-condition',
                                     f'Unexamined condition {name}={value}', location(load_file))
                            continue
                        if impossible_load_conditions(item.attrib, owner_id):
                            # Impossible branches cannot contribute keys and
                            # must not displace reachable bounded scenarios.
                            continue
                        # LoadFolders separators are relative to the MOD root,
                        # including /Common and separator-only root aliases.
                        # Use the same normalization as the resolver.
                        relative = (item.text or '').strip().replace('\\', '/').strip('/')
                        path = Path(relative)
                        folder = owner / path
                        if path.is_absolute() or '..' in path.parts:
                            warn('load-path', f'Invalid load folder: {relative}', location(load_file))
                        elif any(p.is_symlink() for p in (folder, *folder.parents)):
                            warn('load-path', f'Symbolic load folder excluded: {relative}', location(load_file))
                        elif not folder.is_dir():
                            warn('missing-folder', f'Load folder missing: {relative}', location(load_file))
                        else:
                            # An unavailable/rejected path cannot contribute keys.
                            # Its conditions must not consume bounded scenario slots.
                            conditions(item, location(load_file), owner_id=owner_id)
                            folders.append(folder)
                            folder_routes.append((folder, dict(item.attrib)))
                            folder_guards.setdefault(folder, []).append(dict(item.attrib))
            except (OSError, ValueError, ET.ParseError) as exc:
                warn('loadfolders', str(exc), location(load_file))
        if folders is None:
            folders = resolve_load_folders(
                owner, game_version, fixed,
                lambda code, message, relative: warn(code, message, location(owner / relative)))
        # Each supported condition is monotone in one direction. If a guard
        # holds with both only fixed IDs and all its mentioned IDs active, it
        # holds in every optional context. A supplied owner's own ID is fixed
        # locally: its content is inspected only when that owner is active.
        def always_active(guard):
            minimum = fixed | ({owner_id} if owner_id else set())
            maximum = minimum | {part.strip().casefold()
                for name, value in guard.items() if name.casefold() in _CONDITIONS
                for part in re.split('[,;]', value) if part.strip()}
            return all(condition_matches(guard, active, lambda *args: None, '')
                       for active in (minimum, maximum))

        # Explicit LoadFolders entries load last-first; default resolver roots
        # already have that priority. Only files active in every owner context
        # can permanently hide a lower root's relative content path.
        priority = reversed(folder_routes) if explicit_folders else ((folder, {}) for folder in folders)
        shadowed = set()
        for folder, guard in priority:
            unconditional = always_active(guard)
            for category in (('Defs', 'Patches') if owner == source else ('Defs',)):
                for file in content_files([folder], category):
                    key = (category, file.relative_to(folder / category).as_posix())
                    if key in shadowed:
                        continue
                    if unconditional:
                        shadowed.add(key)
                    if file in seen_files:
                        continue
                    if len(seen_files) >= max_xml_files:
                        limited = True
                        return
                    seen_files.add(file)
                    try:
                        conditions(safe_xml(file), location(file),
                                   defs=category == 'Defs', patches=category == 'Patches',
                                   owner_id=owner_id,
                                   folder_guards=folder_guards.get(folder, ({},)))
                    except (OSError, ValueError, ET.ParseError) as exc:
                        warn('condition-xml', str(exc), location(file))

    inspect(source)
    inspected = {source}
    # Only contexts that can be active contribute conditions. Newly discovered
    # IDs may make another supplied context relevant, regardless of input order.
    while not limited:
        pending = [(context, ident) for ident, sources in contexts.items()
                   if ident in fixed or ident in optional
                   for context in sources if context not in inspected]
        if not pending:
            break
        for context, ident in dict.fromkeys(pending):
            inspected.add(context)
            inspect(context, ident)
            if limited:
                break
    if limited:
        warn('condition-file-limit', f'Condition XML exploration stopped after {max_xml_files} files', '.')
    optional = tuple(sorted(optional - fixed))
    total = 1 << len(optional)
    subsets = (subset for size in range(len(optional) + 1) for subset in combinations(optional, size))
    scenarios = tuple(DependencyScenario('optional:' + ','.join(subset) if subset else 'base',
                                         frozenset(fixed.union(subset)))
                      for subset in islice(subsets, max_scenarios))
    unexamined = total - len(scenarios)
    if unexamined:
        # Keep diagnostics bounded too: decimal conversion of 2**N can exceed
        # Python's integer-string limit even when only a few scenarios run.
        warn('scenario-limit',
             f'2^{len(optional)} - {len(scenarios)} optional combinations remain unexamined', '.')
    warn('dependency-context-unverified',
         'Dependency availability, transitive requirements, incompatibilities and load order are unverified', 'About/About.xml')
    return DependencyPlan(game_version, tuple(sorted(required)), optional, scenarios,
                          total, unexamined, tuple(diagnostics))
