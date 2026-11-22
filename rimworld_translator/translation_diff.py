"""Reconstruct unified translation XML diffs in memory against a read-only base."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .core import MAX_XML


@dataclass(frozen=True)
class PatchedXML:
    path: Path
    root: ET.Element


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: tuple[bytes, ...]
    new_lines: tuple[bytes, ...]


@dataclass(frozen=True)
class _FilePatch:
    path: str
    creation: bool
    deletion: bool
    hunks: tuple[_Hunk, ...]


_HUNK = re.compile(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
_NO_NEWLINE = b"\\ No newline at end of file"
_MODE = re.compile(rb"(?:old mode|new mode|new file mode|deleted file mode) (100644|100755)")
_INDEX = re.compile(rb"index [0-9a-f]+\.\.[0-9a-f]+(?: (100644|100755))?")


def _lines(data: bytes) -> list[bytes]:
    # Unified diffs count LF lines; preserve CR and missing final LF exactly.
    parts = data.split(b"\n")
    return [part + b"\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _relative(name: str) -> str:
    parts = name.split("/")
    if (not name or name.startswith(("/", '"', "'")) or "\\" in name or ":" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in parts)):
        raise ValueError(f"差分に安全でないパスがあります: {name}")
    if Path(name).suffix.casefold() != ".xml":
        raise ValueError(f"差分は翻訳XMLだけを取り込めます: {name}")
    return name


def _header_path(line: bytes) -> str | None:
    try:
        name = line[4:].rstrip(b"\r\n").split(b"\t", 1)[0].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("差分のパスはUTF-8である必要があります。引用・エスケープされたGitパスは未対応です。") from exc
    return None if name == "/dev/null" else _relative(name)


def _git_paths(line: bytes) -> tuple[str, str]:
    try:
        text = line.rstrip(b"\r\n").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("差分のGitパスはUTF-8である必要があります") from exc
    match = re.fullmatch(r"diff --git (a/.+) (b/.+)", text)
    if '"' in text:
        raise ValueError("引用・エスケープされたGitパスは未対応です。通常の相対パスのunified diffを使用してください。")
    if not match:
        raise ValueError("Git差分の接頭辞は a/ と b/ だけに対応しています。通常の相対パスのunified diffを使用してください。")
    old, new = match.groups()
    if _relative(old[2:]) != _relative(new[2:]):
        raise ValueError("差分のファイル名変更・コピーは未対応です")
    return old, new


def _file_path(old: str | None, new: str | None, git: tuple[str, str] | None) -> str:
    if old is None and new is None:
        raise ValueError("差分の元・変更後パスが両方 /dev/null です")
    if git is not None:
        if (old is not None and old != git[0]) or (new is not None and new != git[1]):
            raise ValueError("差分のGitヘッダーとXMLパスが一致しません")
        old = old[2:] if old is not None else None
        new = new[2:] if new is not None else None
    elif old is None and new is not None and new.startswith("b/"):
        new = new[2:]
    elif new is None and old is not None and old.startswith("a/"):
        old = old[2:]
    elif old is not None and new is not None and old.startswith("a/") and new.startswith("b/"):
        old, new = old[2:], new[2:]
    if old is not None and new is not None and old != new:
        raise ValueError("差分の元・変更後パスが異なります。ファイル名変更と任意のパス接頭辞の除去は未対応です。")
    return _relative(new if new is not None else old)


def _read_hunk(lines: list[bytes], index: int) -> tuple[_Hunk, int]:
    match = _HUNK.fullmatch(lines[index].rstrip(b"\r\n"))
    if match is None:
        raise ValueError(f"差分のハンクヘッダーが不正です (差分の{index + 1}行目)")
    old_start, old_count, new_start, new_count = (
        int(value) if value is not None else 1 for value in match.groups())
    old_lines, new_lines = [], []
    index += 1
    changed = False
    while len(old_lines) < old_count or len(new_lines) < new_count:
        if index >= len(lines) or not lines[index].endswith(b"\n"):
            raise ValueError("差分のハンクが途中で終わっています")
        line = lines[index]
        kind, content = line[:1], line[1:]
        if kind not in {b" ", b"-", b"+"}:
            raise ValueError(f"差分のハンクの行数・内容が不正です (差分の{index + 1}行目)")
        if kind in {b" ", b"-"}:
            old_lines.append(content)
        if kind in {b" ", b"+"}:
            new_lines.append(content)
        changed = changed or kind != b" "
        index += 1
        if index < len(lines) and lines[index].rstrip(b"\r\n") == _NO_NEWLINE:
            if kind in {b" ", b"-"}:
                old_lines[-1] = old_lines[-1][:-1]
            if kind in {b" ", b"+"}:
                new_lines[-1] = new_lines[-1][:-1]
            index += 1
        if len(old_lines) > old_count or len(new_lines) > new_count:
            raise ValueError("差分のハンクの行数が一致しません")
    if not changed:
        raise ValueError("差分のハンクに変更がありません")
    return _Hunk(old_start, old_count, new_start, new_count, tuple(old_lines), tuple(new_lines)), index


def _parse(data: bytes) -> list[_FilePatch]:
    if b"\x00" in data:
        raise ValueError("バイナリ・UTF-16の差分は未対応です。通常のunified diffを使用してください。")
    lines = _lines(data.removeprefix(b"\xef\xbb\xbf"))
    result, seen = [], set()
    git = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.rstrip(b"\r\n")
        if not stripped:
            index += 1
            continue
        if line.startswith(b"diff --git "):
            if git is not None:
                raise ValueError("差分にXML本文のないGit変更があります。通常のunified diffを使用してください。")
            git = _git_paths(line)
            index += 1
            continue
        if git is not None and (_MODE.fullmatch(stripped) or _INDEX.fullmatch(stripped)):
            index += 1
            continue
        if not line.startswith(b"--- "):
            raise ValueError(f"未対応または不正な差分形式です (差分の{index + 1}行目)。通常のunified diffが必要です。")
        if index + 1 >= len(lines) or not lines[index + 1].startswith(b"+++ "):
            raise ValueError("差分に変更後の +++ XMLヘッダーがありません")
        old, new = _header_path(line), _header_path(lines[index + 1])
        path = _file_path(old, new, git)
        if path.casefold() in seen:
            raise ValueError(f"差分に同じXMLの変更が複数あります。連続適用は未対応です: {path}")
        seen.add(path.casefold())
        index += 2
        hunks = []
        while index < len(lines) and lines[index].startswith(b"@@ "):
            hunk, index = _read_hunk(lines, index)
            hunks.append(hunk)
        if not hunks:
            raise ValueError(f"{path}: 通常のunified diffのハンクがありません。結合・バイナリ差分などは未対応です。")
        result.append(_FilePatch(path, old is None, new is None, tuple(hunks)))
        git = None
    if git is not None or not result:
        raise ValueError("取り込めるunified diffのXML変更がありません")
    return result


def _line_index(start: int, count: int) -> int:
    if count > 0 and start == 0:
        raise ValueError("差分のハンクの開始行が不正です")
    return start - 1 if count else start


def _reconstruct(data: bytes, hunks: tuple[_Hunk, ...]) -> bytes:
    base, output = _lines(data), []
    cursor = 0
    for hunk in hunks:
        old_index = _line_index(hunk.old_start, hunk.old_count)
        if old_index < cursor or old_index > len(base):
            raise ValueError("差分の元の行位置が重複するか、基準XMLの範囲外です")
        output.extend(base[cursor:old_index])
        if len(output) != _line_index(hunk.new_start, hunk.new_count):
            raise ValueError("差分の変更後の行位置が一致しません")
        if tuple(base[old_index:old_index + hunk.old_count]) != hunk.old_lines:
            raise ValueError(f"基準XMLと差分の元の内容が一致しません ({hunk.old_start}行目)。位置・改行を含む元のXMLを選択してください。")
        output.extend(hunk.new_lines)
        cursor = old_index + hunk.old_count
    output.extend(base[cursor:])
    if any(not line.endswith(b"\n") for line in output[:-1]):
        raise ValueError("差分の改行なし指定がファイル末尾以外にあります")
    result = b"".join(output)
    if len(result) > MAX_XML:
        raise ValueError("差分の復元XMLが大きすぎます (上限8MB)")
    return result


def _translation_xml(data: bytes) -> ET.Element:
    normalized = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        raise ValueError("DTD / ENTITY declarations are prohibited")
    try:
        root = ET.fromstring(data)
    except LookupError as exc:
        raise ValueError(f"XMLの文字コードが未対応です: {exc}") from exc
    if root.tag != "LanguageData":
        raise ValueError("差分は LanguageData をルートに持つ翻訳XMLだけを取り込めます")
    return root


def read_xml_diff(path: Path, base_folder: Path) -> tuple[list[PatchedXML], list[str]]:
    """Read exact relative bases; return reconstructed XML and per-file warnings.

    Supports plain unified or unquoted Git a/ b/ XML diffs with /dev/null.
    Paths are relative to the explicitly selected folder; no search, fuzzy
    context matching, file renames, external commands or filesystem writes.
    """
    base_folder = Path(base_folder).absolute()
    if any(part.is_symlink() for part in (base_folder, *base_folder.parents)):
        raise ValueError("差分の基準フォルダーがシンボリックリンクです")
    if not base_folder.is_dir():
        raise ValueError("差分の基準XMLがある元フォルダーを選択してください")
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("差分ファイルのパスにシンボリックリンクがあります")
        patches = _parse(path.read_bytes())
    except (ValueError, OSError) as exc:
        return [], [f"{path}: {exc}"]
    result, warnings = [], []
    for patch in patches:
        xml_path = base_folder / patch.path
        try:
            if any(part.is_symlink() for part in (xml_path, *xml_path.parents)):
                raise ValueError("基準XMLのパスにシンボリックリンクがあります")
            if patch.creation:
                if xml_path.exists():
                    raise ValueError("差分では新規作成ですが、基準フォルダーに同名のファイルが既にあります")
                before, old_root = b"", None
            else:
                if not xml_path.is_file():
                    raise ValueError("差分の基準XMLがありません。差分の相対パスに合う元フォルダーを選択してください")
                if xml_path.stat().st_size > MAX_XML:
                    raise ValueError("差分の基準XMLが大きすぎます (上限8MB)")
                before = xml_path.read_bytes()
                if len(before) > MAX_XML:
                    raise ValueError("差分の基準XMLが大きすぎます (上限8MB)")
                old_root = _translation_xml(before)
            after = _reconstruct(before, patch.hunks)
            if patch.deletion:
                if after:
                    raise ValueError("差分の削除後にXMLの内容が残っています")
                warnings.append(f"{patch.path}: 差分のファイル削除を確認しました。現在の訳と元ファイルは削除しません。")
                continue
            root = _translation_xml(after)
            if old_root is not None:
                after_keys = {node.tag for node in root}
                if any(node.tag not in after_keys for node in old_root):
                    warnings.append(f"{patch.path}: 差分にキーの削除があります。現在の訳は消さずに保持します。")
            if any(not (node.text or "").strip() for node in root if isinstance(node.tag, str) and not len(node)):
                warnings.append(f"{patch.path}: 空の訳は取り込まず、現在の訳を保持します。")
            result.append(PatchedXML(xml_path, root))
        except (ValueError, OSError, ET.ParseError) as exc:
            warnings.append(f"{patch.path}: {exc}")
    return result, warnings
