"""Opt-in real RimWorld UI proof using a disposable diagnostic MOD.

Requires a legally installed game and real source MODs. The image is captured
by Unity from the actual game's framebuffer, so unrelated desktop windows
cannot appear. A loaded-value match and independently OCR-visible marker are
reported separately. This proves diagnostic UI rendering, not gameplay UI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rimworld_translator.core import Project, Scan, atomic_write, export_mod, scan_mod, writable_destination, xml_bytes
from rimworld_translator.game_testing import prepare_game_test
from rimworld_translator.platforms import GameInstallation
from tools.build_runtime_probe import build_probe

DEFAULT_SOURCES = ("3687005016", "3659157288", "3669656495", "3670495115", "3714807736", "3780459800")
PROBE_ID = "local.rimworldtranslator.runtimeproof"


def select_label(scan: Scan):
    candidates = [entry for entry in scan.entries if entry.kind == "DefInjected" and entry.group == "ThingDef"
                  and entry.key.endswith(".label") and entry.key.count(".") == 1
                  and not (entry.blocked or entry.excluded or entry.stale)
                  and not re.search(r"\{[^}]+\}|<[^>]+>", entry.english)]
    if not candidates:
        raise ValueError("No unblocked top-level ThingDef.label suitable for runtime proof")
    return candidates[0]


def _dimensions(image: Path) -> tuple[int, int] | None:
    if not image.is_file():
        return None
    with image.open("rb") as source:
        if source.read(8) != b"\x89PNG\r\n\x1a\n":
            return None
    from PySide6.QtGui import QImage
    frame = QImage(str(image))
    if frame.isNull() or min(frame.width(), frame.height()) < 100:
        return None
    return frame.width(), frame.height()


def evaluate_evidence(expected: list[dict], probe: dict, image: Path, ocr_text: str) -> dict:
    """Classify independent fixture/value/image evidence; do not trust probe flags."""
    dimensions = _dimensions(image)
    observed = {(item.get("source_id"), item.get("def_name")): item for item in probe.get("observations", [])}
    samples = []
    for fixture in expected:
        item = observed.get((fixture["source_id"], fixture["def_name"]), {})
        actual = item.get("actual")
        match = item.get("found") is True and actual == fixture["expected"]
        marker = re.match(r"SOLPROOF\d{2}\b", fixture["expected"])
        # RimWorld's font makes 0/O and 1/I/l ambiguous to ASCII OCR. Limit
        # normalization to exactly the two-character numeric marker suffix.
        normalized_ocr = re.sub(r'\bSOLPROOF([0-9OIl]{2})\b',
                                lambda m:'SOLPROOF'+m[1].translate(str.maketrans({'O':'0','I':'1','l':'1'})),ocr_text)
        visible = bool(dimensions and marker and re.search(r"\b" + re.escape(marker[0]) + r"\b", normalized_ocr))
        samples.append({**fixture, "actual": actual, "injection_match": match,
                        "marker_visible_in_screenshot": visible, "display_verified": match and visible})
    injection = bool(samples) and all(item["injection_match"] for item in samples)
    display = bool(samples) and all(item["display_verified"] for item in samples)
    return {"evidence_kind": "diagnostic_actual_game_window", "injection_verified": injection,
            "display_verified": display, "display_verified_samples": sum(item["display_verified"] for item in samples),
            "sample_count": len(samples), "samples": samples,
            "screenshot": str(image) if dimensions else None, "screenshot_dimensions": dimensions,
            "screenshot_sha256": hashlib.sha256(image.read_bytes()).hexdigest() if dimensions else None,
            "ocr_text": ocr_text,
            "scope": "Actual loaded ThingDef.label values displayed by a diagnostic Verse.Window. Normal gameplay UI is not tested."}


def _write_json(path: Path, value) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def prepare(root: Path, game: Path, workshop: Path, source_ids: list[str], dependencies: list[Path], cache: Path) -> dict:
    root = root.resolve()
    game = game.resolve(strict=True)
    writable_destination(root, game)
    writable_destination(root, workshop.resolve(strict=True))
    if (root / "setup.json").exists():
        raise ValueError("This proof already exists; use --reuse to rerun it or choose a new --root")
    root.mkdir(parents=True, exist_ok=True)
    expected, exports, projects, sources = [], [], [], []
    for index, source_id in enumerate(source_ids, 1):
        source = (workshop / source_id).resolve(strict=True)
        scanned = scan_mod(source)
        project = Project.create(source, scanned)
        label = select_label(scanned)
        text = f"SOLPROOF{index:02d} 翻訳実機装備{index:02d}"
        project.set_translation(label.id, text)
        label.review = False
        project_path = root / "projects" / source_id / "project.json"
        project.save(project_path)
        generated = project_path.parent / "translation"
        export_mod(project, generated)
        definition = label.key[:-len(".label")]
        catalog = generated / "Languages/Japanese/DefInjected/ThingDef/Translations.xml"
        catalog_value = ET.parse(catalog).getroot().findtext(label.key)
        if catalog_value != text:
            raise AssertionError(f"Canonical exported translation did not match fixture: {catalog}")
        expected.append({"source_id": source_id, "mod_name": project.name, "def_name": definition,
                         "key": label.key, "english": label.english, "expected": text,
                         "source_package_id": project.original_package_id,
                         "translation_package_id": project.package_id,
                         "exported_catalog": str(catalog), "project": str(project_path)})
        exports.append(generated)
        projects.append(project)
        sources.append(source)
    executable = game / ("RimWorldLinux" if sys.platform != "win32" else "RimWorldWin64.exe")
    installation = GameInstallation(game, game / "Mods", workshop, "1.6.0", executable)
    plan = prepare_game_test(installation, exports[0], root / "isolated-run",
                             source_mods=[*sources, *dependencies], language="Japanese")
    prefs_path = plan.savedata / "Config/Prefs.xml"
    prefs = ET.parse(prefs_path).getroot()
    for tag, value in (("screenWidth", "1024"), ("screenHeight", "768"), ("fullscreen", "False")):
        ET.SubElement(prefs, tag).text = value
    atomic_write(prefs_path, xml_bytes(prefs))
    active = list(plan.active_packages)
    for project, exported in zip(projects[1:], exports[1:]):
        destination = plan.game / "Mods" / ("translation-" + project.package_id)
        shutil.copytree(exported, destination, symlinks=False)
        active.append(project.package_id.lower())
    build_probe(game, plan.game / "Mods/runtime-proof", cache)
    active.append(PROBE_ID)
    config_path = plan.savedata / "Config/ModsConfig.xml"
    xml = ET.parse(config_path).getroot()
    node = xml.find("activeMods")
    node.clear()
    for package in active:
        ET.SubElement(node, "li").text = package
    atomic_write(config_path, xml_bytes(xml))
    # The diagnostic popup is deliberately last, above normal menus and startup dialogs.
    probe_report = plan.root / "probe-observations.json"
    screenshot = plan.root / "game-translation-proof.png"
    fixture = plan.root / "proof-fixture.xml"
    fixture_xml = ET.Element("TranslationProof", {"report": str(probe_report), "screenshot": str(screenshot)})
    for item in expected:
        ET.SubElement(fixture_xml, "Item", {"sourceId": item["source_id"], "modName": item["mod_name"],
                                           "defName": item["def_name"]}).text = item["expected"]
    atomic_write(fixture, xml_bytes(fixture_xml))
    setup = {"schema": 1, "prepared_at": datetime.now(timezone.utc).isoformat(), "root": str(root),
             "original_game": str(game), "original_workshop": str(workshop), "isolated_root": str(plan.root),
             "game": str(plan.game), "executable": str(plan.executable), "savedata": str(plan.savedata),
             "player_log": str(plan.player_log), "stdout_log": str(plan.stdout_log),
             "argv": [*plan.argv, "-rwt-proof-fixture=" + str(fixture)], "active_packages": active,
             "expected": expected, "probe_report": str(probe_report), "screenshot": str(screenshot),
             "dependencies": [str(path.resolve()) for path in dependencies]}
    _write_json(root / "setup.json", setup)
    return setup


def _original_state() -> dict:
    original = Path.home() / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios"
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in (original / "Config/ModsConfig.xml", original / "Player.log")}


def run(setup: dict, timeout: float) -> dict:
    root = Path(setup["root"])
    image, probe_path = Path(setup["screenshot"]), Path(setup["probe_report"])
    # Retain earlier proof artifacts on a repeat; never classify stale files as this run's evidence.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for path in (image, probe_path, Path(setup["player_log"]), Path(setup["stdout_log"]), root / "runtime-ui-report.json"):
        if path.exists():
            archive = root / "previous-runs" / stamp
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), archive / path.name)
    original_before = _original_state()
    environment = dict(os.environ)
    if sys.platform != "win32":
        environment.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
        environment.setdefault("WAYLAND_DISPLAY", "wayland-1")
        environment.setdefault("DISPLAY", ":0")
        environment.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    argv = list(setup["argv"])
    network_isolated = False
    network_namespace = None
    if sys.platform.startswith("linux"):
        # Steam's SDK can submit an assert minidump on shutdown. Isolate only
        # this disposable game process; never change the host network setup.
        unshare = shutil.which("unshare")
        if unshare is None:
            raise RuntimeError("This real-game proof needs unshare for an offline disposable runtime")
        # Mapped as the current user, not root: RimWorld 1.6.4871 segfaults within a second when it runs as uid 0.
        check = subprocess.run([unshare, "--user", "--map-current-user", "--net", "--", "true"],
                               capture_output=True, text=True, timeout=10)
        if check.returncode:
            raise RuntimeError("Disposable game network isolation failed: " + check.stderr.strip())
        argv = [unshare, "--user", "--map-current-user", "--net", "--", *argv]
        network_isolated = True
    started = time.monotonic()
    process = None
    timed_out = False
    error = ""
    with Path(setup["stdout_log"]).open("wb") as output:
        try:
            process = subprocess.Popen(argv, cwd=setup["game"], env=environment,
                                       stdout=output, stderr=subprocess.STDOUT)
            print(f"Launched disposable RimWorld PID {process.pid}; waiting for actual UI screenshot", flush=True)
            while process.poll() is None:
                if network_isolated and network_namespace is None:
                    try:
                        child_namespace = os.readlink(f"/proc/{process.pid}/ns/net")
                        own_namespace = os.readlink("/proc/self/ns/net")
                        if child_namespace != own_namespace:
                            network_namespace = child_namespace
                    except OSError:
                        pass
                if image.is_file() and image.stat().st_size > 0 and probe_path.is_file() and _dimensions(image):
                    # Let the asynchronous frame write complete before terminating this exact process.
                    time.sleep(1)
                    break
                if time.monotonic() - started >= timeout:
                    timed_out = True
                    break
                time.sleep(1)
        except OSError as exception:
            error = str(exception)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    elapsed = round(time.monotonic() - started, 1)
    probe = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.is_file() else {}
    ocr_text, ocr_error = "", ""
    tesseract = shutil.which("tesseract")
    if _dimensions(image) and tesseract:
        # ASCII marker OCR remains independent of installed Japanese OCR language packs.
        try:
            ocr = subprocess.run([tesseract, str(image), "stdout", "-l", "eng", "--psm", "6"],
                                 capture_output=True, text=True, encoding="utf-8", timeout=45)
            ocr_text = ocr.stdout
            ocr_error = ocr.stderr if ocr.returncode else ""
        except subprocess.TimeoutExpired:
            # A slow OCR pass must not discard the game evidence already on disk.
            ocr_error = "tesseract timed out; display remains unverified"
    elif not tesseract:
        ocr_error = "tesseract is unavailable; display remains unverified"
    atomic_write(root / "screenshot-ocr.txt", ocr_text.encode("utf-8"))
    player_log = Path(setup["player_log"])
    log = player_log.read_text(encoding="utf-8", errors="replace") if player_log.is_file() else ""
    report = evaluate_evidence(setup["expected"], probe, image, ocr_text)
    report.update({"started_at": stamp, "platform": sys.platform, "process_started": process is not None,
                   "process_id": process.pid if process is not None else None,
                   "process_exit_code": process.returncode if process is not None else None,
                   "launch_command": argv, "network_isolation_requested": network_isolated,
                   "network_namespace": network_namespace,
                   "stopped_after_time_limit": timed_out, "runtime_seconds": elapsed, "launch_error": error,
                   "player_log": str(player_log), "stdout_log": setup["stdout_log"],
                   "game_version_loaded": "RimWorld 1.6." in log,
                   "isolated_savedatafolder_confirmed": "Save data folder overridden to " + setup["savedata"] in log,
                   "original_profile_unchanged": original_before == _original_state(),
                   "original_profile_before_sha256": original_before, "original_profile_after_sha256": _original_state(),
                   "ocr_error": ocr_error, "probe_report": str(probe_path), "active_packages": setup["active_packages"],
                   "active_language": probe.get("active_language"),
                   "diagnostic_lines": [line.strip() for line in log.splitlines()
                                        if any(term in line.lower() for term in ("error", "exception", "failed", "dependency", "rwt-proof"))][:60]})
    _write_json(root / "runtime-ui-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "artifacts/sol-runtime")
    parser.add_argument("--game", type=Path, default=Path.home() / ".local/share/Steam/steamapps/common/RimWorld")
    parser.add_argument("--workshop", type=Path, default=Path.home() / ".local/share/Steam/steamapps/workshop/content/294100")
    parser.add_argument("--source-id", action="append")
    parser.add_argument("--dependency", action="append", type=Path, default=[])
    parser.add_argument("--compiler-cache", type=Path, default=ROOT / "artifacts/sol-runtime/compiler")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    if not 15 <= args.timeout <= 900:
        parser.error("--timeout must be between 15 and 900 seconds")
    if args.reuse:
        setup = json.loads((args.root / "setup.json").read_text(encoding="utf-8"))
    else:
        setup = prepare(args.root, args.game, args.workshop, args.source_id or list(DEFAULT_SOURCES),
                        args.dependency, args.compiler_cache)
    if args.prepare_only:
        print(json.dumps(setup, indent=2, ensure_ascii=False))
        return
    report = run(setup, args.timeout)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["display_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
