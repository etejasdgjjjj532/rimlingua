"""Official RimWorld translations (Core and DLC language packs) as read-only translation suggestions.

The game's own language files carry an ' EN: source ' comment before every entry, so each file alone gives
(key, English, translation). Suggestions are shown to the translator, never written automatically; the
packs belong to the game and are only read from the user's own installation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re
import tarfile
import xml.etree.ElementTree as ET

from .core import MAX_XML, PLACEHOLDER as _PLACEHOLDER, english_comment

_LIST_ITEM = re.compile(r"<li>(.*?)</li>", re.S)


def _normalized(english: str) -> str:
    """English as it appears in an EN comment, so both sides compare equal."""
    return english_comment(english).strip()[len("EN:"):].strip()


@dataclass
class OfficialIndex:
    by_key: dict[tuple[str, str, str], list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    by_english: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    entries: int = 0

    def add(self, kind: str, group: str, key: str, english: str, translation: str) -> None:
        if not translation.strip() or translation.strip() == _PLACEHOLDER:
            return
        english = english.strip()
        self.by_key[(kind, group if kind == "DefInjected" else "", key)].append((english, translation))
        if english:
            self.by_english[english][translation] += 1
        self.entries += 1

    def suggest(self, entry, limit: int = 3) -> list[str]:
        """Official translations for an entry: the same key with the same English first, then the same English."""
        english = _normalized(entry.english)
        if not english:
            return []
        group = entry.group if entry.kind == "DefInjected" else ""
        found = [text for source, text in self.by_key.get((entry.kind, group, entry.key), []) if source == english]
        found += [text for text, _ in self.by_english.get(english, Counter()).most_common()]
        result = []
        for text in found:
            if text not in result:
                result.append(text)
        return result[:limit]


def _parse(data: bytes) -> ET.Element | None:
    normalized = data.replace(b"\x00", b"").upper()
    if len(data) > MAX_XML or b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        return None
    try:
        return ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except ET.ParseError:
        return None


def _read_language_file(index: OfficialIndex, relative: PurePosixPath, data: bytes) -> None:
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "DefInjected":
        kind, group = "DefInjected", parts[1]
    elif len(parts) >= 2 and parts[0] == "Keyed":
        kind, group = "Keyed", ""
    else:
        return
    root = _parse(data)
    if root is None or root.tag != "LanguageData":
        return
    english = None
    for node in root:
        if node.tag is ET.Comment:
            text = (node.text or "").strip()
            english = text[3:].strip() if text.startswith("EN:") else english
            continue
        if not isinstance(node.tag, str):
            continue
        source, english = english, None
        if source is None:
            continue
        items = [child for child in node if child.tag == "li"]
        if items:
            # A whole-list translation; its comment lists the English items as <li>..</li>.
            sources = [item.strip() for item in _LIST_ITEM.findall(source)]
            for number, (item, item_source) in enumerate(zip(items, sources)):
                index.add(kind, group, f"{node.tag}.{number}", item_source, item.text or "")
        elif not len(node):
            index.add(kind, group, node.tag, source, node.text or "")


def _language_sources(game: Path, language: str) -> list[Path]:
    data = game / "Data"
    if not data.is_dir():
        return []
    sources = []
    for expansion in sorted(data.iterdir()):
        folder = expansion / "Languages"
        if not folder.is_dir() or folder.is_symlink():
            continue
        for item in sorted(folder.iterdir()):
            stem = item.stem if item.is_file() else item.name
            if stem.partition(" (")[0].strip() == language and not item.is_symlink():
                sources.append(item)
    return sources


@lru_cache(maxsize=4)
def _cached_index(sources: tuple[tuple[str, int, int], ...]) -> OfficialIndex:
    index = OfficialIndex()
    for name, _, _ in sources:
        path = Path(name)
        if path.is_dir():
            for file in sorted(path.rglob("*.xml")):
                if file.is_symlink() or file.stat().st_size > MAX_XML:
                    continue
                index_path = PurePosixPath(*file.relative_to(path).parts)
                _read_language_file(index, index_path, file.read_bytes())
        elif path.suffix.lower() == ".tar":
            with tarfile.open(path) as archive:
                for member in archive:
                    if not member.isfile() or not member.name.endswith(".xml") or member.size > MAX_XML:
                        continue
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        continue
                    stream = archive.extractfile(member)
                    if stream is not None:
                        _read_language_file(index, relative, stream.read())
    return index


def official_index(game: Path | str | None, language: str) -> OfficialIndex:
    """Index of the official packs for ``language`` in an installed game; empty when none are found."""
    if not game:
        return OfficialIndex()
    sources = []
    for path in _language_sources(Path(game), language):
        stat = path.stat()
        sources.append((str(path), stat.st_mtime_ns, stat.st_size))
    return _cached_index(tuple(sources)) if sources else OfficialIndex()


def official_field_patterns(game: Path | str | None, language: str) -> frozenset:
    """(Def type, first field, leaf field) of every DefInjected key the official packs translate.

    Indexes and list handles are ignored, so the pattern also fits a MOD's own Defs of that type. This is
    evidence that the game's translators treat such a field as wording; it does not prove a MOD key works.
    """
    patterns = set()
    for kind, group, key in official_index(game, language).by_key:
        if kind != "DefInjected":
            continue
        fields = [part for part in key.split(".")[1:] if re.fullmatch(r"[a-z][A-Za-z0-9_]*", part)]
        if fields:
            patterns.add((group.rsplit(".", 1)[-1], fields[0], fields[-1]))
    return frozenset(patterns)
