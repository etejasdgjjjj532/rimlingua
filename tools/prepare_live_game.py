"""Create the isolated live RimWorld translation integration fixture from installed content."""
from pathlib import Path
import json
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rimworld_translator.core import Project, scan_mod, export_mod

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "artifacts/live-game-test"
WORKSHOP_SOURCE = Path.home() / ".local/share/Steam/steamapps/workshop/content/294100/3687005016"
STEAM_GAME = Path.home() / ".local/share/Steam/steamapps/common/RimWorld"

def prepare() -> dict:
    if not WORKSHOP_SOURCE.is_dir() or not STEAM_GAME.is_dir():
        raise RuntimeError("RimWorld game and workshop sample must be installed via Steam")
    ROOT.mkdir(parents=True, exist_ok=True)
    sandbox_game = ROOT / "game"
    if not sandbox_game.exists():
        shutil.copytree(STEAM_GAME, sandbox_game, symlinks=True)
    original = sandbox_game / "Mods/rwtest-original-rimfront"
    if not original.exists():
        shutil.copytree(WORKSHOP_SOURCE, original)
    project_path = ROOT / "generated-project/project.json"
    if project_path.exists():
        project = Project.load(project_path)
    else:
        scanned = scan_mod(WORKSHOP_SOURCE)
        project = Project.create(WORKSHOP_SOURCE, scanned)
        candidates = [e for e in project.entries if e.key.endswith(".label")
                      and e.kind == "DefInjected" and not e.blocked]
        if not candidates:
            raise RuntimeError("No translatable label found in workshop sample")
        candidates[0].japanese = "翻訳実機テスト装備"
        candidates[0].review = False
        project.save(project_path)
    export_mod(project, sandbox_game / "Mods/rwtest-generated-translation")
    config_dir = ROOT / "isolated-user-data/Config"
    config_dir.mkdir(parents=True, exist_ok=True)
    prefs = config_dir / "Prefs.xml"
    if not prefs.exists():
        node = ET.Element("PrefsData")
        ET.SubElement(node, "langFolderName").text = "Japanese"
        ET.SubElement(node, "runInBackground").text = "True"
        ET.SubElement(node, "resetModsConfigOnCrash").text = "False"
        ET.ElementTree(node).write(prefs, encoding="utf-8", xml_declaration=True)
    config = config_dir / "ModsConfig.xml"
    if not config.exists():
        node = ET.Element("ModsConfigData")
        ET.SubElement(node, "version").text = "1.6.0"
        active = ET.SubElement(node, "activeMods")
        for name in ["ludeon.rimworld", project.original_package_id.lower(),
                     project.package_id.lower()]:
            ET.SubElement(active, "li").text = name
        ET.ElementTree(node).write(config, encoding="utf-8", xml_declaration=True)
    result = {
        "source": str(WORKSHOP_SOURCE),
        "sandbox_game": str(sandbox_game),
        "project": str(project_path),
        "source_id": project.original_package_id,
        "translation_id": project.package_id,
        "language": "Japanese",
    }
    (ROOT / "setup.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result

if __name__ == "__main__":
    import argparse
    # Parsing first keeps --help from copying the game.
    argparse.ArgumentParser(description=__doc__ + " Takes no options; copies the installed game into "
                            "artifacts/live-game-test on first use.").parse_args()
    print(json.dumps(prepare(), indent=2, ensure_ascii=False))
