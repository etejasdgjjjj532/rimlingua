"""List the string fields RimWorld's own assembly declares, with their owning class.

Reads Assembly-CSharp.dll as ECMA-335 metadata only (rimworld_translator.schema.inspect_assembly);
nothing is loaded or executed. For every class the output separates
  must    string / List<string> fields carrying [MustTranslate]
  may     ... carrying [MayTranslate]
  plain   string fields with neither attribute (DefInjected can still target them)
  no      string fields carrying [NoTranslate] or [Unsaved]
and records the base class, so inherited fields can be resolved without the game.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rimworld_translator.schema import TranslationSchema, inspect_assembly  # noqa: E402


def classify(spec) -> str:
    if spec.forbidden:
        return 'no'
    if 'MustTranslateAttribute' in spec.attributes:
        return 'must'
    if 'MayTranslateAttribute' in spec.attributes:
        return 'may'
    return 'plain'


def dump(game: Path) -> dict:
    dll = next(game.glob('*_Data/Managed/Assembly-CSharp.dll'))
    types = inspect_assembly(dll)
    schema = TranslationSchema(types=types)
    version = (game / 'Version.txt').read_text(encoding='utf-8').strip()
    out = {}
    for name, typ in sorted(types.items()):
        groups = {'must': [], 'may': [], 'plain': [], 'no': []}
        for field_name, spec in typ.fields.items():
            if spec.type_name != 'System.String':
                continue
            groups[classify(spec)].append(field_name + ('[]' if spec.is_list else ''))
        if any(groups.values()):
            out[name] = {'base': typ.base, 'is_def': schema.is_def(name),
                         **{key: sorted(value) for key, value in groups.items() if value}}
    return {'rimworld_version': version, 'assembly': dll.name,
            'assembly_sha256': hashlib.sha256(dll.read_bytes()).hexdigest(),
            'assembly_bytes': dll.stat().st_size, 'method': 'static ECMA-335 metadata read; no code executed',
            'types': out}


def summary(data: dict) -> str:
    types = data['types']
    count = Counter()
    for item in types.values():
        for key in ('must', 'may', 'plain', 'no'):
            count[key] += len(item.get(key, ()))
            if item['is_def']:
                count['def_' + key] += len(item.get(key, ()))
    lines = [
        '# RimWorld string fields by owning class', '',
        f"- RimWorld version: `{data['rimworld_version']}`",
        f"- Assembly: `{data['assembly']}` ({data['assembly_bytes']} bytes)",
        f"- SHA-256: `{data['assembly_sha256']}`",
        f"- Method: {data['method']} (`tools/dump_game_text_fields.py`)", '',
        'Static metadata only. An attribute states what the game declares, not what a player sees in a given build.', '',
        '| group | all classes | Def classes |', '|---|---:|---:|',
        *(f"| {label} | {count[key]} | {count['def_' + key]} |" for key, label in (
            ('must', '[MustTranslate]'), ('may', '[MayTranslate]'),
            ('plain', 'string, no attribute'), ('no', '[NoTranslate] / [Unsaved]'))),
        '', f"Classes with at least one string field: {len(types)} "
        f"({sum(item['is_def'] for item in types.values())} are Defs).", '',
        '## Fields carrying [MustTranslate] or [MayTranslate]', '',
        '| owner | base | MustTranslate | MayTranslate |', '|---|---|---|---|',
    ]
    for name, item in types.items():
        if item.get('must') or item.get('may'):
            lines.append(f"| `{name}` | `{item['base']}` | {', '.join(item.get('must', []))} | {', '.join(item.get('may', []))} |")
    lines += ['', 'The complete list, including unattributed string fields, is in `fields.json`.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='directory for fields.json and README.md')
    args = parser.parse_args()
    data = dump(args.game)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'fields.json').write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (args.out / 'README.md').write_text(summary(data), encoding='utf-8')
    print(summary(data).split('## ')[0])


if __name__ == '__main__':
    main()
