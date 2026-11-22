"""Previewable translation interchange and edits, without writing to source mods."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import csv
from dataclasses import dataclass, field
import io
from pathlib import Path
import re
from typing import Iterable
import xml.etree.ElementTree as ET

from .core import PLACEHOLDER as _PLACEHOLDER, Entry, Project, atomic_write, safe_xml, writable_destination
from .languages import LANGUAGES, validate_language
from .translation_diff import read_xml_diff


@dataclass(frozen=True)
class TranslationChange:
    id: str
    language: str
    before: str
    after: str
    review: bool = False


@dataclass
class ImportPreview:
    changes: list[TranslationChange] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemorySuggestion:
    translation: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class _Incoming:
    id: str
    language: str
    text: str
    english: str | None = None
    origin: str = ""
    review: bool = False


def _translation(project: Project, entry: Entry, language: str) -> str:
    # The active entry remains the authority while an editor has unsaved edits.
    return entry.japanese if language == project.language else project.translations.get(language, {}).get(entry.id, "")


def _selected_language(project: Project, language: str | None) -> str:
    language = language or project.language
    validate_language(language)
    if language not in project.languages:
        raise ValueError(f"プロジェクトで選択していない言語です: {language}")
    return language


def _path_language(path: Path) -> str | None:
    for index, part in enumerate(path.parts[:-1]):
        if part == "Languages":
            return path.parts[index + 1]
    for part in reversed(path.parts[:-1]):
        if part in LANGUAGES:
            return part
    return None


def _xml_files(project: Project, path: Path, language: str | None, preview: ImportPreview) -> list[Path]:
    if path.is_file():
        return [path]
    if path.name == "Languages":
        roots = [path]
    elif (path / "Languages").is_dir():
        roots = [path / "Languages"]
    elif _path_language(path) is not None:
        return sorted(path.rglob("*.xml"))
    else:
        roots = sorted(candidate for candidate in path.rglob("Languages") if candidate.is_dir() and not candidate.is_symlink())
    if roots:
        files = []
        selection = [language] if language else project.languages
        for root in roots:
            for selected in selection:
                folder = root / selected
                if folder.is_dir() and not folder.is_symlink():
                    files.extend(sorted(folder.rglob("*.xml")))
        if len(roots) > 1:
            preview.warnings.append("複数のバージョンの翻訳フォルダーがあります。重複する異なる訳は競合として除外します。")
        return files
    if (path.name in {"Keyed", "DefInjected"} or (path / "Keyed").is_dir()
            or (path / "DefInjected").is_dir() or any(path.glob("*.xml"))):
        return sorted(path.rglob("*.xml"))
    return []


def _xml_identity(path: Path, key: str, entries_by_key: dict[str, list[Entry]]) -> str:
    parts = path.parts
    if "Keyed" in parts[:-1]:
        return f"Keyed:Keyed:{key}"
    if "DefInjected" in parts[:-1]:
        index = max(i for i, part in enumerate(parts[:-1]) if part == "DefInjected")
        group = parts[index + 1] if index + 1 < len(parts) - 1 else path.stem
        return f"DefInjected:{group}:{key}"
    matches = entries_by_key.get(key, [])
    return matches[0].id if len(matches) == 1 else key


def _list_item_entries(path: Path, key: str, entries_by_key: dict[str, list[Entry]]) -> list[Entry]:
    """Entries for the items of the list ``key`` (``key.0``, ``key.1``, ...), in list order."""
    group = _xml_identity(path, key, {}).split(":")[1] if "DefInjected" in path.parts[:-1] else None
    prefix = key + "."
    items = [entry for entries in entries_by_key.values() for entry in entries
             if entry.kind == "DefInjected" and entry.key.startswith(prefix)
             and "." not in entry.key[len(prefix):] and (group is None or entry.group == group)
             and not entry.stale]
    numbered = [entry for entry in items if entry.key[len(prefix):].isdigit()]
    # Handle-named items cannot be matched by position; whole-list translations only cover plain lists.
    if len(numbered) != len(items):
        return []
    return sorted(numbered, key=lambda entry: int(entry.key[len(prefix):]))


def _xml_list_rows(node: ET.Element, path: Path, language: str, entries_by_key: dict[str, list[Entry]],
                   preview: ImportPreview) -> list[_Incoming]:
    """A whole-list translation (``<Def.field><li>..</li></Def.field>``), matched to item entries by position."""
    children = [child for child in node if isinstance(child.tag, str)]
    if not children or any(child.tag != "li" or len(child) for child in children):
        preview.warnings.append(f"{path}: {node.tag}: li 以外の子要素がある翻訳は取り込めません")
        return []
    items = _list_item_entries(path, node.tag, entries_by_key)
    if not items:
        preview.warnings.append(f"{path}: {node.tag}: 対応するリストの項目が見つからないため取り込めません")
        return []
    texts = [child.text or "" for child in children if (child.text or "").strip() != _PLACEHOLDER]
    if all("->" in entry.english for entry in items) and all("->" in text for text in texts):
        return _rule_list_rows(node.tag, items, texts, path, language, preview)
    review = len(texts) != len(items)
    if review:
        preview.warnings.append(
            f"{path}: {node.tag}: 訳の項目数 {len(texts)} と原文の項目数 {len(items)} が違います。"
            f"先頭から {min(len(texts), len(items))} 項目を順に取り込み、要確認にします")
    return [_Incoming(entry.id, language, text, origin=str(path), review=review)
            for entry, text in zip(items, texts)]


def _rule_prefix(text: str) -> str:
    return text.partition("->")[0].strip()


def _rule_list_rows(key: str, items: list[Entry], texts: list[str], path: Path, language: str,
                    preview: ImportPreview) -> list[_Incoming]:
    """Grammar rules (``name->text``) are matched by rule name, the n-th translation of a name to its n-th source rule.

    Translators reorder, add and drop rules freely, so list position says little about which rule is which.
    """
    pending: dict[str, list[str]] = defaultdict(list)
    for text in texts:
        pending[_rule_prefix(text)].append(text)
    result = []
    for entry in items:
        candidates = pending.get(_rule_prefix(entry.english))
        if candidates:
            result.append(_Incoming(entry.id, language, candidates.pop(0), origin=str(path)))
    unmatched = sum(len(rest) for rest in pending.values())
    if unmatched or len(result) != len(items):
        preview.warnings.append(
            f"{path}: {key}: 文法ルールを名前で対応付けました({len(result)}/{len(items)} 項目)。"
            f"原文に対応のない訳 {unmatched} 項目は取り込みません")
    return result


def _xml_rows(root: ET.Element, path: Path, language: str, entries_by_key: dict[str, list[Entry]],
              preview: ImportPreview) -> list[_Incoming]:
    result = []
    for node in root:
        if not isinstance(node.tag, str):
            continue
        if node.tag == "rep":
            # Old syntax the game still reads: <rep><path>Def.field</path><trans>text</trans></rep>
            key, text = (node.findtext("path") or "").strip(), node.findtext("trans") or ""
            if key and text.strip() and text.strip() != _PLACEHOLDER:
                result.append(_Incoming(_xml_identity(path, key, entries_by_key), language, text, origin=str(path)))
            continue
        if len(node):
            result.extend(_xml_list_rows(node, path, language, entries_by_key, preview))
            continue
        if (node.text or "").strip() == _PLACEHOLDER:
            continue
        identity = _xml_identity(path, node.tag, entries_by_key)
        result.append(_Incoming(identity, language, node.text or "", origin=str(path)))
    return result


def _read_xml(project: Project, path: Path, language: str | None, preview: ImportPreview) -> list[_Incoming]:
    entries_by_key: dict[str, list[Entry]] = defaultdict(list)
    for entry in project.entries:
        entries_by_key[entry.key].append(entry)
    result = []
    for xml_path in _xml_files(project, path, language, preview):
        target_language = language or _path_language(xml_path) or project.language
        try:
            _selected_language(project, target_language)
            root = safe_xml(xml_path)
            if root.tag != "LanguageData":
                raise ValueError("翻訳XMLは LanguageData がルート要素である必要があります")
        except (ValueError, OSError, ET.ParseError) as exc:
            preview.warnings.append(f"{xml_path}: {exc}")
            continue
        result.extend(_xml_rows(root, xml_path, target_language, entries_by_key, preview))
    return result


def _read_diff(project: Project, path: Path, language: str | None, base_folder: Path,
               preview: ImportPreview) -> list[_Incoming]:
    candidates, warnings = read_xml_diff(path, base_folder)
    preview.warnings.extend(warnings)
    entries_by_key: dict[str, list[Entry]] = defaultdict(list)
    for entry in project.entries:
        entries_by_key[entry.key].append(entry)
    result = []
    for candidate in candidates:
        target_language = language or _path_language(candidate.path) or project.language
        try:
            _selected_language(project, target_language)
        except ValueError as exc:
            preview.warnings.append(f"{candidate.path}: {exc}")
            continue
        result.extend(_xml_rows(candidate.root, candidate.path, target_language, entries_by_key, preview))
    return result


_REVIEW_STATUSES = {"needs-review", "changed", "stale", "review", "fuzzy"}


def _read_csv_text(path: Path, preview: ImportPreview) -> str:
    """UTF-8 (with or without BOM), else Shift_JIS: Excel in Japanese locales saves CSV as cp932."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp932")
        except UnicodeDecodeError as exc:
            raise ValueError("CSVの文字コードを判別できません。UTF-8 または Shift_JIS で保存してください") from exc
        preview.warnings.append(f"{path.name}: UTF-8 ではないため Shift_JIS (Excel の CSV) として読み込みました")
        return text


def _read_csv(project: Project, path: Path, language: str | None, preview: ImportPreview) -> list[_Incoming]:
    result = []
    text = _read_csv_text(path, preview)
    header = text.splitlines()[0] if text.strip() else ""
    delimiter = max((",", ";", "\t"), key=header.count) if header else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    if not reader.fieldnames or "translation" not in reader.fieldnames:
        raise ValueError("CSVには translation 列が必要です")
    if "id" not in reader.fieldnames and not {"kind", "group", "key"}.issubset(reader.fieldnames):
        raise ValueError("CSVには id 列または kind / group / key 列が必要です")
    for row_number, row in enumerate(reader, 2):
        origin = f"{path.name}:{row_number}"
        if None in row or any(value is None for value in row.values()):
            preview.warnings.append(f"{origin}: CSVの列数が一致しません")
            continue
        identity = row.get("id", "").strip()
        components = [row.get(key, "").strip() for key in ("kind", "group", "key")]
        if all(components):
            composed = ":".join(components)
            if identity and identity != composed:
                preview.conflicts.append(f"{origin}: id と kind / group / key が一致しません: {identity}")
                continue
            identity = identity or composed
        if not identity:
            if row["translation"].strip():
                preview.warnings.append(f"{origin}: id がないため取り込めません")
            continue
        target_language = language or row.get("language", "").strip() or project.language
        try:
            _selected_language(project, target_language)
        except ValueError as exc:
            preview.warnings.append(f"{origin}: {exc}")
            continue
        flagged = (row.get("status", "").strip().casefold() in _REVIEW_STATUSES
                   or row.get("review", "").strip().casefold() in {"1", "true", "yes", "y", "はい", "要確認"})
        result.append(_Incoming(identity, target_language, row["translation"], row.get("english") or None, origin, flagged))
    return result


def _polib():
    try:
        import polib
    except ImportError as exc:
        raise ValueError("POの読み書きには polib が必要です。配布版を再インストールしてください。") from exc
    return polib


_PO_LOCALES = {
    "ja": "Japanese", "en": "English", "ca": "Catalan", "zh": "ChineseSimplified",
    "zh_cn": "ChineseSimplified", "zh_hans": "ChineseSimplified", "zh_tw": "ChineseTraditional",
    "zh_hant": "ChineseTraditional", "cs": "Czech", "da": "Danish", "nl": "Dutch",
    "et": "Estonian", "fi": "Finnish", "fr": "French", "de": "German", "el": "Greek",
    "hu": "Hungarian", "it": "Italian", "ko": "Korean", "no": "Norwegian", "nb": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "pt_br": "PortugueseBrazilian", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "es": "Spanish", "es_419": "SpanishLatin",
    "sv": "Swedish", "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
}


def _po_language(declared: str) -> str:
    folded = declared.strip().split(".")[0].replace("-", "_").casefold()
    if folded in _PO_LOCALES:
        return _PO_LOCALES[folded]
    if folded.split("_")[0] in _PO_LOCALES:
        return _PO_LOCALES[folded.split("_")[0]]
    return next((language for language in LANGUAGES if language.casefold() == folded), declared)


def _read_po(project: Project, path: Path, language: str | None, preview: ImportPreview) -> list[_Incoming]:
    polib = _polib()
    try:
        catalog = polib.pofile(str(path))
    except (ValueError, OSError) as exc:
        raise ValueError(f"POを読み込めません: {exc}") from exc
    declared = catalog.metadata.get("X-RimWorld-Language") or catalog.metadata.get("Language") or project.language
    target_language = _selected_language(project, language or _po_language(declared))
    result = []
    for item in catalog:
        if item.obsolete:
            continue
        if item.msgid_plural:
            preview.warnings.append(f"{item.msgctxt or item.msgid}: POの複数形はRimWorldのキーに対応しないため除外しました")
            continue
        if not item.msgctxt:
            preview.unknown.append(item.msgid)
            preview.warnings.append(f"{item.msgid}: 安定したキーを特定する msgctxt がありません")
            continue
        result.append(_Incoming(item.msgctxt, target_language, item.msgstr, item.msgid, str(path), "fuzzy" in item.flags))
        if "fuzzy" in item.flags:
            preview.warnings.append(f"{item.msgctxt}: PO側で要確認 (fuzzy) に指定されています")
    return result


def preview_import(project: Project, path: Path, language: str | None = None, overwrite: bool = False,
                   base_folder: Path | None = None) -> ImportPreview:
    """Read XML folders/subsets, unified diffs, BOM CSV or contextual PO.

    Diffs require an explicit read-only ``base_folder`` matching their relative
    XML paths. Reconstructed XML is imported in memory, including unchanged
    nonempty translations. Neither the project nor source files are modified.

    Blank incoming translations are always ignored. Existing differing nonempty
    translations require ``overwrite=True``; differing incoming duplicates are
    never selected automatically. XML has no source-English history to compare.
    """
    path = Path(path).absolute()
    if path.is_symlink():
        raise ValueError("取り込み元がシンボリックリンクです")
    if not path.exists():
        raise ValueError(f"取り込み元がありません: {path}")
    if language is not None:
        _selected_language(project, language)
    if path.is_file() and path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("取り込みファイルが大きすぎます (上限64MB)")
    preview = ImportPreview()
    if path.is_file() and path.suffix.casefold() == ".csv":
        incoming = _read_csv(project, path, language, preview)
    elif path.is_file() and path.suffix.casefold() == ".po":
        incoming = _read_po(project, path, language, preview)
    elif path.is_file() and path.suffix.casefold() in {".diff", ".patch"}:
        if base_folder is None:
            raise ValueError("差分の基準XMLがある元フォルダーを選択してください")
        incoming = _read_diff(project, path, language, base_folder, preview)
    elif path.is_dir() or path.suffix.casefold() == ".xml":
        incoming = _read_xml(project, path, language, preview)
    else:
        raise ValueError("XML、差分 (.diff / .patch)、CSV、PO、または翻訳MODのフォルダーを選択してください")
    entries = {entry.id: entry for entry in project.entries}
    grouped: dict[tuple[str, str], list[_Incoming]] = defaultdict(list)
    for row in incoming:
        if row.id not in entries:
            if row.id not in preview.unknown:
                preview.unknown.append(row.id)
        elif row.text.strip():
            grouped[(row.id, row.language)].append(row)
    for (identity, target_language), rows in grouped.items():
        entry = entries[identity]
        label = f"{target_language} / {identity}"
        if len({row.text for row in rows}) > 1:
            preview.conflicts.append(f"{label}: 取り込み元に異なる訳が重複しています")
            continue
        before = _translation(project, entry, target_language)
        after = rows[0].text
        if before.strip() and before != after and not overwrite:
            preview.conflicts.append(f"{label}: 現在の訳を保護しました。置き換える場合は上書きを選択してください。")
            continue
        source_changed = any(row.english is not None and row.english != entry.english for row in rows)
        review = source_changed or any(row.review for row in rows)
        if source_changed:
            preview.warnings.append(f"{label}: 取り込み元の英語と現在の英語が異なります。要確認として取り込みます。")
        if before != after or review:
            preview.changes.append(TranslationChange(identity, target_language, before, after, review))
    if not incoming and not preview.warnings:
        preview.warnings.append("取り込める翻訳が見つかりませんでした。翻訳言語のフォルダーまたはXMLを選択してください。")
    return preview


@dataclass
class _StateSnapshot:
    states: dict[tuple[str, str], dict]


def _snapshot_states(project: Project, changes: list[TranslationChange]) -> _StateSnapshot:
    entries = {entry.id: entry for entry in project.entries}
    states = {}
    for change in changes:
        if change.id not in entries:
            continue
        entry = entries[change.id]
        state = {"reviewed": False, "approved": False, "review": entry.review, "changed": entry.changed, "new": entry.is_new}
        if change.language == project.language:
            state.update(reviewed=entry.reviewed, approved=entry.approved)
        else:
            state.update(project.language_states.get(change.language, {}).get(change.id, {}))
        states[(change.language, change.id)] = deepcopy(state)
    return _StateSnapshot(states)


def _restore_states(project: Project, snapshot: _StateSnapshot) -> None:
    for (language, identity), state in snapshot.states.items():
        project.language_states.setdefault(language, {})[identity] = deepcopy(state)
    for entry in project.entries:
        state = snapshot.states.get((project.language, entry.id))
        if state is not None:
            for name in ("reviewed", "approved", "review", "changed"):
                setattr(entry, name, bool(state.get(name, False)))
            entry.is_new = bool(state.get("new", False))


def _set_translation(project: Project, change: TranslationChange, entry: Entry) -> None:
    project.set_translation(change.id, change.after, change.language)
    if change.review:
        state = project.language_states.setdefault(change.language, {}).setdefault(change.id, {})
        state.update(review=True, reviewed=False, approved=False)
        if change.language == project.language:
            entry.review = True
            entry.reviewed = entry.approved = False


def _apply_transaction(project: Project, changes: list[TranslationChange]) -> None:
    entries = {entry.id: entry for entry in project.entries}
    if len(entries) != len(project.entries):
        raise ValueError("プロジェクト内に重複するキーがあります")
    seen = set()
    for change in changes:
        if not isinstance(change, TranslationChange) or not isinstance(change.before, str) or not isinstance(change.after, str):
            raise ValueError("変更データが不正です")
        _selected_language(project, change.language)
        identity = (change.language, change.id)
        if identity in seen:
            raise ValueError(f"変更対象が重複しています: {change.language} / {change.id}")
        seen.add(identity)
        if change.id not in entries:
            raise ValueError(f"変更対象のキーがありません: {change.id}")
        if _translation(project, entries[change.id], change.language) != change.before:
            raise ValueError(f"プレビュー後に訳が変更されました。再度プレビューしてください: {change.language} / {change.id}")
    state_snapshot = _snapshot_states(project, changes)
    stored = {(change.language, change.id): project.translations.get(change.language, {}).get(change.id) for change in changes}
    active = {change.id: entries[change.id].japanese for change in changes if change.language == project.language}
    try:
        for change in changes:
            _set_translation(project, change, entries[change.id])
    except Exception:
        for (language, identity), text in stored.items():
            if text is None:
                project.translations.get(language, {}).pop(identity, None)
            else:
                project.translations.setdefault(language, {})[identity] = text
        for identity, text in active.items():
            entries[identity].japanese = text
        _restore_states(project, state_snapshot)
        raise


@dataclass
class EditBatch:
    changes: list[TranslationChange]
    _before_states: _StateSnapshot
    _after_states: _StateSnapshot
    _applied: bool = True

    def undo(self, project: Project) -> None:
        if not self._applied:
            raise ValueError("この変更はすでに元に戻されています")
        reversed_changes = [TranslationChange(change.id, change.language, change.after, change.before) for change in self.changes]
        _apply_transaction(project, reversed_changes)
        _restore_states(project, self._before_states)
        self._applied = False

    def redo(self, project: Project) -> None:
        if self._applied:
            raise ValueError("この変更はすでに適用されています")
        _apply_transaction(project, self.changes)
        _restore_states(project, self._after_states)
        self._applied = True


def apply_changes(project: Project, changes: Iterable[TranslationChange]) -> EditBatch:
    changes = list(changes)
    before = _snapshot_states(project, changes)
    _apply_transaction(project, changes)
    return EditBatch(changes, before, _snapshot_states(project, changes))


def preview_replace(project: Project, find: str, replace: str, entry_ids: Iterable[str] | None = None, regex: bool = False) -> ImportPreview:
    if not isinstance(find, str) or not find:
        raise ValueError("検索する文字を入力してください")
    if not isinstance(replace, str):
        raise ValueError("置換する文字列が不正です")
    selected = None if entry_ids is None else set(entry_ids)
    preview = ImportPreview()
    try:
        pattern = re.compile(find) if regex else None
        for entry in project.entries:
            if selected is not None and entry.id not in selected:
                continue
            before = _translation(project, entry, project.language)
            if not before:
                continue
            after = pattern.sub(replace, before) if pattern is not None else before.replace(find, replace)
            if after != before:
                preview.changes.append(TranslationChange(entry.id, project.language, before, after))
    except re.error as exc:
        raise ValueError(f"正規表現が不正です: {exc}") from exc
    return preview


def _output_path(project: Project, path: Path) -> Path:
    path = Path(path).absolute()
    return writable_destination(path.parent, Path(project.source)) / path.name


def export_csv(project: Project, path: Path, language: str | None = None, detailed: bool = False) -> None:
    """Export every selected language by default, including untranslated entries.

    ``detailed`` adds source_file, status, previous_english and note columns for a translator or reviewer
    working in a spreadsheet. Import reads back id / translation / status / review and ignores the rest.
    """
    from .row_filters import _view
    languages = [_selected_language(project, language)] if language else list(project.languages)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    extra = ["source_file", "status", "previous_english", "note"] if detailed else []
    writer.writerow(["id", "kind", "group", "key", "english", "translation", "language", *extra])
    for target_language in languages:
        for entry in project.entries:
            translation = _translation(project, entry, target_language)
            row = [entry.id, entry.kind, entry.group, entry.key, entry.english, translation, target_language]
            if detailed:
                status = _view(project, entry, translation, target_language).status
                row += [entry.source_file, status, entry.previous_english, (project.notes.get(entry.id) or {}).get("text", "")]
            writer.writerow(row)
    atomic_write(_output_path(project, path), stream.getvalue().encode("utf-8-sig"))


def export_po(project: Project, path: Path, language: str | None = None) -> None:
    """Export one language; msgctxt carries the stable RimWorld entry identity."""
    target_language = _selected_language(project, language)
    polib = _polib()
    catalog = polib.POFile(encoding="utf-8")
    catalog.metadata = {"MIME-Version": "1.0", "Content-Type": "text/plain; charset=UTF-8", "Content-Transfer-Encoding": "8bit", "Language": target_language, "X-RimWorld-Language": target_language}
    states = getattr(project, "language_states", {}).get(target_language, {})
    for entry in project.entries:
        state = states.get(entry.id, {})
        needs_review = state.get("review", entry.review if target_language == project.language else False) or state.get("changed", entry.changed if target_language == project.language else False)
        note = project.notes.get(entry.id) or {}
        previous = entry.previous_english if target_language == project.language or states.get(entry.id, {}).get("changed") else ""
        catalog.append(polib.POEntry(msgctxt=entry.id, msgid=entry.english, msgstr=_translation(project, entry, target_language),
                                     comment=entry.source_file, tcomment=note.get("text", ""), previous_msgid=previous or None,
                                     flags=["fuzzy"] if needs_review else []))
    atomic_write(_output_path(project, path), str(catalog).encode("utf-8"))


def translation_memory(project: Project, entry_id: str, language: str | None = None) -> list[MemorySuggestion]:
    """Return all distinct translations of exactly equal English, without edits."""
    target_language = _selected_language(project, language)
    entry = next((item for item in project.entries if item.id == entry_id), None)
    if entry is None:
        raise ValueError(f"翻訳メモリの対象キーがありません: {entry_id}")
    candidates: dict[str, list[str]] = defaultdict(list)
    for item in project.entries:
        if item.id == entry_id or item.english != entry.english or item.stale or item.blocked:
            continue
        translation = _translation(project, item, target_language)
        if translation.strip():
            candidates[translation].append(item.id)
    return [MemorySuggestion(text, tuple(identities)) for text, identities in sorted(candidates.items())]


def set_glossary_term(project: Project, source_term: str, translation: str) -> None:
    source_term, translation = source_term.strip(), translation.strip()
    if not source_term or not translation:
        raise ValueError("用語集の英語と訳語を両方入力してください")
    if not hasattr(project, "glossary"):
        project.glossary = {}
    existing = next((key for key in project.glossary if key.casefold() == source_term.casefold()), source_term)
    project.glossary[existing] = translation


def remove_glossary_term(project: Project, source_term: str) -> bool:
    glossary = getattr(project, "glossary", {})
    key = next((key for key in glossary if key.casefold() == source_term.strip().casefold()), None)
    if key is None:
        return False
    del glossary[key]
    return True


@dataclass(frozen=True)
class IdenticalGroup:
    english: str
    entry_ids: tuple[str, ...]
    untranslated: int


def identical_english_groups(project: Project, language: str | None = None, only_untranslated: bool = True) -> list[IdenticalGroup]:
    """Groups of two or more rows with exactly the same English (numbered names, repeated labels), largest first.

    With ``only_untranslated`` a group is listed only while at least one of its rows still has no translation.
    """
    language = _selected_language(project, language)
    groups: dict[str, list[Entry]] = defaultdict(list)
    for entry in project.entries:
        if entry.english.strip() and not (entry.stale or entry.blocked or entry.excluded):
            groups[entry.english].append(entry)
    result = []
    for english, entries in groups.items():
        empty = sum(1 for entry in entries if not _translation(project, entry, language).strip())
        if len(entries) > 1 and (empty or not only_untranslated):
            result.append(IdenticalGroup(english, tuple(entry.id for entry in entries), empty))
    return sorted(result, key=lambda group: (-len(group.entry_ids), group.english))


def preview_apply_identical(project: Project, entry_id: str, language: str | None = None, overwrite: bool = False) -> ImportPreview:
    """Preview copying one row's translation to every other row with the same English.

    Rows that already differ are left alone (and listed as conflicts) unless ``overwrite``.
    Apply the result with ``apply_changes``; the changes are marked for review only if the row is.
    """
    language = _selected_language(project, language)
    source = project.entry_index().get(entry_id)
    if source is None:
        raise ValueError(f"対象のキーがありません: {entry_id}")
    text = _translation(project, source, language)
    if not text.strip():
        raise ValueError("先に元の行の訳を入力してください")
    preview = ImportPreview()
    for entry in project.entries:
        if entry.id == entry_id or entry.english != source.english or entry.stale or entry.blocked or entry.excluded:
            continue
        before = _translation(project, entry, language)
        if before == text:
            continue
        if before.strip() and not overwrite:
            preview.conflicts.append(f"{language} / {entry.id}: 現在の訳を保護しました。置き換える場合は上書きを選択してください。")
            continue
        preview.changes.append(TranslationChange(entry.id, language, before, text))
    return preview
