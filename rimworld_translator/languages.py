"""Languages recognized from RimWorld's own installed language archives and folders.

Modern RimWorld stores translations in '<Code> (Display Name).tar' archives.
Do not mistake the absence of directories for the absence of languages.
"""
from __future__ import annotations
from pathlib import Path
import re

LANGUAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
DEFAULT_GAME = Path.home() / ".local/share/Steam/steamapps/common/RimWorld"

def discover_languages(game: Path | None = None) -> dict[str, str]:
    if game is None:
        from .platforms import discover_installations
        installations = discover_installations()
        game = installations[0].root if installations else DEFAULT_GAME
    else:
        game = Path(game)
    roots = [game / "Data/Core/Languages"]
    data = game / "Data"
    if data.is_dir():
        roots += [folder / "Languages" for folder in data.iterdir()
                  if folder.is_dir() and folder.name != "Core"]
    languages: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for item in root.iterdir():
            if item.is_symlink() or not (item.is_dir() or item.suffix.lower() == ".tar"):
                continue
            stem = item.stem if item.is_file() else item.name
            code, divider, display = stem.partition(" (")
            code = code.strip()
            if not LANGUAGE_ID.fullmatch(code):
                continue
            label = display[:-1] if divider and display.endswith(")") else code
            languages.setdefault(code, f"{label}  ({code})" if label != code else code)
    # English must always be present as a source and is a valid language target.
    languages.setdefault("English", "English")
    return dict(sorted(languages.items(), key=lambda item: (item[0] not in {"Japanese", "English"}, item[0] != "Japanese", item[0].casefold())))

def validate_language(code: str) -> str:
    if not isinstance(code, str) or not LANGUAGE_ID.fullmatch(code):
        raise ValueError("Unsafe RimWorld language folder name")
    # Accept a language which was available when the project was saved even if
    # that archive is missing on this particular machine.
    return code

# Country flags are decorative visual hints; language identity comes from folder IDs.
FLAG_COUNTRIES = {
 'Japanese':'jp','English':'gb','Catalan':'es-ct','ChineseSimplified':'cn',
 'ChineseTraditional':'tw','Czech':'cz','Danish':'dk','Dutch':'nl',
 'Estonian':'ee','Finnish':'fi','French':'fr','German':'de','Greek':'gr',
 'Hungarian':'hu','Italian':'it','Korean':'kr','Norwegian':'no','Polish':'pl',
 'Portuguese':'pt','PortugueseBrazilian':'br','Romanian':'ro','Russian':'ru',
 'Slovak':'sk','Spanish':'es','SpanishLatin':'mx','Swedish':'se',
 'Turkish':'tr','Ukrainian':'ua','Vietnamese':'vn',
}
# Offer supported RimWorld language choices even if the game is installed elsewhere.
_installed_labels = discover_languages()
_all_codes = set(FLAG_COUNTRIES) | set(_installed_labels)
LANGUAGES = {
    code: (_installed_labels.get(code, code), FLAG_COUNTRIES.get(code, 'global'))
    for code in sorted(_all_codes, key=lambda c: (c not in ('Japanese', 'English'), c != 'Japanese', c))
}

def validate_languages(languages):
    if not isinstance(languages, list) or not languages:
        raise ValueError('Select at least one output language')
    if len(languages) != len(set(languages)) or any(
        not isinstance(lang, str) or lang not in LANGUAGES for lang in languages
    ):
        raise ValueError('Unknown or duplicate language')
    return languages
