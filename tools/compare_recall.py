"""Compare precision_bench.py result files measured on the same mods under different conditions.

    python tools/compare_recall.py game=artifacts/bench/game.json none=artifacts/bench/none.json

Recall is counted only on mods that ship community translations and have Defs of their own. A
repository that holds nothing but translations of other mods has no source to extract from, so its
keys say nothing about extraction; such repositories are listed and left out. Both the pooled recall
(large mods dominate) and the per-mod median are shown.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('results', nargs='+', help='label=path pairs')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    runs = {}
    for item in args.results:
        label, path = item.split('=', 1)
        runs[label] = {row['mod']: row for row in json.loads(Path(path).read_text()) if 'error' not in row}
    common = set.intersection(*(set(rows) for rows in runs.values()))

    def has_defs(mod):
        rows = [run[mod] for run in runs.values()]
        if any('def_files' in row for row in rows):
            return any(row.get('def_files', 0) for row in rows)
        return any(row['defInjected'] for row in rows)  # older result files: nothing extracted under any condition

    with_truth = sorted(mod for mod in common if next(iter(runs.values()))[mod]['truth_total'])
    excluded = [mod for mod in with_truth if not has_defs(mod)]
    kept = [mod for mod in with_truth if has_defs(mod)]
    first = next(iter(runs.values()))
    lines = [f'mods measured under every condition: {len(common)}',
             f'  with community translations: {len(with_truth)}',
             f'  left out, no Defs of their own (translation-only): {len(excluded)} '
             f'({sum(first[m]["truth_total"] for m in excluded)} keys)',
             f'  counted: {len(kept)} mods, {sum(first[m]["truth_total"] for m in kept)} community-translated keys', '',
             f"{'condition':10}{'DefInj':>9}{'hit':>8}{'pooled':>9}{'median':>9}{'mods<50%':>10}{'proven-ref':>12}{'per 1000':>10}"]
    table = {}
    for label, rows in runs.items():
        truth = sum(rows[m]['truth_total'] for m in kept)
        hit = sum(rows[m]['truth_hit'] for m in kept)
        per_mod = [rows[m]['truth_hit'] / rows[m]['truth_total'] for m in kept]
        extracted = sum(rows[m]['defInjected'] for m in common)
        proven = sum(rows[m]['proven_total'] for m in common)
        table[label] = {'defInjected': extracted, 'truth': truth, 'hit': hit, 'pooled_recall': round(hit / truth, 4),
                        'median_recall': round(statistics.median(per_mod), 4),
                        'mods_below_half': sum(value < 0.5 for value in per_mod), 'proven_reference': proven,
                        'proven_per_1000': round(1000 * proven / max(extracted, 1), 2)}
        row = table[label]
        lines.append(f"{label:10}{extracted:>9}{hit:>8}{row['pooled_recall']:>9.1%}{row['median_recall']:>9.1%}"
                     f"{row['mods_below_half']:>10}{proven:>12}{row['proven_per_1000']:>10}")
    lines += ['', 'translation-only repositories left out: ' + ', '.join(excluded)]
    text = '\n'.join(lines)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'mods': len(common), 'counted': len(kept), 'excluded': excluded, 'conditions': table},
                                       indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
