"""Reviewed, reversible installs of editor-owned translation mods only.

The editor's ordinary exports cannot write to Steam content. This service makes
one narrow exception: a dedicated, marked package directly inside local Mods.
Workshop packages, source mods, user ModsConfig.xml and saves remain read-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET

from .core import PACKAGE, atomic_write, safe_xml
from .platforms import GameInstallation


MARKER = ".rimworld-translator.json"


@dataclass(frozen=True)
class InstallPlan:
    generated_mod: Path
    installation: GameInstallation
    destination: Path
    package_id: str
    files: tuple[str, ...]
    file_count: int
    total_bytes: int
    updating: bool
    generated_fingerprint: str
    previous_fingerprint: str | None
    source: Path | None = None

    @property
    def actions(self) -> tuple[str, ...]:
        if self.updating:
            return (f"導入済みの翻訳をバックアップ: {self.destination}",
                    f"翻訳MODを更新: {self.destination}")
        return (f"翻訳MODを導入: {self.destination}",)


@dataclass(frozen=True)
class InstallResult:
    destination: Path
    package_id: str
    backup: Path | None
    updating: bool
    file_count: int


@dataclass(frozen=True)
class ModDependency:
    package_id: str
    display_name: str
    url: str = ""
    # Other package IDs the game accepts in place of this one (forks and renamed MODs).
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModMetadata:
    root: Path
    package_id: str
    name: str
    dependencies: tuple[ModDependency, ...]
    load_after: tuple[str, ...]
    load_before: tuple[str, ...]
    supported_versions: tuple[str, ...] = ()
    dependencies_by_version: tuple[tuple[str, tuple[ModDependency, ...]], ...] = ()


def dependencies_for(meta: ModMetadata, version: str) -> tuple[ModDependency, ...]:
    """The prerequisites the game uses for ``version``: its modDependenciesByVersion entry, else modDependencies."""
    return next((items for key, items in meta.dependencies_by_version if key == version), meta.dependencies)


@dataclass(frozen=True)
class ModDiagnostic:
    code: str
    severity: str
    message: str
    package_id: str = ""
    related_package_id: str = ""


def _no_links(path: Path) -> Path:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"リンク先への書き込みはできません: {path}")
    return path.resolve()


def _relative_file(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("翻訳MODのファイル一覧が不正です")
    relative = PurePosixPath(value)
    if relative.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in relative.parts or str(relative) != value:
        raise ValueError("翻訳MODのファイル一覧に不正なパスがあります")
    return value


def read_mod_metadata(root: Path | str, about_file: Path | None = None) -> ModMetadata:
    """``about_file`` lets a read-only caller pass About.xml already resolved past a link."""
    root = Path(root).resolve()
    about = safe_xml(about_file or root / "About/About.xml")
    package = (about.findtext("packageId") or "").strip().casefold()
    if not PACKAGE.fullmatch(package):
        raise ValueError(f"MODのpackageIdを確認してください: {root}")
    def packages(nodes) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            node.text.strip().casefold() for node in nodes if node.text and PACKAGE.fullmatch(node.text.strip())
        ))

    def dependency_list(block) -> tuple[ModDependency, ...]:
        dependencies = []
        for node in block.findall("li") if block is not None else ():
            ident = (node.findtext("packageId") or "").strip().casefold()
            if PACKAGE.fullmatch(ident):
                dependencies.append(ModDependency(
                    ident, (node.findtext("displayName") or ident).strip(),
                    (node.findtext("steamWorkshopUrl") or node.findtext("downloadUrl") or "").strip(),
                    packages(node.findall("alternativePackageIds/li"))))
        return tuple(dependencies)

    def values(*tags: str) -> tuple[str, ...]:
        return packages(node for tag in tags for node in about.findall(tag + "/li"))
    by_version = tuple((block.tag[1:], dependency_list(block)) for block in about.findall("modDependenciesByVersion/*")
                       if re.fullmatch(r"v\d+\.\d+", block.tag))
    supported = tuple(dict.fromkeys(node.text.strip() for node in about.findall("supportedVersions/li")
                                    if node.text and re.fullmatch(r"\d+\.\d+", node.text.strip())))
    return ModMetadata(root, package, (about.findtext("name") or package).strip(), dependency_list(about.find("modDependencies")),
                       values("loadAfter", "forceLoadAfter"), values("loadBefore", "forceLoadBefore"), supported, by_version)


WORKSHOP_LINK = 'About/PublishedFileId.txt'


def owned_mod_files(root: Path | str, package_id: str | None = None) -> tuple[str, ...]:
    """Validate an exported package's ownership manifest and complete file set."""
    root = _no_links(Path(root))
    marker = root / MARKER
    if not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"エディターが生成した翻訳MODではありません: {root}")
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("package_id"), str) or not PACKAGE.fullmatch(metadata["package_id"]):
        raise ValueError("翻訳MODの所有情報が不正です")
    if package_id is not None and metadata["package_id"].casefold() != package_id.casefold():
        raise ValueError("別の翻訳プロジェクトに属するMODです")
    files = metadata.get("files")
    if not isinstance(files, list) or len(files) > 100000:
        raise ValueError("翻訳MODのファイル一覧が不正です")
    files = [_relative_file(value) for value in files]
    if len(set(files)) != len(files) or MARKER in files or "About/About.xml" not in files:
        raise ValueError("翻訳MODのファイル一覧が不正です")
    expected = set(files) | {MARKER}
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("翻訳MODにシンボリックリンクがあります")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    # Steam's uploader writes this file next to a published translation; it is not user content to protect.
    actual.discard(WORKSHOP_LINK)
    if actual != expected:
        raise ValueError("翻訳フォルダに未登録のユーザーファイル、または不足したファイルがあります。別のフォルダを選んでください")
    if read_mod_metadata(root).package_id != metadata["package_id"].casefold():
        raise ValueError("About.xmlと翻訳プロジェクトのpackageIdが一致しません")
    return tuple(sorted(expected))


def mod_fingerprint(root: Path, files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8") + b"\0")
        with (root / relative).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _mods_root(installation: GameInstallation) -> Path:
    root = _no_links(installation.root)
    mods = _no_links(installation.mods)
    if mods != root / "Mods" or not (root / "Data/Core").is_dir():
        raise ValueError("ゲームのローカルModsフォルダを選んでください。Workshopには導入できません")
    if "workshop" in {part.casefold() for part in mods.parts}:
        raise ValueError("Workshopの内容は変更できません")
    if mods.exists() and not mods.is_dir():
        raise ValueError("Modsフォルダがディレクトリではありません")
    return mods


def review_installation(
    generated_mod: Path | str, installation: GameInstallation, *, source: Path | str | None = None,
    destination_name: str | None = None,
) -> InstallPlan:
    """Produce a read-only review plan; installing requires a separate call."""
    generated_mod = _no_links(Path(generated_mod))
    files = owned_mod_files(generated_mod)
    package = read_mod_metadata(generated_mod).package_id
    mods = _mods_root(installation)
    existing = []
    if mods.is_dir():
        for folder in mods.iterdir():
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            try:
                if read_mod_metadata(folder).package_id == package:
                    existing.append(folder)
            except (ValueError, OSError, ET.ParseError):
                pass
    if len(existing) > 1:
        raise ValueError("同じpackageIdのMODが複数あります。重複を解消してから導入してください")
    name = destination_name or (existing[0].name if existing else "editor-" + package)
    if not name or name.startswith(".") or any(c in name for c in '/\\:') or name in {".", ".."}:
        raise ValueError("導入フォルダ名が不正です")
    destination = _no_links(mods / name)
    if existing and destination != existing[0].resolve():
        raise ValueError("同じ翻訳MODが別のフォルダに導入済みです")
    for protected in (generated_mod, Path(source).resolve() if source is not None else None):
        if protected is not None and (destination == protected or protected in destination.parents or destination in protected.parents):
            raise ValueError("元MOD・生成元フォルダと導入先を分けてください")
    previous = None
    if destination.exists():
        previous_files = owned_mod_files(destination, package)
        previous = mod_fingerprint(destination, previous_files)
    return InstallPlan(generated_mod, installation, destination, package, files, len(files),
                       sum((generated_mod / relative).stat().st_size for relative in files), previous is not None,
                       mod_fingerprint(generated_mod, files), previous,
                       Path(source).resolve() if source is not None else None)


def _copy_owned(source: Path, destination: Path, files: tuple[str, ...]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)


def _backup(plan: InstallPlan) -> Path:
    backups = _no_links(plan.destination.parent / ".rimworld-translator-backups")
    marker = backups / ".rimworld-translator-backups.json"
    if backups.exists():
        if not backups.is_dir() or not marker.is_file() or marker.is_symlink():
            raise ValueError("バックアップ先に別のファイルがあります。移動してから再試行してください")
        if json.loads(marker.read_text(encoding="utf-8")) != {"schema": 1, "owner": "rimworld-translator"}:
            raise ValueError("バックアップフォルダの所有情報が不正です")
    else:
        backups.mkdir(parents=True)
        atomic_write(marker, b'{"schema": 1, "owner": "rimworld-translator"}\n')
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final = backups / (stamp + "-" + uuid.uuid4().hex[:12])
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=backups))
    try:
        files = owned_mod_files(plan.destination, plan.package_id)
        _copy_owned(plan.destination, staging / "mod", files)
        fingerprint = mod_fingerprint(staging / "mod", files)
        if fingerprint != plan.previous_fingerprint:
            raise ValueError("導入済みの翻訳が確認後に変わりました。もう一度内容を確認してください")
        atomic_write(staging / "backup.json", (json.dumps({
            "schema": 1, "package_id": plan.package_id, "destination_name": plan.destination.name,
            "time": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint,
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        os.replace(staging, final)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _keep_workshop_link(installed: Path, staging: Path) -> None:
    """Carry over About/PublishedFileId.txt so updating a published translation does not unlink it from its Workshop item."""
    link = installed / WORKSHOP_LINK
    kept = staging / WORKSHOP_LINK
    if link.is_file() and not link.is_symlink() and not kept.exists() and link.stat().st_size <= 64:
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(link, kept)


def install_translation(plan: InstallPlan) -> InstallResult:
    """Execute exactly a reviewed plan, backing up before replacement."""
    fresh = review_installation(plan.generated_mod, plan.installation, source=plan.source,
                                destination_name=plan.destination.name)
    if fresh != plan:
        raise ValueError("確認後にファイルが変わりました。もう一度導入内容を確認してください")
    mods = _mods_root(plan.installation)
    mods.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rwt-install-", dir=mods))
    displaced = mods / (".rwt-replaced-" + uuid.uuid4().hex)
    backup = None
    try:
        _copy_owned(plan.generated_mod, staging, plan.files)
        if mod_fingerprint(staging, owned_mod_files(staging, plan.package_id)) != plan.generated_fingerprint:
            raise ValueError("コピー中に生成された翻訳が変わりました。もう一度確認してください")
        if plan.updating:
            backup = _backup(plan)
            if mod_fingerprint(plan.destination, owned_mod_files(plan.destination, plan.package_id)) != plan.previous_fingerprint:
                raise ValueError("導入済みの翻訳が変更されました。もう一度確認してください")
            _keep_workshop_link(plan.destination, staging)
            os.replace(plan.destination, displaced)
        elif plan.destination.exists():
            raise ValueError("導入先が作成されました。もう一度内容を確認してください")
        try:
            os.replace(staging, plan.destination)
        except BaseException:
            if displaced.exists():
                os.replace(displaced, plan.destination)
            raise
        if displaced.exists():
            shutil.rmtree(displaced)
        return InstallResult(plan.destination, plan.package_id, backup, plan.updating, plan.file_count)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def restore_installation(backup: Path | str, installation: GameInstallation) -> InstallResult:
    """Restore an owned backup; first back up the current installed translation."""
    backup = _no_links(Path(backup))
    mods = _mods_root(installation)
    if backup.parent != mods / ".rimworld-translator-backups":
        raise ValueError("このゲームの翻訳バックアップを選んでください")
    metadata = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("schema") != 1:
        raise ValueError("未対応の翻訳バックアップです")
    files = owned_mod_files(backup / "mod", metadata.get("package_id", ""))
    if mod_fingerprint(backup / "mod", files) != metadata.get("fingerprint"):
        raise ValueError("バックアップのファイルが変更されています")
    plan = review_installation(backup / "mod", installation, destination_name=metadata.get("destination_name"))
    return install_translation(plan)


def read_active_mods(config: Path | str) -> list[str]:
    root = safe_xml(Path(config).resolve())
    return [node.text.strip().casefold() for node in root.findall("activeMods/li") if node.text and node.text.strip()]


def available_mod_paths(installation: GameInstallation) -> list[Path]:
    """Enumerate official, local and Workshop mod folders without changing them."""
    result = []
    for folder in (installation.root / "Data", installation.mods, installation.workshop):
        if folder is not None and folder.is_dir():
            result.extend(path for path in folder.iterdir()
                          if path.is_dir() and not path.name.startswith(".") and (path / "About/About.xml").is_file())
    return result


def diagnose_load_order(
    translation_mod: Path | str, available_mods: list[Path] | tuple[Path, ...],
    mods_config: Path | str | None = None,
) -> list[ModDiagnostic]:
    """Explain missing source/dependencies, disabled mods and incorrect order."""
    translation = read_mod_metadata(translation_mod)
    available = {translation.package_id: translation}
    diagnostics = []
    for path in available_mods:
        try:
            metadata = read_mod_metadata(path)
            available[metadata.package_id] = metadata
        except (ValueError, OSError, ET.ParseError) as exc:
            diagnostics.append(ModDiagnostic("invalid-metadata", "warning", f"MOD情報を読み取れません: {path}: {exc}"))
    active = None
    if mods_config is not None:
        try:
            active = read_active_mods(mods_config)
        except (ValueError, OSError, ET.ParseError) as exc:
            diagnostics.append(ModDiagnostic("invalid-config", "warning", f"MOD設定を読み取れません: {exc}"))
    if active is not None and translation.package_id not in active:
        diagnostics.append(ModDiagnostic("translation-disabled", "warning", "ゲームのMOD設定で翻訳MODを有効にしてください", translation.package_id))
    checked = set()

    def check(mod: ModMetadata, source: bool = False) -> None:
        if mod.package_id in checked:
            return
        checked.add(mod.package_id)
        for dependency in mod.dependencies:
            ident = dependency.package_id
            found = available.get(ident)
            if found is None:
                code = "missing-source" if source else "missing-dependency"
                label = "翻訳元MOD" if source else "必要なMOD"
                diagnostics.append(ModDiagnostic(code, "error", f"{label}「{dependency.display_name}」を導入してください ({ident})", mod.package_id, ident))
                continue
            if active is not None and ident not in active:
                code = "source-disabled" if source else "disabled-dependency"
                diagnostics.append(ModDiagnostic(code, "warning", f"ゲームのMOD設定で「{found.name}」を有効にしてください ({ident})", mod.package_id, ident))
            check(found)
        if active is not None and mod.package_id in active:
            for ident in mod.load_after:
                if ident in active and active.index(ident) > active.index(mod.package_id):
                    diagnostics.append(ModDiagnostic("load-order", "warning", f"MOD一覧で「{mod.name}」を「{available[ident].name if ident in available else ident}」より後に移動してください", mod.package_id, ident))
            for ident in mod.load_before:
                if ident in active and active.index(ident) < active.index(mod.package_id):
                    diagnostics.append(ModDiagnostic("load-order", "warning", f"MOD一覧で「{mod.name}」を「{available[ident].name if ident in available else ident}」より前に移動してください", mod.package_id, ident))

    check(translation, source=True)
    return diagnostics
