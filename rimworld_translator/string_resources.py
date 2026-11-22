"""Conservative parser for the game's nested Languages/.../Strings text lists."""
from __future__ import annotations

from pathlib import PurePosixPath
import re


STRING_LINE = re.compile(r'line_(0|[1-9][0-9]*)\Z')
WINDOWS_DEVICE = re.compile(r'(?:CON(?:IN\$|OUT\$)?|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])\Z', re.IGNORECASE)
# System.Char.IsWhiteSpace, used by String.Trim, excludes Python's U+001C–001F.
ENGINE_WHITESPACE = '\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'


def decode_strings(data: bytes) -> str:
    """Recognize the standard reader's UTF BOMs; reject corrupt input strictly."""
    # UTF-32 LE begins with UTF-16 LE's BOM, so inspect four-byte marks first.
    for marker, encoding in ((b'\xff\xfe\x00\x00', 'utf-32'),
                             (b'\x00\x00\xfe\xff', 'utf-32'),
                             (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16')):
        if data.startswith(marker):
            return data.decode(encoding)
    return data.decode('utf-8-sig')


def validate_string_entry(group: str, key: str) -> bool:
    """Accept portable nested TXT resource paths and logical line indexes."""
    if not isinstance(group, str) or not isinstance(key, str):
        return False
    path = PurePosixPath(group)
    return (len(path.parts) >= 2 and not path.is_absolute()
            and path.as_posix() == group and path.suffix == '.txt'
            and all(not part.startswith('.') and not part.endswith((' ', '.'))
                    and not WINDOWS_DEVICE.fullmatch(part.split('.', 1)[0].rstrip(' ')) for part in path.parts)
            and not any(char in group for char in '\\:<>"|?*\x00\r\n')
            and all(ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF for char in group)
            and bool(STRING_LINE.fullmatch(key)))


def parse_strings(text: str) -> list[str]:
    """Match GenText.LinesFromString: trim, remove // comments, skip empty."""
    lines = []
    for raw in re.split(r'\r\n|\n', text):
        value = raw.strip(ENGINE_WHITESPACE).split('//', 1)[0]
        if value:
            lines.append(value)
    return lines


def serialize_string_entries(entries, translations: dict[str, str]) -> bytes:
    """Serialize one complete translated resource without silent source fallback."""
    entries = list(entries)
    if not entries:
        raise ValueError('Strings resource has no lines')
    groups = {entry.group for entry in entries}
    if len(groups) != 1 or any(entry.kind != 'Strings' or not validate_string_entry(entry.group, entry.key)
                               for entry in entries):
        raise ValueError('Invalid Strings resource identity')
    ordered = sorted(entries, key=lambda entry: int(entry.key[5:]))
    if [entry.key for entry in ordered] != [f'line_{index}' for index in range(len(ordered))]:
        raise ValueError('Strings resource indexes must be complete and consecutive')
    lines = []
    for entry in ordered:
        value = translations.get(entry.id)
        if (not isinstance(value, str) or not value.strip() or value != value.lstrip()
                or (not lines and value.startswith('\ufeff'))
                or any(character in value for character in ('\r', '\n', '//'))
                or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF
                       or ord(character) in (0xFFFE, 0xFFFF) for character in value)):
            raise ValueError('Strings translation would change meaning when parsed')
        # GenText trims before comment removal. A sentinel retains spaces which
        # belonged to an inline comment's preceding text in the source resource.
        lines.append(value + ('//' if value != value.rstrip() else ''))
    return ('\n'.join(lines) + '\n').encode('utf-8')
