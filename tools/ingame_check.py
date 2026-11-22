"""Check exported translations inside the isolated RimBridgeServer + GABS test game.

Each extracted row gets a numbered marker translation (訳00001, ...) followed by the
source's placeholders, grammar tokens and rich-text tags, so formal QA passes without
hand translation. The translation MODs are installed into the bridge's own game copy,
the game runs in Japanese through GABS, and three independent views are collected:

- the game's own Translation Report (injection errors, missing fields, NoTranslate
  fields, argument mismatches), minus the vanilla baseline;
- warnings and errors from the game log;
- marker text read back from spawned items through the bridge (what a player sees).

Nothing outside the bridge folder and --out is written. MOD DLLs are not loaded unless
--allow-dlls is given; downloaded MODs are untrusted code.

Usage: python tools/ingame_check.py MOD_FOLDER [...] --out DIR [--version 1.6]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rimworld_translator.core import TOKENS, Entry  # noqa: E402
from rimworld_translator.qa import _GRAMMAR_TOKENS, _PAIRED_TAGS, _SINGLE_TAGS, _TAG, grammar_rule_prefix  # noqa: E402


# ---------------------------------------------------------------- numbered fill

def numbered_translation(entry: Entry, number: int) -> str:
    """The marker plus everything formal QA requires the translation to keep, in source order per kind."""
    prefix = grammar_rule_prefix(entry)
    body = entry.english[len(prefix):]
    stripped = body.strip()
    keep = TOKENS.findall(stripped)
    if prefix:
        keep += _GRAMMAR_TOKENS.findall(stripped)
    keep += [m.group(0) for m in _TAG.finditer(stripped) if m.group(2).casefold() in _PAIRED_TAGS | _SINGLE_TAGS]
    lead = body[:len(body) - len(body.lstrip())]
    trail = body[len(body.rstrip()):]
    inner_breaks = '\n' * stripped.replace('\r\n', '\n').count('\n')
    return prefix + lead + ' '.join([f'訳{number:05d}', *keep]) + inner_breaks + trail


def fill_numbered(entries, start: int = 1) -> dict[str, str]:
    """Give every exportable row a marker; returns marker -> entry id."""
    markers, number = {}, start
    for entry in entries:
        if entry.blocked or entry.excluded or entry.stale:
            continue
        entry.japanese = numbered_translation(entry, number)
        entry.review = False
        markers[f'訳{number:05d}'] = entry.id
        number += 1
    return markers


# ---------------------------------------------------------------- game report

_SECTION = re.compile(r'^=+ (.+?) \((\d+)\) =+$')


def parse_translation_report(text: str) -> dict[str, list[str]]:
    """Section title -> items; indented continuation lines stay with their item."""
    sections, current = {}, None
    for line in text.splitlines():
        match = _SECTION.match(line.strip())
        if match:
            current = sections.setdefault(match.group(1), [])
            continue
        if current is None or not line.strip():
            continue
        if line.startswith((' ', '\t')) and current:
            current[-1] += '\n' + line
        else:
            current.append(line)
    return sections


def new_report_items(sections: dict[str, list[str]], baseline: dict[str, list[str]]) -> dict[str, list[str]]:
    """Items not present in the vanilla report; empty sections are dropped."""
    result = {}
    for title, items in sections.items():
        known = set(baseline.get(title, ()))
        fresh = [item for item in items if item not in known]
        if fresh:
            result[title] = fresh
    return result


# ---------------------------------------------------------------- pipeline

BRIDGE = Path.home() / '.local/share/rimworld-translator/bridge'
LIBRARY = Path.home() / '.local/share/rimworld-translator/games'
WORKSHOP = Path.home() / '.local/share/Steam/steamapps/workshop/content/294100'
# RimWorld 1.6 writes the report into the home folder, not into -savedatafolder.
REPORT_FILE = Path.home() / 'TranslationReport.txt'
GAME_ID = 'rimworld16'
PREFIX = 'zzcheck-'
BASE_MODS = ['brrainz.harmony', 'ludeon.rimworld', 'ludeon.rimworld.royalty', 'ludeon.rimworld.biotech']
BRIDGE_MOD = 'brrainz.rimbridgeserver'


def _dlls(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.suffix.casefold() == '.dll' and p.is_file())


def unapproved_dlls(source: Path, prerequisites) -> dict[str, list[str]]:
    """DLLs that need --allow-dlls, by folder.

    Only a prerequisite whose packageId is Harmony is approved: install() never copies a prerequisite whose
    packageId the bridge game already has, so the bridge's own Harmony is what loads. The source is always copied.
    """
    from rimworld_translator.installation import read_mod_metadata
    found = {}
    for folder in [Path(source), *map(Path, prerequisites)]:
        if folder != Path(source) and read_mod_metadata(folder).package_id.casefold() == 'brrainz.harmony':
            continue
        if dlls := _dlls(folder):
            found[str(folder)] = dlls
    return found


def prepare_mod(root: Path, version: str, number: int, out: Path, extra_paths) -> dict:
    """Scan with the product's own context, fill markers, export. Returns a description of the result."""
    from rimworld_translator.core import Project, export_mod
    from rimworld_translator.extraction import content_files, resolve_load_folders, scan
    from rimworld_translator.game_library import game_dll
    from rimworld_translator.installation import read_mod_metadata
    from rimworld_translator.scan_context import dependency_context
    from rimworld_translator.schema import schema_from_assemblies
    from tools.dependency_bench import library_games

    game = library_games(LIBRARY)[version]
    context = dependency_context(game, (), root, version, None, extra_mod_paths=extra_paths)
    assemblies = [game_dll(game.root)]
    for folder in (root, *context.sources):
        assemblies += content_files(resolve_load_folders(folder, version, None), 'Assemblies', '.dll')
    schema = schema_from_assemblies(assemblies, out / 'schema-cache')
    result = scan(root, version, None, None, None, None, schema, context.sources, 100000)
    project = Project.create(root, result, ['Japanese'])
    markers = fill_numbered(project.entries, number)
    work = out / 'projects' / f'{len(list((out / "projects").glob("*"))) if (out / "projects").is_dir() else 0:02d}-{root.name}'
    project.save(work / 'project.json')
    warnings = export_mod(project, work / 'mod')
    return {'root': str(root), 'package_id': read_mod_metadata(root).package_id, 'project': str(work / 'project.json'),
            'export': str(work / 'mod'), 'translation_id': project.package_id, 'markers': markers,
            'entries': {e.id: {'key': e.key, 'kind': e.kind, 'group': e.group, 'english': e.english[:200],
                               'japanese': e.japanese[:200]} for e in project.entries if e.id in markers.values()},
            'rows': len(project.entries), 'filled': len(markers), 'export_warnings': warnings,
            'prerequisites': [str(p) for p in context.sources if not str(p).startswith(str(game.root))],
            'missing_prerequisites': [d.package_id for d in context.missing]}


def install(mods: list[dict], game: Path, savedata: Path) -> list[str]:
    """Replace this tool's earlier copies in the bridge game and activate sources, prerequisites and translations."""
    from rimworld_translator.installation import read_mod_metadata
    target = game / 'Mods'
    for old in target.glob(PREFIX + '*'):
        shutil.rmtree(old)
    present = {read_mod_metadata(p).package_id for p in target.iterdir() if (p / 'About/About.xml').is_file()}
    order = list(BASE_MODS)
    for mod in mods:
        for dep in mod['prerequisites']:
            package = read_mod_metadata(Path(dep)).package_id
            if package not in present and package not in order:
                shutil.copytree(dep, target / f'{PREFIX}dep-{package}', symlinks=False)
                present.add(package)
            if package not in order:
                order.append(package)
    for index, mod in enumerate(mods):
        shutil.copytree(mod['root'], target / f'{PREFIX}src-{index:02d}', symlinks=False)
        shutil.copytree(mod['export'], target / f'{PREFIX}tr-{index:02d}', symlinks=False)
        order += [mod['package_id'], mod['translation_id']]
    order.append(BRIDGE_MOD)
    config = ET.Element('ModsConfigData')
    ET.SubElement(config, 'version').text = (game / 'Version.txt').read_text(encoding='utf-8').strip()
    active = ET.SubElement(config, 'activeMods')
    for package in dict.fromkeys(order):
        ET.SubElement(active, 'li').text = package
    known = ET.SubElement(config, 'knownExpansions')
    for package in BASE_MODS[2:]:
        ET.SubElement(known, 'li').text = package
    ET.ElementTree(config).write(savedata / 'Config/ModsConfig.xml', encoding='utf-8', xml_declaration=True)
    return list(dict.fromkeys(order))


def set_language(prefs: Path, folder_name: str) -> None:
    tree = ET.parse(prefs)
    for tag, value in (('langFolderName', folder_name), ('devMode', 'True'), ('runInBackground', 'True')):
        node = tree.getroot().find(tag)
        if node is None:
            node = ET.SubElement(tree.getroot(), tag)
        node.text = value
    tree.write(prefs, encoding='utf-8', xml_declaration=True)


class Gabs:
    """GABS MCP over loopback HTTP; the server process lives only as long as this object."""

    def __init__(self, port: int, log: Path):
        binary = next((BRIDGE / 'gabs').glob('gabs-*/gabs'))
        self.url = f'http://127.0.0.1:{port}/mcp'
        self.process = subprocess.Popen([str(binary), 'server', 'http', '--addr', f'127.0.0.1:{port}',
                                         '--configDir', str(BRIDGE / 'gabs-config'), '--log-level', 'warn'],
                                        stdout=log.open('wb'), stderr=subprocess.STDOUT)
        self.session, self.counter = None, 0
        # Game errors that RimBridge raised while this run was calling it; each is acknowledged so the run continues.
        self.attentions = []
        for _ in range(100):
            try:
                self._rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                         'clientInfo': {'name': 'ingame_check', 'version': '1'}})
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError('GABS server did not start')

    def _rpc(self, method, params):
        self.counter += 1
        body = json.dumps({'jsonrpc': '2.0', 'id': self.counter, 'method': method, 'params': params}).encode()
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        with urllib.request.urlopen(urllib.request.Request(self.url, body, headers), timeout=900) as response:
            self.session = response.headers.get('Mcp-Session-Id') or self.session
            raw = response.read().decode()
        if 'data:' in raw[:20] or raw.lstrip().startswith('event:'):
            raw = '\n'.join(line[5:].strip() for line in raw.splitlines() if line.startswith('data:'))
        reply = json.loads(raw)
        if 'error' in reply:
            raise RuntimeError(f'{method}: {reply["error"]}')
        return reply['result']

    def gabs(self, name, **arguments):
        result = self._rpc('tools/call', {'name': name, 'arguments': arguments})
        return result.get('structuredContent') or result

    def game(self, tool, **arguments):
        for _ in range(5):
            result = self.gabs('games_call_tool', gameId=GAME_ID, tool=f'{GAME_ID}_{tool}', arguments=arguments)
            attention = result.get('attention') if result.get('status') == 'blocked_by_attention' else None
            if not attention:
                return result
            self.attentions.append({'during': tool, 'summary': attention.get('summary'), 'sample': attention.get('sample')})
            self.gabs('games_ack_attention', gameId=GAME_ID, attentionId=attention['attentionId'])
        raise RuntimeError(f'{tool} stayed blocked by game errors')

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _wait(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise TimeoutError(message)


def run_game(mods: list[dict], out: Path, sample: int) -> dict:
    """Start the game through GABS, collect the report, logs and on-screen labels, and always stop it."""
    player_log = BRIDGE / 'logs/Player.log'
    if player_log.exists():
        player_log.unlink()
    gabs = Gabs(_free_port(), out / 'gabs-server.log')
    findings = {}
    try:
        gabs.gabs('games_start', gameId=GAME_ID)
        _wait(lambda: player_log.exists() and 'GABP server connected' in player_log.read_text(errors='replace'),
              900, 'the bridge did not connect; see Player.log')
        gabs.gabs('games_connect', gameId=GAME_ID)
        gabs.game('rimbridge_wait_for_long_event_idle', timeoutMs=600000)
        languages = gabs.game('rimworld_list_languages')
        findings['language'] = languages.get('activeLanguage')
        gabs.game('rimworld_execute_debug_action', path='Actions\\Save Translation Report')
        _wait(REPORT_FILE.exists, 300, 'the game did not write TranslationReport.txt')
        time.sleep(2)
        shutil.move(str(REPORT_FILE), out / 'TranslationReport.txt')
        try:
            findings['display'] = check_display(gabs, mods, sample)
        except Exception as exc:  # a broken colony start must not lose the report already collected
            findings['display_error'] = repr(exc)[:500]
        logs = gabs.game('rimbridge_list_logs', limit=500, minimumLevel='warning')
        findings['bridge_logs'] = logs.get('entries') or logs.get('logs') or logs
    finally:
        findings['game_errors_during_calls'] = gabs.attentions
        try:
            gabs.gabs('games_stop', gameId=GAME_ID)
        except Exception as exc:  # the report must still be written
            findings['stop_error'] = repr(exc)
        gabs.close()
        if REPORT_FILE.exists():
            shutil.move(str(REPORT_FILE), out / 'TranslationReport.late.txt')
    if player_log.exists():
        shutil.copy2(player_log, out / 'Player.log')
    return findings


def check_display(gabs: Gabs, mods: list[dict], sample: int) -> list[dict]:
    """Spawn marked ThingDefs next to a colonist and read back what the game shows for them."""
    gabs.game('rimworld_start_debug_game_ready', readiness='playable', timeoutMs=600000, pauseIfNeeded=True)
    colonists = gabs.game('rimworld_list_colonists').get('colonists') or []
    origin = colonists[0]['position'] if colonists else {'x': 100, 'z': 100}
    results, offset = [], 2
    for mod in mods:
        labels = [(e['key'].split('.')[0], e['japanese']) for e in mod['entries'].values()
                  if e['kind'] == 'DefInjected' and e['group'] == 'ThingDef' and e['key'].count('.') == 1
                  and e['key'].endswith('.label')]
        for def_name, expected in labels[:sample]:
            cell = {'x': origin['x'] + offset % 12, 'z': origin['z'] + 2 + offset // 12}
            offset += 1
            row = {'mod': mod['root'], 'defName': def_name, 'expected': expected}
            try:
                spawned = gabs.game('rimworld_spawn_thing', defName=def_name, **cell)
                row['spawn_label'] = spawned.get('label')
                gabs.game('rimworld_clear_selection')
                gabs.game('rimworld_click_cell', **cell)
                selected = gabs.game('rimworld_get_selection_semantics').get('selectedObjects') or []
                row['inspect_label'] = selected[0].get('inspectLabel') if selected else None
            except Exception as exc:
                row['error'] = repr(exc)[:300]
            marker = expected.split()[0] if expected else ''
            row['shown'] = bool(marker) and marker in f"{row.get('spawn_label')}{row.get('inspect_label')}"
            results.append(row)
    return results


def summarize(mods: list[dict], findings: dict, out: Path, baseline_file: Path) -> dict:
    report = parse_translation_report((out / 'TranslationReport.txt').read_text(encoding='utf-8'))
    baseline = parse_translation_report(baseline_file.read_text(encoding='utf-8')) if baseline_file.is_file() else {}
    fresh = new_report_items(report, baseline)
    log_text = (out / 'Player.log').read_text(errors='replace') if (out / 'Player.log').exists() else ''
    error_lines = [line for line in log_text.splitlines()
                   if re.search(r'\b(error|exception|could not|couldn\'t|failed)\b', line, re.I)
                   and 'Fallback handler could not load library' not in line]
    display = findings.get('display', [])
    summary = {'mods': [{k: m[k] for k in ('root', 'package_id', 'rows', 'filled', 'export_warnings',
                                            'missing_prerequisites', 'export')} for m in mods],
               'language': findings.get('language'),
               'report_new_items': {title: len(items) for title, items in fresh.items()},
               'report_new': fresh,
               'player_log_errors': error_lines[:300],
               'display_checked': len(display), 'display_shown': sum(1 for d in display if d['shown']),
               'display': display}
    for key in ('stop_error', 'display_error', 'game_errors_during_calls'):
        if key in findings:
            summary[key] = findings[key]
    (out / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('mods', nargs='+', type=Path, help='MOD folders that contain About/About.xml')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--version', default='1.6', help='game version to scan and run (the bridge copy is 1.6)')
    parser.add_argument('--allow-dlls', action='store_true', help='load MODs that ship DLLs (untrusted code)')
    parser.add_argument('--sample', type=int, default=15, help='ThingDefs per MOD to spawn and read back')
    parser.add_argument('--extra', type=Path, action='append', default=[], help='more read-only MOD folders for prerequisites')
    parser.add_argument('--baseline', type=Path, default=BRIDGE / 'logs/TranslationReport-vanilla-ja.txt')
    args = parser.parse_args(argv)

    from rimworld_translator.game_testing import resolve_game_language
    from rimworld_translator.installation import read_mod_metadata
    game, savedata = BRIDGE / 'game-1.6/RimWorld', BRIDGE / 'savedata'
    if REPORT_FILE.exists():
        raise SystemExit(f'{REPORT_FILE} already exists; move it away first (it is not this tool\'s file).')
    if subprocess.run(['pidof', 'RimWorldLinux'], capture_output=True).returncode == 0:
        raise SystemExit('RimWorldLinux is already running; stop it first.')
    args.out.mkdir(parents=True, exist_ok=True)
    extra = [p for p in sorted(WORKSHOP.iterdir()) if (p / 'About/About.xml').is_file()] if WORKSHOP.is_dir() else []
    extra += [p.resolve() for p in args.extra]

    mods, skipped, number = [], [], 1
    for root in (p.resolve() for p in args.mods):
        meta = read_mod_metadata(root)
        if meta.supported_versions and args.version not in meta.supported_versions:
            # An old MOD fails to load its own Defs on this game; its errors would bury the translation's.
            skipped.append({'root': str(root), 'reason': f'does not declare {args.version}',
                            'supported': list(meta.supported_versions)})
            continue
        prepared = prepare_mod(root, args.version, number, args.out, extra)
        if prepared['missing_prerequisites']:
            skipped.append({'root': str(root), 'reason': 'prerequisites not installed',
                            'missing': prepared['missing_prerequisites']})
            continue
        dlls = unapproved_dlls(Path(prepared['root']), prepared['prerequisites'])
        if dlls and not args.allow_dlls:
            skipped.append({'root': str(root), 'reason': 'ships DLLs', 'dlls': dlls})
            continue
        number += len(prepared['markers'])
        mods.append(prepared)
        print(f'prepared {root.name}: {prepared["filled"]}/{prepared["rows"]} rows', flush=True)
    (args.out / 'prepared.json').write_text(json.dumps({'mods': mods, 'skipped': skipped}, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
    if not mods:
        print(json.dumps({'skipped': skipped}, ensure_ascii=False, indent=2))
        return 1
    active = install(mods, game, savedata)
    set_language(savedata / 'Config/Prefs.xml', resolve_game_language(game, 'Japanese'))
    print('active:', ', '.join(active), flush=True)
    findings = run_game(mods, args.out, args.sample)
    summary = summarize(mods, findings, args.out, args.baseline)
    summary['skipped'] = skipped
    (args.out / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('report_new_items', 'display_checked', 'display_shown')}, ensure_ascii=False))
    print('player log error lines:', len(summary['player_log_errors']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
