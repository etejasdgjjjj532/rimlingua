"""Compare the keys the scan writes for the game's Core Defs with the official Japanese DefInjected keys.

    python tools/compare_handle_keys.py --out artifacts/handle-keys.json

The installed game is only read: Core's Defs are scanned in place, the official Japanese archive is read
in memory. Two scans are made on the same Defs and the same game metadata: with the rule that copies
`untranslatedX` from `X` (list items keyed by handle) and with it switched off (list items keyed by index,
the scan before this rule). Keys are compared as exact strings. Static analysis only; nothing here shows
what a running game displays.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lxml import etree  # noqa: E402
from rimworld_translator.extraction import scan  # noqa: E402
from rimworld_translator.schema import schema_from_assemblies  # noqa: E402

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
FOCUS = ('HediffDef', 'ThoughtDef', 'ThingDef')


def game_root(explicit: Path | None) -> Path:
    for candidate in ([explicit] if explicit else []) + [Path.home() / '.local/share/Steam/steamapps/common/RimWorld']:
        if candidate and candidate.is_dir():
            return candidate
    raise SystemExit('RimWorld installation not found; pass --game')


def official_keys(archive: Path) -> dict[str, set[str]]:
    """DefInjected keys of the official translation, by the folder (Def type) that holds them."""
    keys = defaultdict(set)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if not member.isfile() or len(parts) < 3 or parts[0] != 'DefInjected' or not member.name.endswith('.xml'):
                continue
            root = etree.fromstring(tar.extractfile(member).read(), PARSER)
            keys[parts[1]].update(node.tag for node in root if isinstance(node.tag, str))
    return keys


def scanned_keys(core: Path, version: str, schema) -> dict[str, set[str]]:
    result = scan(core, version, None, None, None, None, schema, (), None)
    keys = defaultdict(set)
    for entry in result.entries:
        if entry.kind == 'DefInjected':
            keys[entry.group].add(entry.key)
    return keys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--unmatched', type=int, default=20, help='unmatched official keys to list per Def type')
    args = parser.parse_args()
    game = game_root(args.game)
    version = '.'.join((game / 'Version.txt').read_text().split()[0].split('.')[:2])
    dll = next(game.glob('*_Data/Managed/Assembly-CSharp.dll'))
    with tempfile.TemporaryDirectory(prefix='handle-keys-') as cache:
        schema = schema_from_assemblies([dll], Path(cache))
    # A schema built from another version's table disables the copy rule, which gives the index-key scan.
    index_schema = copy.copy(schema)
    index_schema.builtin_version = '0.0'
    official = official_keys(next((game / 'Data/Core/Languages').glob('Japanese*.tar')))
    handle = scanned_keys(game / 'Data/Core', version, schema)
    index = scanned_keys(game / 'Data/Core', version, index_schema)
    rows = {}
    for group in sorted(official):
        wanted = official[group]
        rows[group] = {'official': len(wanted), 'handle_scan': len(wanted & handle.get(group, set())),
                       'index_scan': len(wanted & index.get(group, set())),
                       'unmatched_handle_scan': sorted(wanted - handle.get(group, set()))[:args.unmatched]}
    total = Counter()
    for row in rows.values():
        total.update({name: row[name] for name in ('official', 'handle_scan', 'index_scan')})
    report = {'game_version': (game / 'Version.txt').read_text().strip(), 'assembly': dll.name,
              'total': dict(total), 'groups': rows}
    print(f"{'group':28}{'official':>10}{'handle':>9}{'index':>8}")
    for group, row in rows.items():
        if group in FOCUS or row['handle_scan'] != row['index_scan']:
            print(f"{group:28}{row['official']:>10}{row['handle_scan']:>9}{row['index_scan']:>8}")
    print(f"{'ALL':28}{total['official']:>10}{total['handle_scan']:>9}{total['index_scan']:>8}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
