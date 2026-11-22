"""Prepare and launch disposable RimWorld copies with isolated data and logs.

Preparation only copies files and writes a disposable profile. Runtime probes
can extend that copy before launch. A successful startup is never treated as
proof that a translated string was displayed in the game's user interface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Iterable, Mapping
import uuid
import xml.etree.ElementTree as ET

from .core import PACKAGE, atomic_write, writable_destination, xml_bytes
from .installation import ModDiagnostic, ModMetadata, diagnose_load_order, owned_mod_files, read_mod_metadata
from .languages import validate_language
from .platforms import GameInstallation


TEST_MARKER = ".rimworld-translator-game-test.json"


@dataclass(frozen=True)
class GameTestPlan:
    root: Path
    game: Path
    executable: Path
    savedata: Path
    player_log: Path
    stdout_log: Path
    report_path: Path
    argv: tuple[str, ...]
    active_packages: tuple[str, ...]
    translation_id: str
    language: str
    diagnostics: tuple[ModDiagnostic, ...]
    language_folder_name: str = ""


@dataclass(frozen=True)
class GameTestReport:
    process_started: bool
    process_exit_code: int | None
    cancelled: bool
    timed_out: bool
    launch_error: str
    runtime_seconds: float
    game_version_loaded: bool
    isolated_savedatafolder_confirmed: bool
    display_verified: bool
    player_log: Path
    stdout_log: Path
    report_path: Path
    diagnostic_lines: tuple[str, ...]
    screenshots: tuple[Path, ...]
    requested_language: str = ""
    configured_language_folder: str = ""


def resolve_game_language(game: Path | str, language: str) -> str:
    """Resolve a language ID to the installed name RimWorld expects in Prefs.

    Modern Core archives use names such as ``Japanese (日本語).tar``. RimWorld
    selects the exact virtual folder name ``Japanese (日本語)`` from Prefs and
    separately accepts ``Japanese`` as a legacy folder for exported MOD data.
    LanguageInfo display labels do not override that selection identity.
    """
    language = validate_language(language)
    data = Path(game) / "Data"
    roots = [data / "Core/Languages"]
    if data.is_dir():
        roots.extend(folder / "Languages" for folder in sorted(data.iterdir())
                     if folder.is_dir() and folder.name != "Core")
    for root in roots:
        if not root.is_dir():
            continue
        names = []
        for item in root.iterdir():
            if item.is_symlink():
                continue
            if item.is_dir():
                names.append(item.name)
            elif item.is_file() and item.suffix.casefold() == ".tar":
                names.append(item.stem)
        canonical = sorted(name for name in names if name.startswith(language + " (") and name.endswith(")"))
        if canonical:
            return canonical[0]
        if language in names:
            return language
    raise ValueError(f"ゲーム内に「{language}」の言語データが見つかりません。ゲームに言語データを導入するか、導入済みの言語を選んでください")


def _order_packages(metadata: dict[str, ModMetadata], requested: list[str]) -> tuple[str, ...]:
    selected = []
    pending = list(dict.fromkeys(requested))
    while pending:
        ident = pending.pop(0)
        if ident in selected:
            continue
        if ident not in metadata:
            raise ValueError(f"隔離テストに必要なMODを追加してください: {ident}")
        selected.append(ident)
        pending.extend(dep.package_id for dep in metadata[ident].dependencies if dep.package_id in metadata)
    prerequisites = {ident: set() for ident in selected}
    for ident in selected:
        mod = metadata[ident]
        prerequisites[ident].update(dep.package_id for dep in mod.dependencies if dep.package_id in prerequisites)
        prerequisites[ident].update(dep for dep in mod.load_after if dep in prerequisites)
        for after in mod.load_before:
            if after in prerequisites:
                prerequisites[after].add(ident)
    ordered = []
    while len(ordered) < len(selected):
        ready = next((ident for ident in selected if ident not in ordered and prerequisites[ident].issubset(ordered)), None)
        if ready is None:
            raise ValueError("MODの依存関係・読み込み順が循環しています。MODの構成を確認してください")
        ordered.append(ready)
    return tuple(ordered)


def prepare_game_test(
    installation: GameInstallation, generated_mod: Path | str, destination: Path | str, *,
    source_mods: Iterable[Path | str] = (), active_packages: Iterable[str] = (), language: str = "Japanese",
) -> GameTestPlan:
    """Copy game/source mods and create a fresh, disposable profile; do not launch.

    Existing local Mods are deliberately omitted from the copy. Supply source
    and dependency folders explicitly; official DLC dependencies are included
    when present. An existing nonempty destination is never replaced.
    """
    language = validate_language(language)
    original = installation.root.resolve(strict=True)
    executable = installation.executable
    if executable is None or not executable.is_file():
        raise ValueError("RimWorldの実行ファイルが見つかりません。ゲームのフォルダを確認してください")
    try:
        executable_relative = executable.resolve().relative_to(original)
    except ValueError:
        raise ValueError("ゲームの実行ファイルはゲームフォルダ内にある必要があります") from None
    language_folder_name = resolve_game_language(original, language)
    generated = Path(generated_mod).absolute()
    owned_mod_files(generated)
    translation = read_mod_metadata(generated)
    sources = [Path(path).resolve(strict=True) for path in source_mods]
    destination = writable_destination(Path(destination), original)
    for protected in (generated, *sources):
        writable_destination(destination, protected)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("隔離テスト用に新しい空のフォルダを選んでください")
    metadata = {}
    data = original / "Data"
    if data.is_dir():
        for folder in data.iterdir():
            if folder.is_dir() and (folder / "About/About.xml").is_file():
                mod = read_mod_metadata(folder)
                metadata[mod.package_id] = mod
    source_ids = []
    local_sources = []
    for source in sources:
        mod = read_mod_metadata(source)
        if mod.package_id == translation.package_id:
            raise ValueError("元MODと翻訳MODのpackageIdを分けてください")
        if mod.package_id in metadata:
            if metadata[mod.package_id].root != source:
                raise ValueError(f"同じpackageIdの元MODが複数あります: {mod.package_id}")
        else:
            metadata[mod.package_id] = mod
            local_sources.append(mod)
        source_ids.append(mod.package_id)
    metadata[translation.package_id] = translation
    requested = []
    for value in active_packages:
        if not isinstance(value, str) or not PACKAGE.fullmatch(value):
            raise ValueError("テスト対象のpackageIdが不正です")
        requested.append(value.casefold())
    base = ["ludeon.rimworld"] if "ludeon.rimworld" in metadata else []
    packages = _order_packages(metadata, [*base, *source_ids, *requested, translation.package_id])
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rwt-test-", dir=destination.parent))
    originally_empty = destination.exists()
    try:
        game = staging / "game"
        def ignore(folder: str, names: list[str]) -> list[str]:
            return ["Mods"] if Path(folder).resolve() == original and "Mods" in names else []
        # Follow links into independent files; never retain writable links back
        # into the installed game or Workshop packages.
        shutil.copytree(original, game, symlinks=False, ignore=ignore)
        mods = game / "Mods"
        mods.mkdir(exist_ok=True)
        for mod in local_sources:
            shutil.copytree(mod.root, mods / ("source-" + mod.package_id), symlinks=False)
        translated = mods / ("translation-" + translation.package_id)
        shutil.copytree(generated, translated, symlinks=False)
        savedata = staging / "isolated-user-data"
        config = savedata / "Config"
        mods_config = ET.Element("ModsConfigData")
        if installation.version:
            ET.SubElement(mods_config, "version").text = installation.version
        active = ET.SubElement(mods_config, "activeMods")
        for ident in packages:
            ET.SubElement(active, "li").text = ident
        atomic_write(config / "ModsConfig.xml", xml_bytes(mods_config))
        preferences = ET.Element("PrefsData")
        for tag, text in (("langFolderName", language_folder_name), ("runInBackground", "True"), ("resetModsConfigOnCrash", "False")):
            ET.SubElement(preferences, tag).text = text
        atomic_write(config / "Prefs.xml", xml_bytes(preferences))
        diagnostics = tuple(diagnose_load_order(translated, [item.root for item in metadata.values() if item.package_id != translation.package_id],
                                               config / "ModsConfig.xml"))
        atomic_write(staging / TEST_MARKER, (json.dumps({
            "schema": 1, "owner": "rimworld-translator", "time": datetime.now(timezone.utc).isoformat(),
            "original_game": str(original), "translation_id": translation.package_id,
            "source_mods": [str(source) for source in sources], "active_packages": list(packages),
            "requested_language": language, "configured_language_folder": language_folder_name,
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        if originally_empty:
            destination.rmdir()
        try:
            os.replace(staging, destination)
        except BaseException:
            if originally_empty and not destination.exists():
                destination.mkdir()
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    game = destination / "game"
    savedata = destination / "isolated-user-data"
    executable = game / executable_relative
    player_log = destination / "Player.log"
    argv = (str(executable), "-savedatafolder=" + str(savedata), "-logFile", str(player_log),
            "-screen-fullscreen", "0", "-screen-width", "1024", "-screen-height", "768")
    return GameTestPlan(destination, game, executable, savedata, player_log,
                        destination / "runtime-stdout.log", destination / "runtime-report.json",
                        argv, packages, translation.package_id, language, diagnostics, language_folder_name)


def _validate_plan(plan: GameTestPlan) -> None:
    marker = plan.root / TEST_MARKER
    if marker.is_symlink():
        raise ValueError("隔離テストの所有情報が不正です")
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    if metadata.get("schema") != 1 or metadata.get("owner") != "rimworld-translator":
        raise ValueError("エディターで準備した隔離テストを選んでください")
    for path in (plan.game, plan.executable, plan.savedata, plan.player_log, plan.stdout_log, plan.report_path):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("隔離テストにシンボリックリンクがあります")
        if plan.root.resolve() not in path.resolve().parents:
            raise ValueError("隔離テストの出力先がテストフォルダ外にあります")
    if plan.game.resolve() not in plan.executable.resolve().parents:
        raise ValueError("コピーされたゲームの実行ファイルを選んでください")
    savedata_args = [arg for arg in plan.argv if arg.startswith("-savedatafolder=")]
    if not plan.argv or plan.argv[0] != str(plan.executable) or savedata_args != ["-savedatafolder=" + str(plan.savedata)]:
        raise ValueError("隔離した保存データの引数がありません")
    if plan.argv.count("-logFile") != 1:
        raise ValueError("隔離したログファイルの引数がありません")
    index = plan.argv.index("-logFile")
    if index + 1 >= len(plan.argv) or plan.argv[index + 1] != str(plan.player_log):
        raise ValueError("隔離したログファイルの出力先が不正です")


def _cancelled(cancel) -> bool:
    if cancel is None:
        return False
    return bool(cancel() if callable(cancel) else cancel.is_set())


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _read_log(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 4 * 1024 * 1024))
        return stream.read().decode("utf-8", errors="replace")


def _rotate_logs(plan: GameTestPlan) -> None:
    paths = [path for path in (plan.player_log, plan.stdout_log, plan.report_path) if path.exists()]
    if not paths:
        return
    previous = plan.root / "previous-runs"
    if previous.is_symlink() or (previous.exists() and not previous.is_dir()):
        raise ValueError("前回のテスト記録を保存するフォルダを確認してください")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = previous / (stamp + "-" + uuid.uuid4().hex[:12])
    archive.mkdir(parents=True)
    for path in paths:
        os.replace(path, archive / path.name)
    old_report = archive / plan.report_path.name
    if old_report.is_file():
        try:
            data = json.loads(old_report.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            return
        if isinstance(data, dict):
            for key, path in (("player_log", plan.player_log), ("stdout_log", plan.stdout_log), ("report_path", plan.report_path)):
                if key in data:
                    data[key] = str(archive / path.name)
            atomic_write(old_report, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def launch_game_test(
    plan: GameTestPlan, *, timeout: float = 120,
    cancel: Callable[[], bool] | object | None = None, env: Mapping[str, str] | None = None,
    screenshot_paths: Iterable[Path | str] = (),
) -> GameTestReport:
    """Run the prepared copy, collect logs and stop on timeout/cancellation.

    ``cancel`` may be a threading.Event or a callable. Call from a GUI worker.
    Supplied screenshots are copied into the disposable report folder but do
    not set display_verified; real UI inspection is a separate evidence step.
    """
    _validate_plan(plan)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("テストの制限時間は正の秒数で指定してください")
    start = time.monotonic()
    was_cancelled = _cancelled(cancel)
    _rotate_logs(plan)
    timed_out = False
    launch_error = ""
    process = None
    if not was_cancelled:
        with plan.stdout_log.open("wb") as output:
            try:
                process = subprocess.Popen(plan.argv, cwd=plan.game,
                                           env=dict(env) if env is not None else None,
                                           stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
            except OSError as exc:
                launch_error = str(exc)
            if process is not None:
                try:
                    while process.poll() is None:
                        if _cancelled(cancel):
                            was_cancelled = True
                            break
                        if time.monotonic() - start >= timeout:
                            timed_out = True
                            break
                        time.sleep(0.05)
                finally:
                    _stop(process)
    screenshots = []
    for source in screenshot_paths:
        source = Path(source)
        if source.is_symlink() or not source.is_file() or source.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("スクリーンショットはPNGまたはJPEGの画像ファイルを選んでください")
        target = plan.root / "screenshots" / (uuid.uuid4().hex + source.suffix.casefold())
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        screenshots.append(target)
    player = _read_log(plan.player_log)
    stdout = _read_log(plan.stdout_log)
    lines = tuple(line.strip() for line in (player + "\n" + stdout).splitlines()
                  if any(word in line.casefold() for word in ("error", "exception", "failed", "dependency", "translation", "missing")))[:100]
    report = GameTestReport(process is not None, process.returncode if process is not None else None,
                            was_cancelled, timed_out, launch_error, round(time.monotonic() - start, 3),
                            bool(re.search(r"\bRimWorld\s+\d+\.\d+", player)),
                            "Save data folder overridden to " + str(plan.savedata) in player,
                            False, plan.player_log, plan.stdout_log, plan.report_path, lines, tuple(screenshots),
                            plan.language, plan.language_folder_name)
    atomic_write(plan.report_path, (json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    return report
