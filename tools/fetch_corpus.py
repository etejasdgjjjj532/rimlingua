"""Fetch the pinned public mod sources listed in tools/corpus/manifest.json.

Sources are downloaded as GitHub tarballs at the recorded revision, extracted with
the data filter into artifacts/corpus/<owner>__<repo>, and never executed. Mod payloads
are not committed; artifacts/ is ignored.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tools/corpus/manifest.json'
CACHE = ROOT / 'artifacts/corpus'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=('dev', 'holdout', 'all'), default='all')
    parser.add_argument('--cache', type=Path, default=CACHE)
    args = parser.parse_args()
    mods = json.loads(MANIFEST.read_text())['mods']
    args.cache.mkdir(parents=True, exist_ok=True)
    for mod in mods:
        if args.split != 'all' and mod['split'] != args.split:
            continue
        destination = args.cache / mod['repository'].replace('/', '__')
        if destination.exists():
            continue
        result = subprocess.run(['gh', 'api', f"repos/{mod['repository']}/tarball/{mod['revision']}"],
                                capture_output=True)
        if result.returncode:
            print('FAILED', mod['repository'], result.stderr[:120].decode(errors='replace'))
            continue
        with tempfile.NamedTemporaryFile(suffix='.tar.gz') as archive:
            archive.write(result.stdout)
            archive.flush()
            destination.mkdir()
            with tarfile.open(archive.name) as tar:
                tar.extractall(destination, filter='data')
        print(f"{len(result.stdout) / 1024:8.0f} KiB  {mod['split']:7} {mod['repository']}")


if __name__ == '__main__':
    main()
