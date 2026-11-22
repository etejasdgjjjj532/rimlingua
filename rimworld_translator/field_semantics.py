"""Known non-language field contracts, independent of CLR string eligibility.

The tables are data (assets/field_contracts.json), so a new contract needs no code change.

Rules identify owners and serialized field structures, never the spelling of a
value. An empty reason means no known exclusion, not proof of localization safety.
The structural fallback also protects pre-policy saved DefInjected entries whose
CLR owner metadata is unavailable. Keyed and Strings resource keys are unrelated.
"""
from __future__ import annotations

from functools import lru_cache
import json
from types import SimpleNamespace


def nonlocalizable_reason(kind: str, group: str, key: str, *, owner_type: str = '',
                          attributes=()) -> str:
    """Explain a known internal field, or return an empty string.

    ``owner_type`` is the declaring owner, not the concrete XML subclass. When
    supplied, exact CLR ownership takes precedence over legacy path inference.
    TranslationHandle alone is deliberately insufficient to reject visible text.
    """
    if kind != 'DefInjected':
        return ''
    for attribute in attributes:
        if attribute.rsplit('.', 1)[-1] in {'NoTranslateAttribute', 'UnsavedAttribute'}:
            return 'CLR attribute excludes localization: ' + attribute
    parts = key.split('.')[1:]  # The first segment is the Def name, never a field.
    if not parts:
        return ''
    # List values end in an index/handle; their field is the preceding segment.
    field = parts[-2] if len(parts) > 1 and parts[-1].isdigit() else parts[-1]
    tables = contracts()
    if owner_type:
        return tables['owned'].get((owner_type, field), '')

    # Legacy projects store Def type and field path even without CLR metadata.
    # Scope every fallback to that owning Def and its exact serialized structure.
    for groups, pattern, reason in tables['legacy']:
        if group in groups and len(pattern) == len(parts) and all(
                expected == '*' or part in expected for expected, part in zip(pattern, parts)):
            return reason
    return ''


@lru_cache(maxsize=1)
def contracts() -> dict:
    """The contract tables of assets/field_contracts.json: owned {(owner, field): reason} and legacy rules."""
    from importlib import resources
    data = json.loads(resources.files(__package__).joinpath('assets/field_contracts.json').read_text(encoding='utf-8'))
    owned = {(item['owner'], item['field']): item['reason'] for item in data['owned']}
    # Each path segment becomes '*' or a frozenset of accepted names.
    legacy = tuple((frozenset(item['groups']),
                    tuple(segment if segment == '*' else frozenset([segment] if isinstance(segment, str) else segment)
                          for segment in item['path']),
                    item['reason']) for item in data['legacy'])
    return {'owned': owned, 'legacy': legacy}


def entry_nonlocalizable_reason(entry) -> str:
    """Use saved CLR evidence when present, otherwise the legacy path contract.

    Cached on the evidence tuple and key because the GUI asks about every entry on each edit.
    """
    evidence = tuple(item for item in getattr(entry, 'evidence', ()) if isinstance(item, str) and item.startswith('CLR '))
    return _nonlocalizable_cached(entry.kind, entry.group, entry.key, evidence)


@lru_cache(maxsize=200_000)
def _nonlocalizable_cached(kind, group, key, evidence) -> str:
    entry = SimpleNamespace(kind=kind, group=group, key=key, evidence=evidence)
    return _entry_nonlocalizable_reason(entry)


def _entry_nonlocalizable_reason(entry) -> str:
    owner, attributes = '', ()
    for item in getattr(entry, 'evidence', ()):
        if not isinstance(item, str) or not item.startswith('CLR ') or ': ' not in item:
            continue
        member, raw_attributes = item[4:].split(': ', 1)
        if '.' not in member:
            continue
        owner, _ = member.rsplit('.', 1)
        attributes = tuple(raw_attributes.split(', '))
        break
    return nonlocalizable_reason(entry.kind, entry.group, entry.key,
                                 owner_type=owner, attributes=attributes)
