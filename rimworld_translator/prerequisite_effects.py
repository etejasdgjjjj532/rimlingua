"""How many rows of a project depend on each found prerequisite MOD.

Three kinds of dependence can be read from the saved rows and the folders, all read-only:

* parent: the row's Def inherits (directly or through the source's own abstract Defs) a ``ParentName`` that only
  the prerequisite defines;
* type: the CLR type that owns the row's field is declared in the prerequisite's assemblies and not in the
  source's own (assembly metadata only, never executed);
* conditional: the row sits in a ``MayRequire`` block naming the prerequisite, or in a load folder whose
  ``IfModActive`` names it.

A row can fall in several groups, so ``rows`` is the union. What cannot be decided is reported in ``notes``
instead of being counted: ``assemblies-unreadable`` (the type count is then ``None``) and
``conditional-def-level`` (a ``MayRequire`` nested inside a Def counts every row of that Def, an upper bound).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

CONDITIONS = {'mayrequire', 'mayrequireanyof', 'ifmodactive', 'ifmodactiveall', 'ifmodactiveany'}


@dataclass(frozen=True)
class PrerequisiteEffect:
    package_id: str
    parent_rows: int
    type_rows: int | None
    conditional_rows: int
    rows: frozenset
    notes: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.rows)


def _packages(attributes) -> set[str]:
    found = set()
    for name, value in attributes.items():
        if name.casefold() in CONDITIONS:
            found.update(p.strip().casefold() for p in re.split('[,;]', value) if p.strip())
    return found


def _parse(path: Path):
    from .core import safe_xml
    try:
        return safe_xml(path)
    except (OSError, ValueError, ET.ParseError):
        return None


def _def_names(folders) -> dict[str, str]:
    """``Name`` -> ``ParentName`` ('' when none) of every Def template in the folders' Defs."""
    from .extraction import content_files
    names = {}
    for path in content_files(list(folders), 'Defs'):
        root = _parse(path)
        for node in (root if root is not None else ()):
            if isinstance(node.tag, str) and node.get('Name'):
                names.setdefault(node.get('Name'), node.get('ParentName') or '')
    return names


def _default_assembly_types(path) -> set[str]:
    from .schema import inspect_assembly
    return set(inspect_assembly(Path(path)))


def _types(folders, assembly_types) -> set[str]:
    from .extraction import content_files
    found = set()
    for dll in content_files(list(folders), 'Assemblies', '.dll'):
        found |= set(assembly_types(dll))
    return found


def _owner(entry) -> str:
    for item in entry.evidence:
        if isinstance(item, str) and item.startswith('CLR ') and ': ' in item:
            member = item[4:].split(': ', 1)[0]
            if '.' in member:
                return member.rsplit('.', 1)[0]
    return ''


def _parent(entry) -> str:
    return next((item[len('XML parent: '):] for item in entry.evidence
                 if isinstance(item, str) and item.startswith('XML parent: ')), '')


def _conditional_rows(project, source: Path, packages):
    """(package -> {entry ids}, package -> {entry ids counted only through a nested block}) for the source's own files."""
    exact = {p: set() for p in packages}
    nested_only = {p: set() for p in packages}
    wanted = {p.casefold(): p for p in packages}
    by_file = {}
    for entry in project.entries:
        by_file.setdefault(entry.source_file, []).append(entry)
    for relative, rows in by_file.items():
        path = Path(relative)
        path = path if path.is_absolute() else source / path
        if source not in (path, *path.parents) or not path.is_file():
            continue
        root = _parse(path)
        if root is None:
            continue
        top, deep = {}, {}
        for node in root:
            if not isinstance(node.tag, str):
                continue
            ident = (node.tag, (node.findtext('defName') or '').strip()) if root.tag == 'Defs' else ('Keyed', node.tag)
            top.setdefault(ident, set()).update(_packages(node.attrib))
            for child in node.iter():
                if child is not node:
                    deep.setdefault(ident, set()).update(_packages(child.attrib))
        for entry in rows:
            ident = ((entry.group, entry.key.split('.', 1)[0]) if entry.kind == 'DefInjected'
                     else ('Keyed', entry.key) if entry.kind == 'Keyed' else None)
            for name, package in wanted.items():
                if ident in top and name in top[ident]:
                    exact[package].add(entry.id)
                elif ident in deep and name in deep[ident]:
                    nested_only[package].add(entry.id)
    return exact, nested_only


def _load_folder_conditions(source: Path, packages) -> dict[str, set[str]]:
    """package -> load folders (relative, '/'-separated) that LoadFolders.xml loads only when it is active."""
    wanted = {p.casefold(): p for p in packages}
    result = {p: set() for p in packages}
    root = _parse(source / 'LoadFolders.xml') if (source / 'LoadFolders.xml').is_file() else None
    for node in (root.iter('li') if root is not None else ()):
        folder = (node.text or '').strip().replace('\\', '/').strip('/')
        if not folder:
            continue
        for name in _packages(node.attrib):
            if name in wanted:
                result[wanted[name]].add(folder)
    return result


def prerequisite_effects(project, found, version, active_mods=None, *, assembly_types=None, cancel=None) -> dict[str, PrerequisiteEffect]:
    """Per found prerequisite (``scan_context.Prerequisite`` with a folder), how many project rows depend on it."""
    from .extraction import ScanCancelled, resolve_load_folders
    assembly_types = assembly_types or _default_assembly_types
    found = [item for item in found if item.folder is not None]
    source = Path(project.source).resolve()
    active = {*(active_mods or ()), *(item.package_id for item in found)}

    def folders(folder):
        return resolve_load_folders(Path(folder), version, active)

    def check():
        if cancel is not None and cancel():
            raise ScanCancelled()

    source_names = _def_names(folders(source))
    try:
        source_types = _types(folders(source), assembly_types)
    except (OSError, ValueError):
        source_types = set()
    packages = [item.package_id for item in found]
    exact, nested = _conditional_rows(project, source, packages)
    load_conditions = _load_folder_conditions(source, packages)

    def external_parent(name):
        """The first template name above ``name`` that the source does not define itself."""
        seen = set()
        while name in source_names and name not in seen:
            seen.add(name)
            name = source_names[name]
        return name

    result = {}
    for item in found:
        check()
        notes = []
        prerequisite_names = set(_def_names(folders(item.folder)))
        parents = {e.id for e in project.entries if _parent(e) and external_parent(_parent(e)) in prerequisite_names
                   and external_parent(_parent(e)) not in source_names}
        try:
            owned = _types(folders(item.folder), assembly_types)
            types = {e.id for e in project.entries if _owner(e) in owned and _owner(e) not in source_types}
            type_count = len(types)
        except (OSError, ValueError):
            types, type_count = set(), None
            notes.append('assemblies-unreadable')
        prefixes = load_conditions[item.package_id]
        in_folder = {e.id for e in project.entries
                     if any(e.source_file.replace('\\', '/').strip('/') == p or e.source_file.replace('\\', '/').strip('/').startswith(p + '/')
                            for p in prefixes)}
        conditional = exact[item.package_id] | in_folder | nested[item.package_id]
        if nested[item.package_id] - exact[item.package_id] - in_folder:
            notes.append('conditional-def-level')
        result[item.package_id] = PrerequisiteEffect(item.package_id, len(parents), type_count, len(conditional),
                                                     frozenset(parents | types | conditional), tuple(notes))
    return result
