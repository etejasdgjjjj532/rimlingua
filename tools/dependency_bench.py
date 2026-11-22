"""Measure how much prerequisite MODs reduce unknown fields, through the editor's own resolution path.

For each dependent MOD in the dependency corpus (artifacts/corpus-deps/manifest.json) and each game version it
declares, scan twice with the matching game from the user's game library:
  alone  game and the MOD only
  deps   the same, with the corpus framework MODs available as installed MOD folders
Prerequisites are found by scan_context.dependency_context, exactly as the editor finds them. DLLs are read as
metadata only; nothing is executed or written outside --out.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rimworld_translator.extraction import content_files, resolve_load_folders, scan  # noqa: E402
from rimworld_translator.game_library import game_dll, identify_game, library_game_roots  # noqa: E402
from rimworld_translator.platforms import GameInstallation  # noqa: E402
from rimworld_translator.scan_context import dependency_context, report_dependency_gaps  # noqa: E402
from rimworld_translator.schema import schema_from_assemblies  # noqa: E402
from precision_bench import mod_root  # noqa: E402

VERSIONS = ('1.1', '1.2', '1.3', '1.4', '1.5', '1.6')


def dependents(deps: Path):
    manifest = json.loads((deps / 'manifest.json').read_text(encoding='utf-8'))
    seen = {}
    for entry in manifest['frameworks'].values():
        for dependent in entry['dependents']:
            folder = deps / 'dependents' / dependent['repository'].replace('/', '__')
            top = next(p for p in folder.iterdir() if p.is_dir())
            seen[dependent['repository']] = top / dependent['mod_root'] if dependent['mod_root'] else top
    frameworks = [mod_root(deps / 'frameworks' / entry['repository'].replace('/', '__'))
                  for entry in manifest['frameworks'].values()]
    return seen, [f for f in frameworks if f is not None]


def library_games(library: Path):
    games = {}
    for root in library_game_roots(library):
        identity = identify_game(root)
        if not identity.problem:
            games.setdefault(identity.version, GameInstallation(root, root / 'Mods', None, identity.build, None))
    return games


def measure(root: Path, version: str, game: GameInstallation, extra, cache: Path):
    context = dependency_context(game, (), root, version, None, extra_mod_paths=extra)
    assemblies = [game_dll(game.root)]
    for folder in (root, *context.sources):
        assemblies += content_files(resolve_load_folders(folder, version, None), 'Assemblies', '.dll')
    schema = schema_from_assemblies(assemblies, cache)
    result = scan(root, version, None, None, None, None, schema, context.sources, 100000)
    report_dependency_gaps(result, context, schema)
    codes = [d.get('code') for d in result.diagnostics]
    missing = next((d for d in result.diagnostics if d.get('code') == 'missing-dependency'), {})
    return {'definjected': sum(e.kind == 'DefInjected' for e in result.entries),
            'keyed': sum(e.kind == 'Keyed' for e in result.entries),
            'unknown_field': codes.count('unknown-field'),
            'missing_dependencies': missing.get('package_ids', []),
            'missing_dependency_count': missing.get('count', 0)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--deps', type=Path, default=Path('artifacts/corpus-deps'))
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    results = args.out / 'results.jsonl'
    done = {(r['mod'], r['version'], r['condition']) for r in map(json.loads, results.read_text().splitlines())} \
        if results.exists() else set()
    mods, frameworks = dependents(args.deps)
    games = library_games(args.library)
    from rimworld_translator.installation import read_mod_metadata
    for repository, root in sorted(mods.items()):
        declared = set(read_mod_metadata(root).supported_versions)
        for version in [v for v in VERSIONS if v in declared and v in games]:
            for condition, extra in (('alone', ()), ('deps', frameworks)):
                if (repository, version, condition) in done:
                    continue
                started = time.perf_counter()
                try:
                    record = {'mod': repository, 'version': version, 'condition': condition,
                              **measure(root, version, games[version], extra, args.out / 'schema-cache')}
                except Exception as exc:  # one broken MOD must not stop the run
                    record = {'mod': repository, 'version': version, 'condition': condition, 'error': repr(exc)[:300]}
                record['seconds'] = round(time.perf_counter() - started, 1)
                with results.open('a', encoding='utf-8') as out:
                    out.write(json.dumps(record) + '\n')
                print(repository, version, condition, record.get('definjected', record.get('error')),
                      record.get('unknown_field'), flush=True)
    summarize(results)


def summarize(results: Path):
    """Totals over each MOD's newest measured version, per condition."""
    from rimworld_translator.extraction import version_tuple
    rows = [r for r in map(json.loads, results.read_text().splitlines()) if 'error' not in r]
    newest = {}
    for row in rows:
        if row['mod'] not in newest or version_tuple(row['version']) > version_tuple(newest[row['mod']]):
            newest[row['mod']] = row['version']
    for condition in ('alone', 'deps'):
        chosen = [r for r in rows if r['condition'] == condition and r['version'] == newest[r['mod']]]
        print(condition, 'mods', len(chosen), 'definjected', sum(r['definjected'] for r in chosen),
              'unknown_field', sum(r['unknown_field'] for r in chosen))
    print('errors', sum(1 for r in map(json.loads, results.read_text().splitlines()) if 'error' in r))


if __name__ == '__main__':
    main()
