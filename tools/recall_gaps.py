"""Explain the community-translated keys the scan did not extract, one cause per key.

Companion to tools/precision_bench.py (same corpus, same key normalization). For every missed key the
mod's own XML is consulted, independently of the extraction rules:

  def-absent          no Def of that name in the folders active for the scanned version
    other-version       ... but one exists in another version folder of the mod
    nowhere             ... and nowhere in the mod (another mod's Def, a removed Def, or one made by code)
  field-in-xml        the Def's own XML writes that field, yet no entry was produced; split into
                      def-mayrequire (the Def loads only with another mod, excluded by design), the
                      diagnostic the scan recorded for it, or "no-diagnostic"
  inherited-in-mod    the field is only on an XML parent inside the mod
  not-in-xml          neither the Def nor its in-mod parents write the field (game default, parent in
                      another mod or Core, or a translation of something code generates)

No mod code is executed; DLLs are read as metadata only.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from lxml import etree  # noqa: E402
from precision_bench import PARSER, community_truth, game_root, mod_root, mod_version, norm  # noqa: E402
from rimworld_translator.extraction import content_files, resolve_load_folders, scan  # noqa: E402
from rimworld_translator.schema import game_table_schema, schema_from_assemblies  # noqa: E402


def defs_by_name(files):
    """defName -> Def elements, and Name attribute -> element, as written (no inheritance applied)."""
    named, parents = defaultdict(list), {}
    for file in files:
        try:
            root = etree.parse(str(file), PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        for node in root:
            if not isinstance(node.tag, str):
                continue
            if node.get('Name'):
                parents[node.get('Name')] = node
            name = (node.findtext('defName') or '').strip()
            if name:
                named[name].append(node)
    return named, parents


def has_field(node, first: str, leaf: str) -> bool:
    """Whether the Def writes ``leaf`` under its top-level element ``first`` (or ``first`` itself when they are equal).

    The Def's own <label> must not count for a key such as verbs.Verb_Shoot.label.
    """
    for top in node:
        if isinstance(top.tag, str) and top.tag.casefold() == first:
            if leaf == first or any(isinstance(e.tag, str) and e.tag.casefold() == leaf for e in top.iter() if e is not top):
                return True
    return False


def explain(base: Path, game: Path, schema_cache: Path, mode: str):
    root = mod_root(base)
    if root is None:
        return None
    version = mod_version(root)
    folders = resolve_load_folders(root, version, None)
    dll = next(game.glob('*_Data/Managed/Assembly-CSharp.dll'))
    mod_dlls = content_files(folders, 'Assemblies', '.dll')
    schema = schema_from_assemblies(([dll] if mode == 'game' else []) + mod_dlls, schema_cache,
                                    base=game_table_schema(schema_cache / 'game-table', [game]) if mode == 'builtin' else None)
    result = scan(root, version, None, None, None, None, schema, (game / 'Data/Core',) if mode == 'game' else (), None)
    tool = {norm(e.group, e.key) for e in result.entries if e.kind == 'DefInjected'}
    truth, _languages = community_truth(root)
    missed = [key for key in truth if key not in tool]
    if not missed:
        return []
    active, parents = defs_by_name(content_files(folders, 'Defs'))
    everywhere, _ = defs_by_name(sorted(p for p in root.rglob('*.xml') if 'Defs' in p.parts and 'Languages' not in p.parts))
    reasons = {}
    for item in result.diagnostics:
        target = item.get('field_path') or item.get('entry_id', '').split(':', 2)[-1]
        if target and '.' in target:
            reasons.setdefault(norm('', target), item['code'])
    rows = []
    for key in missed:
        _, def_name, first, leaf = key
        nodes = active.get(def_name)
        if not nodes:
            cause = 'def-absent/other-version' if def_name in everywhere else 'def-absent/nowhere'
        elif any(has_field(node, first, leaf) for node in nodes):
            conditional = all(any(name.casefold() in ('mayrequire', 'mayrequireanyof') for name in node.attrib)
                              for node in nodes if has_field(node, first, leaf))
            # A Def loaded only when another mod is active is outside a scan without that mod, by design.
            cause = 'field-in-xml/' + ('def-mayrequire' if conditional else reasons.get(key, 'no-diagnostic'))
        else:
            inherited, seen = False, set()
            queue = [node.get('ParentName') for node in nodes]
            while queue:
                name = queue.pop()
                if not name or name in seen or name not in parents:
                    continue
                seen.add(name)
                inherited = inherited or has_field(parents[name], first, leaf)
                queue.append(parents[name].get('ParentName'))
            cause = 'inherited-in-mod' if inherited else 'not-in-xml'
        tag = nodes[0].tag if nodes else ''
        rows.append([base.name, '.'.join(key[1:]), cause, tag])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path)
    parser.add_argument('--schema', choices=('game', 'builtin'), default='game')
    parser.add_argument('--cache', type=Path, default=ROOT / 'artifacts/corpus')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/bench/recall-gaps.json')
    args = parser.parse_args()
    game = game_root(args.game)
    rows, measured = [], 0
    for mod in json.loads((ROOT / 'tools/corpus/manifest.json').read_text())['mods']:
        base = args.cache / mod['repository'].replace('/', '__')
        if not base.is_dir():
            continue
        if args.limit is not None and measured >= args.limit:
            break
        measured += 1
        try:
            rows += explain(base, game, ROOT / 'artifacts/bench/schema', args.schema) or []
        except Exception as exc:  # one bad mod must not hide the rest
            rows.append([base.name, '', 'error/' + type(exc).__name__, ''])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False))
    causes = Counter(row[2] for row in rows)
    examples = defaultdict(list)
    for mod, key, cause, tag in rows:
        if len(examples[cause]) < 5:
            examples[cause].append(f'{mod}: {tag} {key}')
    print(f'mods {measured}, missed keys {len(rows)}')
    for cause, count in causes.most_common():
        print(f'{count:>7}  {cause}')
        for example in examples[cause]:
            print(f'           {example}')
    fields = Counter((row[3].rsplit('.', 1)[-1], row[1].rsplit('.', 1)[-1]) for row in rows if row[2].startswith('field-in-xml'))
    print('field-in-xml by Def tag and field:')
    for (tag, leaf), count in fields.most_common(40):
        print(f'{count:>7}  {tag}.{leaf}')


if __name__ == '__main__':
    main()
