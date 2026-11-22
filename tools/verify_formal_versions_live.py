"""Formal multi-version export, end to end: real GUI -> exported MOD -> isolated game.

Three steps, each leaving evidence under --root (default artifacts/formal-live):

  scan    copy one installed source MOD, open it in the real editor window, scan it, then run
          "check and add declared versions". Saves the project and screenshots.
  export  apply translations from a JSON file ({version: {entry id: text}}) through the editor's own
          edit and approve actions, press "export translation MOD", record exported and held versions.
  game    put the exported MOD, the source copy and its dependencies into a disposable game copy with a
          disposable profile, launch it offline with the diagnostic window from tools/runtime_probe, and
          record loaded label values, a framebuffer screenshot and the translation lines of the log.

Run each step through the isolating runner on a real display, for example
    python tools/run_tests.py --script tools/verify_formal_versions_live.py scan --source <mod folder>
The original MOD, the installed game, saves and personal projects are only read. MOD DLLs are read as
metadata by the editor; inside the disposable game the game itself loads its mods as it always does.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def open_window(root: Path, size=(1366, 768)):
    from PySide6.QtWidgets import QApplication
    from rimworld_translator.gui import Window
    app = QApplication.instance() or QApplication([])
    window = Window(settings_path=root / 'settings.json')
    window.resize(*size)
    window.show()
    return app, window


def wait_idle(app, window, timeout=1800):
    started = time.monotonic()
    app.processEvents()
    while window.busy:
        app.processEvents()
        time.sleep(0.02)
        if time.monotonic() - started > timeout:
            raise TimeoutError('The editor stayed busy')
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)


def shot(app, window, root: Path, name: str, widget=None) -> str:
    for _ in range(10):
        app.processEvents()
        time.sleep(0.03)
    path = root / 'screenshots' / (name + '.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    (widget or window).grab().save(str(path))
    return str(path)


def step_scan(args):
    from PySide6.QtWidgets import QMessageBox
    root = args.root.resolve()
    original = args.source.resolve(strict=True)
    if (root / 'scan.json').exists():
        raise SystemExit(f'{root} already holds a run; choose a new --root')
    before = tree_hash(original)
    source = root / 'source' / original.name
    shutil.copytree(original, source, symlinks=False)
    app, window = open_window(root)
    errors = []
    window.error = lambda text: errors.append(str(text))
    started = time.monotonic()
    window.start_scan(source, new_path=root / 'workspace/project.json')
    wait_idle(app, window)
    first_seconds = round(time.monotonic() - started, 1)
    shots = [shot(app, window, root, '01-first-scan')]
    first = {'version': window.project.game_version, 'entries': len(window.project.entries),
             'game_context': None}
    # The two confirmations of "check and add declared versions", answered as a user would.
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    window.choose_declared_versions = lambda result, available: list(available)
    started = time.monotonic()
    window.scan_declared_versions_dialog()
    wait_idle(app, window)
    declared_seconds = round(time.monotonic() - started, 1)
    shots.append(shot(app, window, root, '02-declared-versions-added'))
    project = window.project
    profiles = {}
    for version in project.versions:
        profile = project.version_profiles.get(version, {})
        entries = profile.get('entries', [])
        context = (profile.get('stats') or {}).get('game_context')
        kinds = {}
        for entry in entries:
            kind = entry['kind'] if isinstance(entry, dict) else entry.kind
            kinds[kind] = kinds.get(kind, 0) + 1
        profiles[version] = {'extracted': bool(profile.get('coverage', {}).get('extracted')),
                             'entries': len(entries), 'kinds': kinds, 'game_context': context}
    report = {'original': str(original), 'source_copy': str(source), 'original_tree_sha256_before': before,
              'original_unchanged': tree_hash(original) == before, 'declared_versions': list(project.versions),
              'first_scan': first, 'first_scan_seconds': first_seconds, 'declared_scan_seconds': declared_seconds,
              'profiles': profiles, 'errors': errors, 'screenshots': shots,
              'qt_platform': app.platformName(), 'project': str(root / 'workspace/project.json')}
    write_json(root / 'scan.json', report)
    window.dirty = False
    window.close()
    print(json.dumps(report, indent=2, ensure_ascii=False))


def step_export(args):
    from PySide6.QtWidgets import QPlainTextEdit
    root = args.root.resolve()
    scan = json.loads((root / 'scan.json').read_text(encoding='utf-8'))
    translations = json.loads(args.translations.read_text(encoding='utf-8'))
    app, window = open_window(root)
    errors = []
    window.error = lambda text: errors.append(str(text))
    window.load_project(Path(scan['project']))
    wait_idle(app, window)
    applied = {}
    for version, items in translations.items():
        index = window.version_selector.findText(version)
        if index < 0:
            raise SystemExit(f'Version {version} is not selectable in the editor')
        window.version_selector.setCurrentIndex(index)
        wait_idle(app, window)
        done = 0
        for entry_id, text in items.items():
            row = window.model.row_for_id.get(entry_id)
            if row is None:
                errors.append(f'{version}: no such entry {entry_id}')
                continue
            window.table.setCurrentIndex(window.proxy.mapFromSource(window.model.index(row, 0)))
            app.processEvents()
            window.japanese.setPlainText(text)     # the editor pane, as when typing
            app.processEvents()
            window.mark_reviewed(approved=True)    # the "confirmed" action
            done += 1
        applied[version] = done
        shot(app, window, root, f'03-edited-{version}')
    exported_ok = window.generate()                # the "export translation MOD" button's action
    wait_idle(app, window)
    output = Path(scan['project']).parent / 'mod'
    report_text = ''
    if window.trial_output_report is not None:
        notices = window.trial_output_report.findChild(QPlainTextEdit, 'trialOutputNotices')
        report_text = notices.toPlainText() if notices else ''
        shot(app, window, root, '04-export-result-dialog', window.trial_output_report)
    shot(app, window, root, '04-after-export')
    marker = output / '.rimworld-translator.json'
    files = sorted(str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()) if output.is_dir() else []
    result = {'export_returned': bool(exported_ok), 'applied': applied, 'errors': errors, 'output': str(output),
              'guidance': window.guidance.text(), 'result_dialog': report_text,
              'marker': json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else None,
              'about': (output / 'About/About.xml').read_text(encoding='utf-8') if (output / 'About/About.xml').is_file() else None,
              'load_folders': (output / 'LoadFolders.xml').read_text(encoding='utf-8') if (output / 'LoadFolders.xml').is_file() else None,
              'files': files,
              'original_unchanged': tree_hash(Path(scan['original'])) == scan['original_tree_sha256_before']}
    write_json(root / 'export.json', result)
    window.close_trial_output_report()
    window.dirty = False
    window.close()
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2, ensure_ascii=False))
    print(f"{len(files)} files written")


def step_game(args):
    from rimworld_translator.core import Project, atomic_write, xml_bytes
    from rimworld_translator.game_testing import prepare_game_test
    from rimworld_translator.platforms import GameInstallation
    from tools.build_runtime_probe import build_probe
    from tools import verify_runtime_ui as runtime
    root = args.root.resolve()
    scan = json.loads((root / 'scan.json').read_text(encoding='utf-8'))
    export = json.loads((root / 'export.json').read_text(encoding='utf-8'))
    game = args.game.resolve(strict=True)
    version = '.'.join((game / 'Version.txt').read_text(encoding='utf-8').split()[0].split('.')[:2])
    project = Project.load(Path(scan['project']))
    project.switch_version(version)
    translated = project.translations.get('Japanese', {})
    labels = [e for e in project.entries if e.kind == 'DefInjected' and e.group == 'ThingDef'
              and e.key.endswith('.label') and e.key.count('.') == 1 and not (e.blocked or e.stale or e.excluded)]
    if args.defs:
        # Named Defs, in the order given: for a window that shows translated and untranslated labels together.
        by_name = {e.key[:-len('.label')]: e for e in labels}
        missing = [name for name in args.defs if name not in by_name]
        if missing:
            raise SystemExit('No top-level ThingDef label in the project for: ' + ', '.join(missing))
        labels = [by_name[name] for name in args.defs]
        args.translated = args.untranslated = len(labels)
    shown = [e for e in labels if translated.get(e.id, '').strip()][:args.translated]
    plain = [e for e in labels if not translated.get(e.id, '').strip()][:args.untranslated]
    expected = [{'source_id': 'translated' if e in shown else 'untranslated', 'mod_name': project.name,
                 'def_name': e.key[:-len('.label')], 'key': e.key, 'english': e.english,
                 'expected': translated.get(e.id, '').strip() or e.english} for e in [*shown, *plain]]
    live = root / 'game'
    executable = game / ('RimWorldLinux' if sys.platform != 'win32' else 'RimWorldWin64.exe')
    installation = GameInstallation(game, game / 'Mods', None, (game / 'Version.txt').read_text().split()[0], executable)
    plan = prepare_game_test(installation, Path(export['output']), live / 'isolated-run',
                             source_mods=[Path(scan['source_copy']), *args.dependency], language='Japanese')
    prefs_path = plan.savedata / 'Config/Prefs.xml'
    prefs = ET.parse(prefs_path).getroot()
    for tag, value in (('screenWidth', '1024'), ('screenHeight', '768'), ('fullscreen', 'False')):
        ET.SubElement(prefs, tag).text = value
    atomic_write(prefs_path, xml_bytes(prefs))
    active = list(plan.active_packages)
    if not args.log_only:
        # Compiling the diagnostic window needs the Roslyn compiler, downloaded once into the compiler cache.
        build_probe(game, plan.game / 'Mods/runtime-proof', args.compiler_cache)
        active.append(runtime.PROBE_ID)
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
                                           'defName': item['def_name']}).text = item['expected']
    atomic_write(fixture, xml_bytes(fixture_xml))
    setup = {'schema': 1, 'root': str(live), 'isolated_root': str(plan.root), 'game': str(plan.game),
             'executable': str(plan.executable), 'savedata': str(plan.savedata), 'player_log': str(plan.player_log),
             'stdout_log': str(plan.stdout_log), 'argv': [*plan.argv, '-rwt-proof-fixture=' + str(fixture)],
             'active_packages': active, 'expected': expected, 'probe_report': str(probe_report),
             'screenshot': str(screenshot)}
    write_json(live / 'setup.json', setup)
    report = runtime.run(setup, args.timeout)
    log = Path(setup['player_log']).read_text(encoding='utf-8', errors='replace') if Path(setup['player_log']).is_file() else ''
    report['translation_log_lines'] = [line.strip()[:300] for line in log.splitlines()
                                       if any(term in line.lower() for term in ('translat', 'definjected', 'keyed', 'language'))][:80]
    report['untranslated_shown_in_english'] = all(
        s['actual'] == s['english'] for s in report['samples'] if s['source_id'] == 'untranslated')
    report['translated_loaded_in_japanese'] = all(
        s['injection_match'] for s in report['samples'] if s['source_id'] == 'translated')
    report['log_only'] = args.log_only
    report['mods_loaded_line'] = next((line.strip()[:400] for line in log.splitlines() if 'Loaded mods' in line or 'Mod load order' in line), '')
    write_json(root / 'game.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('ocr_text', 'original_profile_before_sha256',
                                                                   'original_profile_after_sha256')},
                     indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=('scan', 'export', 'game'))
    parser.add_argument('--root', type=Path, default=ROOT / 'artifacts/formal-live')
    parser.add_argument('--source', type=Path, help='scan: installed source MOD folder (copied, never changed)')
    parser.add_argument('--translations', type=Path, help='export: JSON {version: {entry id: translation}}')
    parser.add_argument('--game', type=Path, default=Path.home() / '.local/share/Steam/steamapps/common/RimWorld')
    parser.add_argument('--dependency', action='append', type=Path, default=[], help='game: required MOD folder')
    parser.add_argument('--compiler-cache', type=Path, default=ROOT / 'artifacts/sol-runtime/compiler')
    parser.add_argument('--timeout', type=float, default=420)
    parser.add_argument('--log-only', action='store_true',
                        help='game: skip the diagnostic window; run until --timeout and read only the log')
    parser.add_argument('--translated', type=int, default=4)
    parser.add_argument('--untranslated', type=int, default=2)
    parser.add_argument('--def', dest='defs', action='append', default=[],
                        help='game: check exactly these ThingDefs instead of the first --translated/--untranslated')
    args = parser.parse_args()
    if args.step == 'scan' and not args.source:
        parser.error('scan needs --source')
    if args.step == 'export' and not args.translations:
        parser.error('export needs --translations')
    {'scan': step_scan, 'export': step_export, 'game': step_game}[args.step](args)


if __name__ == '__main__':
    main()
