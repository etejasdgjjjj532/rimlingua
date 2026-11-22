"""Do translations under handle keys (stages.<label>.label) reach list items in a running game?

    python tools/run_tests.py --script tools/verify_handle_keys_live.py --root artifacts/handle-keys-live

Builds a small MOD of our own (HediffDef / ThoughtDef with stages, one duplicated label, one label with a space),
scans it against the installed game's field table, exports a Japanese translation MOD through the editor's own
export, and starts a disposable copy of the game with a diagnostic window (tools/runtime_probe) that reads the
loaded stage labels. A control Def is translated under the old index key (stages.0.label); the game is expected
to leave it in English. Nothing here is a normal gameplay screen. The installed game, Workshop MODs and the real
profile are only read.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rimworld_translator.core import Project, atomic_write, export_mod, export_shared, scan_mod, xml_bytes  # noqa: E402
from rimworld_translator.game_testing import prepare_game_test  # noqa: E402
from rimworld_translator.platforms import GameInstallation  # noqa: E402
from rimworld_translator.schema import schema_from_assemblies  # noqa: E402
from tools import verify_runtime_ui as runtime  # noqa: E402
from tools.build_runtime_probe import build_probe  # noqa: E402

SOURCE_ID = 'test.rwt.livehandle'
CONTROL_ID = 'test.rwt.livehandle.control'
# (Def type, defName, stage index, English label, translation sent under the handle key; None for the control)
ITEMS = [
    ('HediffDef', 'RwtLiveHediff', 0, 'Initial', 'ハンドル検証 初期'),
    ('HediffDef', 'RwtLiveHediff', 1, 'Severe pain', 'ハンドル検証 激痛'),
    ('HediffDef', 'RwtLiveHediff', 2, 'Worse', 'ハンドル検証 悪化A'),
    ('HediffDef', 'RwtLiveHediff', 3, 'Worse', 'ハンドル検証 悪化B'),
    ('ThoughtDef', 'RwtLiveThought', 0, 'Cheerful', 'ハンドル検証 上機嫌'),
    ('ThoughtDef', 'RwtLiveThought', 1, 'Gloomy', 'ハンドル検証 陰気'),
    ('HediffDef', 'RwtLiveControl', 0, 'Control stage', None),
]


def write_source(folder: Path, versions=('1.6',)) -> None:
    (folder / 'About').mkdir(parents=True)
    (folder / 'Defs').mkdir()
    supported = ''.join(f'<li>{v}</li>' for v in versions)
    (folder / 'About/About.xml').write_text(
        f'<ModMetaData><name>RWT live handle test</name><author>test</author><packageId>{SOURCE_ID}</packageId>'
        f'<supportedVersions>{supported}</supportedVersions><description>Test MOD for handle keys.</description>'
        '</ModMetaData>', encoding='utf-8')

    def hediff_stages(name):
        return ''.join(f'<li><minSeverity>{index}</minSeverity><label>{label}</label></li>'
                       for index, (_, owner, _, label, _) in enumerate(i for i in ITEMS if i[1] == name)
                       for owner in [owner])
    thought = ''.join(f'<li><label>{label}</label><description>desc</description><baseMoodEffect>1</baseMoodEffect></li>'
                      for _, name, _, label, _ in ITEMS if name == 'RwtLiveThought')
    (folder / 'Defs/test.xml').write_text(
        '<Defs>'
        '<HediffDef><defName>RwtLiveHediff</defName><label>live</label><hediffClass>Hediff</hediffClass>'
        f'<stages>{hediff_stages("RwtLiveHediff")}</stages></HediffDef>'
        '<HediffDef><defName>RwtLiveControl</defName><label>control</label><hediffClass>Hediff</hediffClass>'
        f'<stages>{hediff_stages("RwtLiveControl")}</stages></HediffDef>'
        f'<ThoughtDef><defName>RwtLiveThought</defName><durationDays>1</durationDays><stages>{thought}</stages></ThoughtDef>'
        '</Defs>', encoding='utf-8')


def write_control(folder: Path) -> None:
    (folder / 'About').mkdir(parents=True)
    (folder / 'About/About.xml').write_text(
        f'<ModMetaData><name>RWT control</name><author>test</author><packageId>{CONTROL_ID}</packageId>'
        '<supportedVersions><li>1.6</li></supportedVersions><description>Index-key control.</description></ModMetaData>',
        encoding='utf-8')
    catalog = folder / 'Languages/Japanese/DefInjected/HediffDef'
    catalog.mkdir(parents=True)
    # The pre-change export wrote index keys; the game is expected to ignore this one.
    (catalog / 'Control.xml').write_text(
        '<?xml version="1.0" encoding="utf-8"?><LanguageData>'
        '<RwtLiveControl.stages.0.label>ハンドル検証 番号キー（当たらない想定）</RwtLiveControl.stages.0.label></LanguageData>',
        encoding='utf-8')


def handle_key(by_key, name, stage, label):
    """The handle-keyed entry for a stage: spaces become '_', duplicate labels are suffixed -0 / -1 in order."""
    handle = label.replace(' ', '_')
    for candidate in (f'{name}.stages.{handle}.label', f'{name}.stages.{handle}-0.label', f'{name}.stages.{handle}-1.label'):
        if candidate in by_key and by_key[candidate].english == label:
            yield candidate


STAGE_KEY = re.compile(r'^[^.]+\.stages\.[^.]+\.label$')


def pick_real_items(project, count):
    """Translate the stage label of up to `count` distinct HediffDef/ThoughtDef Defs of a real MOD.

    The stage index the probe reads comes from the entry's previous (index-form) key.
    """
    items, seen = [], set()
    for entry in project.entries:
        if (entry.kind != 'DefInjected' or entry.group not in ('HediffDef', 'ThoughtDef')
                or not STAGE_KEY.match(entry.key) or entry.blocked or entry.excluded or entry.stale
                or not entry.legacy_keys):
            continue
        name = entry.key.split('.')[0]
        if (entry.group, name) in seen:
            continue
        seen.add((entry.group, name))
        stage = int(entry.legacy_keys[0].split('.')[-2])
        text = f'ハンドル検証 {len(items) + 1} {name}'
        project.set_translation(entry.id, text)
        entry.review = False
        items.append({'source_id': f'{name}[{stage}]', 'mod_name': project.name, 'def_name': name,
                      'def_type': entry.group, 'stage': stage, 'key': entry.key, 'english': entry.english,
                      'expected': text, 'translated_under_handle_key': True})
        if len(items) >= count:
            break
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT / 'artifacts/handle-keys-live')
    parser.add_argument('--game', type=Path, default=Path.home() / '.local/share/Steam/steamapps/common/RimWorld')
    parser.add_argument('--compiler-cache', type=Path, default=ROOT / 'artifacts/sol-runtime/compiler')
    parser.add_argument('--timeout', type=float, default=420)
    parser.add_argument('--source', type=Path, help='check a real MOD folder (copied, never changed) instead of the test MOD')
    parser.add_argument('--dependency', action='append', type=Path, default=[], help='MOD folder the source needs (copied)')
    parser.add_argument('--count', type=int, default=6, help='real MOD: how many Defs\' stage labels to translate and read')
    parser.add_argument('--shared', action='store_true',
                        help='test MOD declares 1.4 and 1.6; export the one shared set (index keys of 1.4 + handle keys of 1.6)')
    args = parser.parse_args()
    root, game = args.root.resolve(), args.game.resolve(strict=True)
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f'{root} already holds a run; choose a new --root')
    root.mkdir(parents=True, exist_ok=True)
    version = '.'.join((game / 'Version.txt').read_text(encoding='utf-8').split()[0].split('.')[:2])
    if args.source:
        original = args.source.resolve(strict=True)
        source = root / 'source' / original.name
        shutil.copytree(original, source, symlinks=False)
    else:
        source = root / 'source' / SOURCE_ID
        write_source(source, ('1.4', '1.6') if args.shared else ('1.6',))
    dll = next(game.glob('*_Data/Managed/Assembly-CSharp.dll'))
    with tempfile.TemporaryDirectory(prefix='handle-live-') as cache:
        schema = schema_from_assemblies([dll], Path(cache))
    scanned = scan_mod(source, game_version=version, schema=schema)
    if args.shared and not args.source:
        # 1.4 is scanned with another version's field table, so it keeps index keys (the unverified-version rule);
        # 1.6 has handle keys. The shared set then carries both forms of every item.
        old_schema = copy.copy(schema)
        old_schema.builtin_version = version
        project = Project.create_versions(source, {'1.4': scan_mod(source, game_version='1.4', schema=old_schema),
                                                   version: scanned})
        project.switch_version('1.4')
        index_entries = {e.key: e for e in project.entries if e.kind == 'DefInjected'}
        for _, name, stage, _, text in ITEMS:
            if text is not None:
                entry = index_entries[f'{name}.stages.{stage}.label']
                project.set_translation(entry.id, text)
                entry.review = False
        project.switch_version(version)
    else:
        project = Project.create(source, scanned)
    by_key ={entry.key: entry for entry in project.entries if entry.kind == 'DefInjected'}
    print('scanned keys:', len(by_key))
    expected, used = [], set()
    if args.source:
        expected = pick_real_items(project, args.count)
        if not expected:
            raise SystemExit('The MOD has no handle-keyed HediffDef/ThoughtDef stage label to check')
    for kind, name, stage, label, text in ([] if args.source else ITEMS):
        if text is not None:
            key = next((k for k in handle_key(by_key, name, stage, label) if k not in used), None)
            if key is None:
                raise SystemExit(f'No handle-keyed entry for {name} stage {stage} ({label})')
            used.add(key)
            project.set_translation(by_key[key].id, text)
            by_key[key].review = False
        else:
            key = f'{name}.stages.{stage}.label'
        expected.append({'source_id': f'{name}[{stage}]', 'mod_name': project.name, 'def_name': name, 'def_type': kind,
                         'stage': stage, 'key': key, 'english': label,
                         'expected': text if text is not None else label,
                         'translated_under_handle_key': text is not None})
    project.save(root / 'workspace/project.json')
    generated = root / 'workspace/translation'
    if args.shared and not args.source:
        shared = export_shared(project, generated)
        print('shared export:', shared.exported, 'held:', list(shared.held), 'notices:', len(shared.warnings))
    else:
        export_mod(project, generated)
    exported_keys = sorted(node.tag for path in (generated / 'Languages').rglob('*.xml')
                           for node in ET.parse(path).getroot() if isinstance(node.tag, str))
    control = None if args.source else root / 'control-mod'
    if control:
        write_control(control)

    executable = game / ('RimWorldLinux' if sys.platform != 'win32' else 'RimWorldWin64.exe')
    installation = GameInstallation(game, game / 'Mods', None, (game / 'Version.txt').read_text().split()[0], executable)
    plan = prepare_game_test(installation, generated, root / 'isolated-run', source_mods=[source, *args.dependency],
                             language='Japanese')
    if control:
        shutil.copytree(control, plan.game / 'Mods' / 'control', symlinks=False)
    prefs_path = plan.savedata / 'Config/Prefs.xml'
    prefs = ET.parse(prefs_path).getroot()
    for tag, value in (('screenWidth', '1024'), ('screenHeight', '768'), ('fullscreen', 'False')):
        ET.SubElement(prefs, tag).text = value
    atomic_write(prefs_path, xml_bytes(prefs))
    build_probe(game, plan.game / 'Mods/runtime-proof', args.compiler_cache)
    active = [*plan.active_packages, *([] if args.source else [CONTROL_ID]), runtime.PROBE_ID]
    config_path = plan.savedata / 'Config/ModsConfig.xml'
    config = ET.parse(config_path).getroot()
    node = config.find('activeMods')
    node.clear()
    for package in active:
        ET.SubElement(node, 'li').text = package
    atomic_write(config_path, xml_bytes(config))
    probe_report, screenshot, fixture = plan.root / 'probe-observations.json', plan.root / 'game-translation-proof.png', plan.root / 'proof-fixture.xml'
    fixture_xml = ET.Element('TranslationProof', {'report': str(probe_report), 'screenshot': str(screenshot)})
    for item in expected:
        ET.SubElement(fixture_xml, 'Item', {'sourceId': item['source_id'], 'modName': item['mod_name'],
                                           'defName': item['def_name'], 'defType': item['def_type'],
                                           'stage': str(item['stage'])}).text = item['expected']
    atomic_write(fixture, xml_bytes(fixture_xml))
    setup = {'schema': 1, 'root': str(root), 'isolated_root': str(plan.root), 'game': str(plan.game),
             'executable': str(plan.executable), 'savedata': str(plan.savedata), 'player_log': str(plan.player_log),
             'stdout_log': str(plan.stdout_log), 'argv': [*plan.argv, '-rwt-proof-fixture=' + str(fixture)],
             'active_packages': active, 'expected': expected, 'probe_report': str(probe_report),
             'screenshot': str(screenshot)}
    (root / 'setup.json').write_text(json.dumps(setup, indent=2, ensure_ascii=False), encoding='utf-8')
    report = runtime.run(setup, args.timeout)

    observed = json.loads(probe_report.read_text(encoding='utf-8')).get('observations', []) if probe_report.is_file() else []
    rows = []
    for item, seen in zip(expected, observed + [{}] * (len(expected) - len(observed))):
        actual = seen.get('actual')
        handled = item['translated_under_handle_key']
        rows.append({'item': item['source_id'], 'key': item['key'], 'english': item['english'], 'sent': item['expected'],
                     'actual_in_game': actual, 'found': seen.get('found'),
                     'applied': actual == item['expected'] if handled else None,
                     'control_left_in_english': actual == item['english'] if not handled else None})
    result = {'game_version': (game / 'Version.txt').read_text().strip(), 'exported_keys': exported_keys,
              'rows': rows, 'active_language': report.get('active_language'),
              'process_exit_code': report.get('process_exit_code'),
              'stopped_after_time_limit': report.get('stopped_after_time_limit'),
              'screenshot': report.get('screenshot'), 'diagnostic_lines': report.get('diagnostic_lines'),
              'original_profile_unchanged': report.get('original_profile_unchanged')}
    (root / 'handle-keys-live.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    translated = [r for r in rows if r['applied'] is not None]
    if not observed or not all(r['applied'] for r in translated):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
