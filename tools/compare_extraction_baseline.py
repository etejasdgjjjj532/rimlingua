"""Compare this repository's legacy extractor with measured current real inputs.

Only the repository's own baseline Python scanner is executed. Game/MOD DLLs
are inspected as metadata, and all installed input is read only.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from rimworld_translator.core import scan_mod
    from rimworld_translator.extraction import content_files,resolve_load_folders
    from rimworld_translator.platforms import discover_installations
    from rimworld_translator.schema import TranslationSchema,schema_from_assemblies
    from tools.verify_installed import catalog_keys,fingerprint
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='dada781')
    parser.add_argument('--report',type=Path,default=ROOT/'artifacts/extraction-comparison.json')
    args = parser.parse_args()
    baseline_commit = subprocess.check_output(['git','-C',str(ROOT),'rev-parse',args.baseline],text=True).strip()
    code = subprocess.check_output(['git','-C',str(ROOT),'show',f'{baseline_commit}:rimworld_translator/core.py'],text=True)
    legacy = types.ModuleType('rimworld_translator._sol_baseline_core')
    sys.modules[legacy.__name__] = legacy
    exec(compile(code,f'<repository baseline {baseline_commit}>','exec'),legacy.__dict__)
    game = discover_installations()[0]
    measured = json.loads((ROOT/'artifacts/installed-verification-final.json').read_text())
    active = set(measured['samples'][0]['stats']['active_mods'])
    managed = next(game.root.glob('*_Data/Managed/Assembly-CSharp.dll'))
    base_schema = schema_from_assemblies([managed],ROOT/'artifacts/schema-index')
    sources = [game.workshop/ident for ident in ('1909914131','3550544871','3659157288','3669656495','3687005016','3714807736')]
    sources.append(game.root/'Data/Core')
    rows = []
    for source in sources:
        before = fingerprint(source)
        old = legacy.scan_mod(source)
        assemblies = content_files(resolve_load_folders(source,game.version,active),'Assemblies','.dll')
        extra = schema_from_assemblies(assemblies,ROOT/'artifacts/schema-index')
        schema = TranslationSchema({**base_schema.types,**extra.types},[*base_schema.assemblies,*extra.assemblies],extra.warnings)
        current = scan_mod(source,game_version=game.version,active_mods=active,schema=schema,
                           cache_path=ROOT/'artifacts/xml-index.sqlite',context_sources=[game.root/'Data/Core'] if source.name!='Core' else [])
        catalog,languages = catalog_keys(source,game.version,active)
        def counts(scan):
            ids = {entry.id for entry in scan.entries}
            usable = {entry.id for entry in scan.entries if not entry.blocked and not entry.stale}
            return {'entries':len(scan.entries),'definjected':sum(entry.kind=='DefInjected' for entry in scan.entries),
                    'keyed':sum(entry.kind=='Keyed' for entry in scan.entries),
                    'blocked_duplicates':sum(entry.blocked for entry in scan.entries),
                    'catalog_exact_matches':len(ids&catalog),'catalog_usable_matches':len(usable&catalog),
                    'catalog_exact_coverage':round(len(ids&catalog)/len(catalog),4) if catalog else None}
        unchanged = fingerprint(source)==before
        assert unchanged
        row = {'sample':source.name,'name':current.name,'existing_catalog_keys':len(catalog),
               'catalog_languages':languages,'baseline':counts(old),'current':counts(current),'source_unchanged':unchanged}
        rows.append(row)
        print(source.name,row['baseline']['definjected'],row['current']['definjected'],flush=True)
    report = {'baseline_commit':baseline_commit,'current_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
              'game_version':game.version,'samples':rows,'source_integrity':True,
              'limitations':['Candidate counts and exact static catalog keys do not prove every candidate is injectable.',
                             'Catalog unions include legacy/generated keys and multiple translations; not a 100% completeness estimate.',
                             'Six real loaded MOD label values were separately verified in the isolated diagnostic game UI.']}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
