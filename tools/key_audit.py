"""Key audit: scan MODs the way the editor does and score the keys against independent answer keys (read-only).

Answer keys never come from the extraction rules under test:
  T  the MOD's own non-English translations (Languages/<other>/DefInjected|Keyed) in any load folder of the version,
     limited to keys of the MOD's own Def names and English Keyed keys (recall = share of them extracted)
  O  the Def type + field patterns the official RimWorld translations translate (Languages/*.tar of the game library)
  A  a CLR MustTranslate/MayTranslate attribute on the field (the game's own statement)
  K  an English Keyed catalog entry (the game's UI string route)
Proven internal values (equal to a Def name, a Keyed key or a texture path of the MOD or the game) are false entries.

Commands:
  official --library LIB --out official.jsonl
      Field patterns of the official Japanese / Simplified Chinese translations in the library.
  corpus --library LIB [--mods DIR ...] [--holdout-manifest FILE] [--context DIR ...] --out corpus.json
      A verification corpus from the user's MOD folders (default: the installed games' Mods and Workshop folders),
      each MOD with the prerequisites found among those folders. Only paths are written; nothing is copied.
  run --library LIB --corpus corpus.json --official official.jsonl --out DIR [--limit N] [--only NAME ...]
      Scan every MOD (resumable) into DIR/rows.jsonl and DIR/scores.jsonl, then print the summary.
  score --corpus corpus.json --official official.jsonl --out DIR
      Score the rows of an earlier run again without scanning.
  summary DIR [DIR2]
      Print the totals of a run, or the change from DIR to DIR2.

MOD DLLs are read as metadata only and never executed. No game or MOD content is copied; output stays under --out.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gc
import inspect
import json
from pathlib import Path
import re
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from lxml import etree  # noqa: E402

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, remove_comments=True)
FIELD = re.compile(r'[a-z][A-Za-z0-9_]*')
KEEP = {'unknown-field', 'internal-value', 'non-localizable-field', 'duplicate'}
OFFICIAL_LANGUAGES = ('Japanese', 'ChineseSimplified')


def shape(group: str, key: str):
    """(Def type without namespace, first field, leaf field) of a DefInjected key; indexes and handles are ignored."""
    fields = [p for p in key.split('.')[1:] if FIELD.fullmatch(p)]
    return (group.rsplit('.', 1)[-1], fields[0], fields[-1]) if fields else (group.rsplit('.', 1)[-1], '', '')


def all_load_folders(root: Path, version: str) -> list[Path]:
    """Every folder the version may load, whatever its IfModActive/IfModNotActive condition says."""
    from rimworld_translator.extraction import resolve_load_folders, version_tuple
    file = root / 'LoadFolders.xml'
    if file.is_file():
        try:
            tree = etree.parse(str(file), PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            tree = None
        if tree is not None:
            branches = {e.tag.lstrip('v'): e for e in tree if isinstance(e.tag, str)}
            older = [v for v in branches if re.fullmatch(r'\d+(?:\.\d+)+', v) and version_tuple(v) <= version_tuple(version)]
            chosen = branches.get(version)
            if chosen is None:
                chosen = branches[max(older, key=version_tuple)] if older else branches.get('default')
            if chosen is not None:
                folders = []
                for item in chosen:
                    relative = (item.text or '').strip().replace('\\', '/').strip('/')
                    folder = (root / relative) if relative else root
                    if item.tag == 'li' and '..' not in Path(relative).parts and folder.is_dir():
                        folders.append(folder)
                return list(dict.fromkeys(folders))
    return resolve_load_folders(root, version, set())


def translated_keys(root: Path, version: str) -> set[tuple[str, str]]:
    """(kind, key casefolded) of every non-empty value in the MOD's own non-English language folders."""
    keys = set()
    for folder in all_load_folders(root, version):
        languages = folder / 'Languages'
        if not languages.is_dir():
            continue
        for language in languages.iterdir():
            if not language.is_dir() or language.name.casefold().startswith('english'):
                continue
            for kind in ('DefInjected', 'Keyed'):
                for file in sorted((language / kind).rglob('*.xml')) if (language / kind).is_dir() else ():
                    try:
                        tree = etree.parse(str(file), PARSER).getroot()
                    except (OSError, etree.XMLSyntaxError):
                        continue
                    for child in tree if tree is not None else ():
                        if isinstance(child.tag, str) and (child.text or '').strip():
                            keys.add((kind, child.tag.casefold()))
    return keys


def mod_names(root: Path, version: str) -> tuple[set[str], set[str]]:
    """Def names (in Defs and Patches) and English Keyed keys of every folder the version may load."""
    from rimworld_translator.extraction import content_files
    folders = all_load_folders(root, version)
    defs, keyed = set(), set()
    for file in [*content_files(folders, 'Defs'), *content_files(folders, 'Patches')]:
        try:
            defs.update((n.text or '').strip() for n in etree.parse(str(file), PARSER).getroot().iter('defName'))
        except (OSError, etree.XMLSyntaxError, AttributeError):
            continue
    for file in content_files(folders, 'Languages/English/Keyed'):
        try:
            keyed.update(c.tag for c in etree.parse(str(file), PARSER).getroot() if isinstance(c.tag, str))
        except (OSError, etree.XMLSyntaxError, TypeError):
            continue
    return defs - {''}, keyed


def answerable(truth, root: Path, version: str) -> set[tuple[str, str]]:
    """Answer keys for text the MOD itself defines: its Def names or its English Keyed keys."""
    defs, keyed = mod_names(root, version)
    defs, keyed = {d.casefold() for d in defs}, {k.casefold() for k in keyed}
    return {(kind, key) for kind, key in truth
            if (kind == 'Keyed' and key in keyed) or (kind == 'DefInjected' and key.split('.', 1)[0] in defs)}


def internal_names(root: Path, version: str, extra=frozenset()) -> set[str]:
    """Def names, Keyed keys and texture paths (casefolded) a value can only refer to, never translate."""
    defs, keyed = mod_names(root, version)
    names = set(extra) | defs | keyed
    for folder in all_load_folders(root, version):
        textures = folder / 'Textures'
        if textures.is_dir():
            names.update(p.relative_to(textures).with_suffix('').as_posix().casefold()
                         for p in textures.rglob('*') if p.suffix.casefold() in {'.png', '.jpg', '.jpeg', '.psd', '.dds'})
    return names - {''}


def _row_key(row):
    """(group, key) of an entry or diagnostic row."""
    if row['cat'] == 'entry':
        return row['group'], row['key']
    if row['cat'] == 'unknown-field':
        return row.get('owner', ''), row.get('path', '')
    parts = row.get('entry_id', '').split(':', 2)
    return (parts[1], parts[2]) if len(parts) == 3 else (row.get('owner', ''), row.get('path', ''))


def evidence(row, truth, official) -> str:
    group, key = _row_key(row)
    kind = row.get('kind', 'DefInjected')
    found = []
    if row['cat'] == 'entry' and kind == 'Keyed':
        found.append('K')
    if kind == 'DefInjected' and shape(group, key) in official:
        found.append('O')
    if any('MustTranslate' in e or 'MayTranslate' in e for e in row.get('ev', ())):
        found.append('A')
    if (kind, key.casefold()) in truth:
        found.append('T')
    return ''.join(found)


def score_rows(rows, truth, official, internal_names=frozenset()) -> dict:
    """Counts of one MOD: answer keys found, entries with and without evidence, proven internal entries."""
    folded = {name.casefold() for name in internal_names}
    extracted = set()
    score = Counter(truth=len(truth))
    for row in rows:
        if row['cat'] == 'entry':
            extracted.add((row['kind'], row['key'].casefold()))
            score['entries'] += 1
            score['blocked'] += bool(row.get('blocked'))
            score['evidenced'] += bool(evidence(row, truth, official))
            value = (row.get('text') or '').strip()
            if row['kind'] == 'DefInjected' and (value in internal_names or ('/' in value and value.casefold() in folded)):
                score['proven_internal'] += 1
        elif row['cat'] in KEEP - {'duplicate'} and evidence(row, truth, official):
            score['official_missed' if 'O' in evidence(row, truth, official) else 'translated_missed'] += 1
    score['truth_hit'] = len(truth & extracted)
    return dict(score)


def summarize(scores) -> dict:
    total = Counter()
    for score in scores:
        total.update({k: v for k, v in score.items() if isinstance(v, int)})
    total = dict(total)
    total['recall'] = total.get('truth_hit', 0) / total['truth'] if total.get('truth') else 0.0
    entries = total.get('entries', 0)
    total['precision'] = 1 - total.get('proven_internal', 0) / entries if entries else 0.0
    total['evidenced_share'] = total.get('evidenced', 0) / entries if entries else 0.0
    return total


def official_patterns(library: Path, out_file: Path):
    found = {}
    for tar_path in sorted(library.glob('*/*/Data/*/Languages/*.tar')):
        if not tar_path.name.startswith(OFFICIAL_LANGUAGES):
            continue
        with tarfile.open(tar_path) as tar:
            for member in tar.getmembers():
                parts = member.name.replace('\\', '/').split('/')
                if not member.isfile() or not member.name.endswith('.xml') or parts[0] != 'DefInjected' or len(parts) < 3:
                    continue
                try:
                    tree = etree.fromstring(tar.extractfile(member).read(), PARSER)
                except etree.XMLSyntaxError:
                    continue
                for child in tree if tree is not None else ():
                    if isinstance(child.tag, str):
                        found.setdefault(shape(parts[1], child.tag), child.tag)
    with out_file.open('w', encoding='utf-8') as out:
        for (group, first, leaf), sample in sorted(found.items()):
            out.write(json.dumps({'group': group, 'first': first, 'leaf': leaf, 'sample': sample}) + '\n')
    print(len(found), 'official DefInjected field patterns')


def load_official(path: Path) -> set:
    return {(r['group'], r['first'], r['leaf']) for r in map(json.loads, path.read_text(encoding='utf-8').splitlines())}


def _games(library):
    from dependency_bench import library_games
    return library_games(library)


def _version(root, games):
    from precision_bench import mod_version
    from rimworld_translator.extraction import version_tuple
    version = mod_version(root)
    if version not in games:
        newer = [v for v in games if version_tuple(v) >= version_tuple(version)]
        version = min(newer, key=version_tuple) if newer else max(games, key=version_tuple)
    return version


def build_corpus(library: Path, mod_dirs, holdout_manifest: Path | None, out: Path, context_dirs=()):
    """Mod roots under the folders, each with the prerequisites found among them and the context folders."""
    from precision_bench import mod_root
    from rimworld_translator.scan_context import dependency_context
    games = _games(library)
    if not mod_dirs and holdout_manifest is None:
        from rimworld_translator.platforms import discover_installations
        mod_dirs = [p for g in discover_installations() for p in (g.mods, g.workshop) if p and p.is_dir()]
    targets = []
    for folder in mod_dirs:
        for child in sorted(Path(folder).iterdir()):
            root = child if (child / 'About/About.xml').is_file() else (mod_root(child) if child.is_dir() else None)
            if root is not None:
                targets.append((f'{Path(folder).name}/{child.name}', root, None))
    if holdout_manifest is not None:
        for item in json.loads(holdout_manifest.read_text(encoding='utf-8'))['mods']:
            targets.append((item['repo'].replace('/', '__'), Path(item['root']), item.get('scan_version')))
    every = [root for _name, root, _v in targets]
    for folder in context_dirs:
        every += [child for child in sorted(Path(folder).iterdir()) if (child / 'About/About.xml').is_file()]
    mods = []
    for name, root, version in targets:
        version = version if version in games else _version(root, games)
        context = dependency_context(games[version], (), root, version, None, extra_mod_paths=every)
        mods.append({'name': name, 'root': str(root), 'version': version,
                     'prerequisites': [str(p) for p in context.sources],
                     'missing': [d.package_id for d in context.missing]})
    out.write_text(json.dumps({'library': str(library), 'mods': mods}, indent=1, ensure_ascii=False), encoding='utf-8')
    print(len(mods), 'MODs;', sum(bool(m['missing']) for m in mods), 'with missing prerequisites')


def scan_one(item, games, schema_cache: Path):
    """Scan one MOD like the editor with an unknown active-MOD list; returns (scan result, game)."""
    from rimworld_translator.extraction import content_files, resolve_load_folders, scan
    from rimworld_translator.game_library import game_dll
    from rimworld_translator.scan_context import dependency_context
    from rimworld_translator.schema import schema_from_assemblies
    root, version = Path(item['root']), item['version']
    game = games[version]
    context = dependency_context(game, (), root, version, None, extra_mod_paths=item.get('prerequisites', ()))
    assumed = getattr(context, 'assumed_active', None)
    assemblies = [game_dll(game.root)]
    for folder in (root, *context.sources):
        assemblies += content_files(resolve_load_folders(folder, version, assumed), 'Assemblies', '.dll')
    schema = schema_from_assemblies(assemblies, schema_cache)
    options = {}
    if assumed is not None and 'assumed_active' in inspect.signature(scan).parameters:
        options['assumed_active'] = assumed
    return scan(root, version, None, None, None, None, schema, context.sources, 100000, **options), game


def rows_of(name, version, result):
    rows = []
    for e in result.entries:
        rows.append({'mod': name, 'v': version, 'cat': 'entry', 'kind': e.kind, 'group': e.group, 'key': e.key,
                     'text': e.english[:400], 'conf': e.confidence, 'blocked': e.blocked,
                     'reasons': list(getattr(e, 'reasons', ())),
                     'ev': [x for x in e.evidence if x.startswith(('CLR ', 'Unattributed', 'Field-name', 'Unverified'))][:2]})
    for d in result.diagnostics:
        if d.get('code') in KEEP:
            text = d.get('source_text') or ''
            if not text:
                match = re.search(r" = (['\"])(.*)\1 \(", d.get('message', ''))
                text = match.group(2) if match else ''
            rows.append({'mod': name, 'v': version, 'cat': d['code'], 'entry_id': d.get('entry_id', ''),
                         'owner': d.get('owner_type', ''), 'path': d.get('field_path', ''), 'text': text[:400],
                         'value_kind': d.get('value_kind', '')})
    return rows


def run(corpus: Path, official_file: Path, out: Path, limit=None, only=()):
    from rimworld_translator.game_library import child
    data = json.loads(corpus.read_text(encoding='utf-8'))
    games = _games(Path(data['library']))
    official = load_official(official_file)
    out.mkdir(parents=True, exist_ok=True)
    scores_file = out / 'scores.jsonl'
    done = {json.loads(line)['mod'] for line in scores_file.read_text().splitlines()} if scores_file.exists() else set()
    game_names = {}
    for count, item in enumerate(data['mods']):
        if limit is not None and count >= limit:
            break
        if item['name'] in done or (only and item['name'] not in only):
            continue
        started = time.perf_counter()
        try:
            result, game = scan_one(item, games, out / 'schema-cache')
            if game.root not in game_names:
                core = child(game.root, 'Data')
                game_names[game.root] = internal_names(core / 'Core', item['version']) if core is not None else set()
            rows = rows_of(item['name'], item['version'], result)
            score = score_mod(item, rows, official, game_names[game.root])
        except Exception as exc:  # one broken MOD must not stop the run
            rows, score = [], {'error': repr(exc)[:300]}
        score.update(mod=item['name'], version=item['version'], seconds=round(time.perf_counter() - started, 1))
        with (out / 'rows.jsonl').open('a', encoding='utf-8') as stream:
            stream.writelines(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
        with scores_file.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(score) + '\n')
        print(item['name'], item['version'], score.get('entries', score.get('error')), score['seconds'], flush=True)
        gc.collect()
    print_summary(out)


def score_mod(item, rows, official, game_names=frozenset()):
    root, version = Path(item['root']), item['version']
    truth = answerable(translated_keys(root, version), root, version)
    return score_rows(rows, truth, official, internal_names(root, version, game_names))


def rescore(corpus: Path, official_file: Path, out: Path):
    """Score the rows of an earlier run again (after a change of the answer keys), without scanning."""
    from rimworld_translator.game_library import child
    data = json.loads(corpus.read_text(encoding='utf-8'))
    games, official = _games(Path(data['library'])), load_official(official_file)
    items = {item['name']: item for item in data['mods']}
    rows = {}
    for line in (out / 'rows.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        rows.setdefault(row['mod'], []).append(row)
    game_names, scores = {}, []
    for old in _scores(out):
        if 'error' in old:
            scores.append(old)
            continue
        item = items[old['mod']]
        game = games[item['version']]
        if game.root not in game_names:
            core = child(game.root, 'Data')
            game_names[game.root] = internal_names(core / 'Core', item['version']) if core is not None else set()
        score = score_mod(item, rows.get(old['mod'], []), official, game_names[game.root])
        score.update(mod=old['mod'], version=old['version'], seconds=old.get('seconds'))
        scores.append(score)
    (out / 'scores.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in scores), encoding='utf-8')
    print_summary(out)


def _scores(directory: Path):
    return [json.loads(line) for line in (directory / 'scores.jsonl').read_text().splitlines()]


COLUMNS = ('truth', 'truth_hit', 'recall', 'entries', 'evidenced', 'evidenced_share', 'proven_internal', 'precision',
           'blocked', 'official_missed', 'translated_missed')


def print_summary(before: Path, after: Path | None = None):
    first = _scores(before)
    totals = [summarize([s for s in first if 'error' not in s])]
    if after is not None:
        names = {s['mod'] for s in first}
        second = [s for s in _scores(after) if s['mod'] in names]
        common = {s['mod'] for s in second}
        totals = [summarize([s for s in first if 'error' not in s and s['mod'] in common]),
                  summarize([s for s in second if 'error' not in s])]
    print(f'mods {len(first)}  errors {sum("error" in s for s in first)}')
    for column in COLUMNS:
        values = [t.get(column, 0) for t in totals]
        cells = [f'{v:.4f}' if isinstance(v, float) else str(v) for v in values]
        if len(values) == 2:
            delta = values[1] - values[0]
            cells.append(f'{delta:+.4f}' if isinstance(delta, float) else f'{delta:+d}')
        print(f'{column:18}' + ''.join(f'{c:>12}' for c in cells))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    official = commands.add_parser('official')
    official.add_argument('--library', type=Path, required=True)
    official.add_argument('--out', type=Path, required=True)
    corpus = commands.add_parser('corpus')
    corpus.add_argument('--library', type=Path, required=True)
    corpus.add_argument('--mods', type=Path, action='append', default=[])
    corpus.add_argument('--holdout-manifest', type=Path)
    corpus.add_argument('--context', type=Path, action='append', default=[],
                        help='MOD folder searched for prerequisites only (e.g. the Workshop folder)')
    corpus.add_argument('--out', type=Path, required=True)
    runner = commands.add_parser('run')
    runner.add_argument('--corpus', type=Path, required=True)
    runner.add_argument('--official', type=Path, required=True)
    runner.add_argument('--out', type=Path, required=True)
    runner.add_argument('--limit', type=int)
    runner.add_argument('--only', action='append', default=[])
    rescorer = commands.add_parser('score')
    rescorer.add_argument('--corpus', type=Path, required=True)
    rescorer.add_argument('--official', type=Path, required=True)
    rescorer.add_argument('--out', type=Path, required=True)
    summary = commands.add_parser('summary')
    summary.add_argument('directories', type=Path, nargs='+')
    args = parser.parse_args(argv)
    if args.command == 'official':
        official_patterns(args.library, args.out)
    elif args.command == 'corpus':
        build_corpus(args.library, args.mods, args.holdout_manifest, args.out, args.context)
    elif args.command == 'run':
        run(args.corpus, args.official, args.out, args.limit, set(args.only))
    elif args.command == 'score':
        rescore(args.corpus, args.official, args.out)
    else:
        print_summary(*args.directories[:2])


if __name__ == '__main__':
    main()
