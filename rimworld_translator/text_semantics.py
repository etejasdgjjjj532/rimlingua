"""Judge whether an extracted string value can be player-facing text.

Used only for string fields that carry no MustTranslate/MayTranslate attribute and
are not confirmed by an author's English catalog. Attributed fields are trusted.
The rules look at the value itself and at names that exist in the scanned content
(Def names, Keyed keys). They never name specific MODs, Defs or fields.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

# Kinds that must not become translation entries (translating them breaks references).
INTERNAL = frozenset({'path', 'reference', 'identifier', 'data'})

_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[_.\-][A-Za-z0-9]+)*')
_PATH = re.compile(r'(?:[\w\-. ]+/)+[\w\-.]+')
# A whole value that is one web or launcher address (http://, steam://, www.): a link target, not wording.
_URL = re.compile(r'(?:[a-z][a-z0-9+.\-]*://|www\.)\S+', re.I)
_INNER_CAPITAL = re.compile(r'[a-z0-9][A-Z]')
# One cell of a comma-separated map grid: a token or a placeholder such as '.'.
_GRID_CELL = re.compile(r'[A-Za-z0-9_.\-]+')
# RimWorld naming convention: these suffixes name a lookup tag, key, id or asset, not text.
_NAME_HINT = re.compile(r'(?:tags?|keys?|ids?|tex|texture|path|icon|var|category|categories|group|class|kinds?|types?|mode|resource|resources|prefix|stuff|defs?|defnames?)$', re.I)


_DEBUG_FIELD = re.compile(r'debug', re.I)
# Field names RimWorld uses for text shown to players. A plain word that happens to equal a Def name
# ("Easy", "Mood") in such a field is a label, not a reference to that Def.
DISPLAY_NAME = _DISPLAY_NAME = re.compile(r'(?:label|description|desc|text|title|tip|name|message|verb|gerund|adjective|'
                           r'header|report|summary|string|blurb|letter|caption|prompt|noun)', re.I)


def is_grid(value: str, field: str = '') -> bool:
    """Comma-separated cells without spaces after the commas, each one token, in real grid structure: layout data.

    Prose separates list items with ", "; terrain and roof grids write "Concrete,Concrete,." row after row. Real
    structure means several rows (lines with commas) or at least five cells; "I,II,III" and "1,000,000" are
    wording. A field named like display text (label, description...) never holds a grid.
    """
    if _DISPLAY_NAME.search(field) or ',' not in value or re.search(r',[ \t]', value):
        return False
    rows = [row for row in re.split(r'[\r\n]+', value.strip()) if row.strip()]
    cells = [cell.strip() for cell in re.split(r'[,\r\n]+', value.strip())]
    if not all(_GRID_CELL.fullmatch(cell) for cell in cells):
        return False
    return len(cells) >= 5 or (len(rows) >= 2 and len(cells) >= 3)


@dataclass(frozen=True)
class ValueVerdict:
    kind: str        # display | ambiguous | path | reference | identifier | data
    reason: str


def field_leaf(key: str) -> str:
    """Last non-index segment of a DefInjected key (list items end in an index or handle)."""
    parts = key.split('.')[1:]
    if not parts:
        return ''
    return parts[-2] if len(parts) > 1 and parts[-1].isdigit() else parts[-1]


def classify_value(text: str, field: str = '', *, defs=frozenset(), keyed=frozenset()) -> ValueVerdict:
    value = text.strip()
    if not value:
        return ValueVerdict('display', 'empty')
    if _DEBUG_FIELD.match(field):
        return ValueVerdict('identifier', f'debug-only field ({field}); the game never shows it to players')
    if not any(character.isalnum() for character in value) and '{' not in value and '[' not in value:
        # Punctuation only (map grids, separators): data, not wording. Digits can be shown text ("0.5:1").
        return ValueVerdict('identifier', 'no letters or digits')
    if is_grid(value, field):
        return ValueVerdict('data', 'comma-separated grid of tokens (map layout data)')
    if _URL.fullmatch(value):
        return ValueVerdict('path', 'web address')
    if re.search(r'\s', value):
        # Sentences and multi-word labels. A slash path with spaces is rare enough to leave to review.
        return ValueVerdict('display', 'contains whitespace')
    if '{' in value or '[' in value or '<' in value:
        return ValueVerdict('display', 'contains placeholders or markup')
    if _PATH.fullmatch(value):
        return ValueVerdict('path', 'slash-separated asset path')
    if not _TOKEN.fullmatch(value):
        # Non-ASCII, punctuation or digits first: ordinary text such as "100%", "Ж", "—".
        return ValueVerdict('display', 'not an identifier token')
    # Hyphens and digits also occur in ordinary labels ("left-sensor", "Mk2"); underscores,
    # dots and inner capitals are how code-style names are spelled.
    structured = bool(re.search(r'[_.]', value) or _INNER_CAPITAL.search(value))
    if value in keyed:
        return ValueVerdict('reference', 'equals a Keyed key')
    if value in defs and not (_DISPLAY_NAME.search(field) and not structured):
        # Case-sensitive equality with a Def name; display text is rarely written exactly like one.
        return ValueVerdict('reference', 'equals a Def name')
    if structured:
        return ValueVerdict('identifier', 'single token with underscores, inner capitals or digits')
    if _NAME_HINT.search(field):
        return ValueVerdict('identifier', f'plain token in a field named like a lookup value ({field})')
    return ValueVerdict('ambiguous', 'single plain word; could be a label or a tag')
