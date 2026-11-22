"""Launch a copied RimWorld game against a disposable mod set and collect diagnostics.

Does not alter Steam's game/mod files, original ModsConfig.xml or any save.
Unity may update its ordinary Player.log even with -savedatafolder; a copy
of that log is retained in artifacts/live-game-test for inspection.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rimworld_translator.core import Project, export_mod
from prepare_live_game import prepare

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "artifacts/live-game-test"
EXECUTABLE = ROOT / "game/RimWorldLinux"
ISOLATED_DATA = ROOT / "isolated-user-data"
TRANSLATION = ROOT / "game/Mods/rwtest-generated-translation"
PROJECT = ROOT / "generated-project/project.json"
LOG = Path.home() / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Player.log"

def main():
    if not EXECUTABLE.is_file() or not PROJECT.is_file():
        prepare()
    project = Project.load(PROJECT)
    export_mod(project, TRANSLATION)
    assert ET.parse(TRANSLATION / "About/About.xml").getroot().findtext(
        "modDependencies/li/steamWorkshopUrl"
    ), "Missing workshop dependency URL"
    mods_config = ET.parse(ISOLATED_DATA / "Config/ModsConfig.xml").getroot()
    active = [e.text.lower() for e in mods_config.findall("activeMods/li") if e.text]
    assert project.original_package_id.lower() in active
    assert project.package_id.lower() in active
    original_config = Path.home() / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml"
    config_before = original_config.read_bytes() if original_config.exists() else None
    current = LOG.read_bytes() if LOG.exists() else None
    env = dict(os.environ)
    env.update({"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-1",
                "DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"})
    argv = [str(EXECUTABLE), f"-savedatafolder={ISOLATED_DATA}", "-screen-fullscreen", "0",
            "-screen-width", "900", "-screen-height", "650"]
    with (ROOT / "runtime-stdout.log").open("wb") as out:
        start = time.monotonic()
        with subprocess.Popen(argv, cwd=EXECUTABLE.parent, env=env,
                              stdout=out, stderr=subprocess.STDOUT) as proc:
            try:
                proc.wait(timeout=70)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.terminate()
                try: proc.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            elapsed = round(time.monotonic() - start, 1)
            exitcode = proc.returncode
    player = LOG.read_bytes() if LOG.exists() else b""
    (ROOT / "runtime-Player.log").write_bytes(player)
    text = player.decode("utf-8", errors="replace")
    lower = text.lower()
    warnings = [line.strip() for line in text.splitlines()
                if any(v in line.lower() for v in
                       ("dependency", "error", "exception", "translation", "wrong", "failed"))]
    report = {
        "game_version_loaded": "RimWorld 1.6." in text,
        "isolated_savedatafolder_used": f"Save data folder overridden to {ISOLATED_DATA}" in text,
        "source_and_translation_enabled_in_isolated_config": True,
        "translated_def_file_exists": (TRANSLATION / "Languages/Japanese/DefInjected/ThingDef/Translations.xml").is_file(),
        "no_missing_dependency_link_warning": "needs to have <downloadUrl>" not in text,
        "runtime_japanese_def_value_directly_observed": False,
        "graphics_startup": "OPENGL LOG: Creating OpenGL" in text,
        "process_exit_code": exitcode,
        "stopped_after_time_limit": timed_out,
        "runtime_seconds": elapsed,
        "diagnostic_lines": warnings[:20],
        "original_player_log_existed_before": current is not None,
        "ordinary_mods_config_unchanged": (
            (original_config.read_bytes() if original_config.exists() else None) == config_before
        ),
        "note": "Unity writes its normal Player.log even with isolated save data; existing saves and ModsConfig.xml are not modified"
    }
    (ROOT / "runtime-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    import argparse
    # Parsing first keeps --help from launching the game.
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                            epilog="Takes no options; launches the copied game for about 70 seconds.").parse_args()
    main()
