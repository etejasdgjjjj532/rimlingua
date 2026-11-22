"""Measure over-extraction and recall guards on the pinned mod corpus (tools/corpus/manifest.json).

Evidence used here is independent of the extraction rules under test:
  proven_reference  the extracted value is another Def's defName, a Keyed key, or an existing texture path
  translated        the community translations shipped inside the mod contain this field (recall guard)
Run tools/fetch_corpus.py first. No mod code is executed; DLLs are read as metadata only.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lxml import etree  # noqa: E402
from rimworld_translator.extraction import content_files, resolve_load_folders, scan  # noqa: E402
from rimworld_translator.schema import game_table_schema, schema_from_assemblies  # noqa: E402

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
IMAGE = {'.png', '.jpg', '.jpeg', '.psd', '.tga', '.dds'}


def game_root(explicit: Path | None) -> Path:
    for candidate in ([explicit] if explicit else []) + [Path.home() / '.local/share/Steam/steamapps/common/RimWorld']:
        if candidate and candidate.is_dir():
            return candidate
    raise SystemExit('RimWorld installation not found; pass --game')


def norm(group: str, key: str):
    # The folder a translator used for a file is not always the Def type, so the group is not compared.
    parts = key.split('.')
    rest = parts[1:]
    leaf = rest[-2] if len(rest) > 1 and rest[-1].isdigit() else (rest[-1] if rest else '')
    # Translators sometimes change the case of a field name; compare case-insensitively.
    return ('', parts[0], (rest[0] if rest else '').casefold(), leaf.casefold())


def mod_root(base: Path):
    hits = sorted((h for h in base.rglob('About.xml') if h.parent.name.lower() == 'about'),
                  key=lambda p: len(p.parts))
    return hits[0].parent.parent if hits else None


def mod_version(root: Path, default: str = '1.6') -> str:
    """Newest game version the mod declares (About supportedVersions or versioned folders)."""
    found = set()
    try:
        for li in etree.parse(str(root / 'About/About.xml'), PARSER).getroot().iter('li'):
            if li.text and re.fullmatch(r'\d+\.\d+', li.text.strip().split(' ')[0].lstrip('v')):
                found.add(li.text.strip().split(' ')[0].lstrip('v'))
    except (OSError, etree.XMLSyntaxError):
        pass
    found.update(d.name.lstrip('v') for d in root.iterdir() if d.is_dir() and re.fullmatch(r'v?\d+\.\d+', d.name))
    key = lambda v: tuple(int(x) for x in v.split('.'))
    return max(found, key=key) if found else default


def xml_names(files, tag):
    names = set()
    for file in files:
        try:
            names.update(n.text.strip() for n in etree.parse(str(file), PARSER).getroot().iter(tag) if n.text)
        except (OSError, etree.XMLSyntaxError):
            pass
    return names


def keyed_keys(root: Path):
    keys = set()
    for folder in root.rglob('Keyed'):
        if folder.parent.name == 'English':
            for file in folder.rglob('*.xml'):
                try:
                    keys.update(c.tag for c in etree.parse(str(file), PARSER).getroot() if isinstance(c.tag, str))
                except (OSError, etree.XMLSyntaxError):
                    pass
    return keys


def texture_paths(root: Path):
    found = set()
    for folder in root.rglob('Textures'):
        for file in folder.rglob('*'):
            if file.suffix.lower() in IMAGE:
                found.add(file.relative_to(folder).with_suffix('').as_posix().casefold())
    return found


def community_truth(root: Path):
    truth = Counter()
    languages = set()
    for languages_dir in root.rglob('Languages'):
        for lang in languages_dir.iterdir():
            if not lang.is_dir() or lang.name.startswith('English') or not (lang / 'DefInjected').is_dir():
                continue
            languages.add(lang.name)
            per = Counter()
            seen_tags = set()
            for file in (lang / 'DefInjected').rglob('*.xml'):
                group = file.relative_to(lang / 'DefInjected').parts[0]
                try:
                    tags = [e.tag for e in etree.parse(str(file), PARSER).getroot() if isinstance(e.tag, str)]
                except (OSError, etree.XMLSyntaxError):
                    continue
                seen_tags.update((tag, norm(group, tag)) for tag in tags)
            # The same key written under two folders (ThingDef and ThingDefs) is one translation, not two.
            per.update(key for _tag, key in seen_tags)
            for key, count in per.items():
                truth[key] = max(truth[key], count)
    return truth, languages


def attribute_class(entry) -> str:
    if entry.confidence == 'catalog':
        return 'catalog'
    if entry.confidence == 'heuristic':
        return 'heuristic'
    attrs = next((ev.split(': ', 1)[1] for ev in entry.evidence if ev.startswith('CLR ') and ': ' in ev), '')
    return 'attributed' if ('MustTranslateAttribute' in attrs or 'MayTranslateAttribute' in attrs) else 'unattributed'


def core_context(game: Path, cache: Path):
    file = cache / 'core-context.json'
    if file.exists():
        data = json.loads(file.read_text())
        return set(data['defs']), set(data['keyed'])
    core = game / 'Data/Core'
    defs = xml_names(content_files([core], 'Defs'), 'defName')
    keyed = keyed_keys(core)
    cache.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({'defs': sorted(defs), 'keyed': sorted(keyed)}))
    return defs, keyed


def measure(base: Path, game: Path, core_defs, core_keyed, schema_cache: Path, mode: str = 'game'):
    root = mod_root(base)
    if root is None:
        return None
    dll = next(game.glob('*_Data/Managed/Assembly-CSharp.dll'))
    version = mod_version(root)
    mod_dlls = content_files(resolve_load_folders(root, version, None), 'Assemblies', '.dll')
    # game: the normal route. mod: no installation, only the mod's own DLLs. none: no CLR metadata at all.
    # The scoring context (core_defs, core_keyed) stays the same so the three conditions are comparable.
    # builtin: what the editor now does without an installation (the field table read from the installed game + mod DLLs).
    schema = None if mode == 'none' else schema_from_assemblies(
        ([dll] if mode == 'game' else []) + mod_dlls, schema_cache, base=game_table_schema(schema_cache / 'game-table', [game]) if mode == 'builtin' else None)
    started = time.perf_counter()
    result = scan(root, version, None, None, None, None, schema, (game / 'Data/Core',) if mode == 'game' else (), None)
    seconds = time.perf_counter() - started
    defs = xml_names(content_files(resolve_load_folders(root, version, None), 'Defs'), 'defName') | core_defs
    keys = keyed_keys(root) | core_keyed
    textures = texture_paths(root)
    truth, languages = community_truth(root)
    entries = [e for e in result.entries if e.kind == 'DefInjected']
    tool = Counter(norm(e.group, e.key) for e in entries)
    classes = Counter(attribute_class(e) for e in entries)
    proven, flagged = Counter(), []
    for entry in entries:
        value = entry.english.strip()
        reason = ('def-name' if value in defs else 'keyed-key' if value in keys
                  else 'texture-path' if value.casefold() in textures else '')
        if reason:
            proven[attribute_class(entry)] += 1
            flagged.append([entry.id, value[:80], attribute_class(entry), reason])
    return {
        'mod': base.name, 'version': version,
        # A repository holding only translations has no Defs to extract from; summaries keep it apart.
        'def_files': len(content_files(resolve_load_folders(root, version, None), 'Defs')), 'seconds': round(seconds, 1), 'defInjected': len(entries), 'keyed': sum(e.kind == 'Keyed' for e in result.entries),
        'classes': dict(classes), 'proven_reference': dict(proven), 'proven_total': sum(proven.values()),
        'languages': len(languages), 'truth_total': sum(truth.values()),
        'truth_hit': sum(min(n, truth[k]) for k, n in tool.items()),
        'diagnostics': len(result.diagnostics), 'flagged': flagged,
        'truth_missed': sorted('.'.join(k[1:]) for k in truth if k not in tool)[:3000],
        'sample': [[e.id, e.english[:80], attribute_class(e)] for e in entries if attribute_class(e) != 'attributed'][:400],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=('dev', 'holdout', 'all'), default='all')
    parser.add_argument('--game', type=Path)
    parser.add_argument('--dir', type=Path, help='measure every sub-folder of DIR as one mod (e.g. a Workshop content folder)')
    parser.add_argument('--ids', type=Path, help='JSON list of sub-folder names to keep when --dir is used')
    parser.add_argument('--schema', choices=('game', 'builtin', 'mod', 'none'), default='game',
                        help='type information given to the scan: game + mod DLLs, shipped field table + mod DLLs, '
                             'mod DLLs only, or none')
    parser.add_argument('--limit', type=int, help='measure only the first N fetched mods of the manifest')
    parser.add_argument('--cache', type=Path, default=ROOT / 'artifacts/corpus')
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/bench/latest.json')
    args = parser.parse_args()
    if args.dir:
        keep = set(json.loads(args.ids.read_text())) if args.ids else None
        manifest = [{'repository': child.name, 'split': 'workshop', 'path': child}
                    for child in sorted(args.dir.iterdir()) if child.is_dir() and (keep is None or child.name in keep)]
    else:
        manifest = json.loads((ROOT / 'tools/corpus/manifest.json').read_text())['mods']
    game = game_root(args.game)
    work = ROOT / 'artifacts/bench'
    core_defs, core_keyed = core_context(game, work)
    rows = []
    for mod in manifest:
        if args.split != 'all' and mod['split'] != args.split:
            continue
        base = mod.get('path') or args.cache / mod['repository'].replace('/', '__')
        if not base.is_dir():
            continue
        if args.limit is not None and len(rows) >= args.limit:
            break
        try:
            row = measure(base, game, core_defs, core_keyed, work / 'schema', args.schema)
        except Exception as exc:  # one bad mod must not hide the rest
            row = {'mod': base.name, 'error': repr(exc)[:160]}
        if row:
            row['split'] = mod['split']
            rows.append(row)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False))
    summarize(rows)


def summarize(rows):
    print(f"{'split':8}{'mods':>5}{'errors':>7}{'DefInj':>8}{'attrib':>8}{'unattr':>8}{'heur':>6}{'catlg':>6}{'proven-ref':>11}"
          f"{'(unattr)':>9}{'truth':>7}{'hit':>6}")
    for split in ('dev', 'holdout', 'workshop'):
        group = [r for r in rows if r['split'] == split]
        ok = [r for r in group if 'error' not in r]
        if not group:
            continue
        total = lambda key: sum(r['classes'].get(key, 0) for r in ok)
        print(f"{split:8}{len(group):>5}{len(group) - len(ok):>7}{sum(r['defInjected'] for r in ok):>8}{total('attributed'):>8}"
              f"{total('unattributed'):>8}{total('heuristic'):>6}{total('catalog'):>6}{sum(r['proven_total'] for r in ok):>11}"
              f"{sum(r['proven_reference'].get('unattributed', 0) for r in ok):>9}{sum(r['truth_total'] for r in ok):>7}"
              f"{sum(r['truth_hit'] for r in ok):>6}")
    for row in rows:
        if 'error' in row:
            print('ERROR', row['mod'], row['error'])


if __name__ == '__main__':
    main()
