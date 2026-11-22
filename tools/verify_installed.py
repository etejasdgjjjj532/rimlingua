"""Read-only real MOD pool, independent export checks and catalog comparisons."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rimworld_translator.core import Project, export_mod, scan_mod
from rimworld_translator.extraction import content_files, resolve_load_folders
from rimworld_translator.history import snapshot
from rimworld_translator.platforms import discover_installations
from rimworld_translator.schema import TranslationSchema, schema_from_assemblies

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(source):
    result = {}
    for folder, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(folder)/d).is_symlink()]
        for name in files:
            path = Path(folder)/name
            stat = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.suffix.lower()=='.xml' and not path.is_symlink() else ''
            result[str(path.relative_to(source))] = (stat.st_size,stat.st_mtime_ns,digest)
    return result


def catalog_keys(source, game_version, active):
    keys, languages = set(), set()
    for folder in resolve_load_folders(source, game_version, active):
        base = folder/'Languages'
        if not base.is_dir():
            continue
        def record(parts, data, language):
            if 'DefInjected' in parts:
                index = parts.index('DefInjected')
                if index+2 >= len(parts):
                    return
                kind,group = 'DefInjected',parts[index+1]
            elif 'Keyed' in parts:
                kind,group = 'Keyed','Keyed'
            else:
                return
            try:
                root = ET.fromstring(data)
                if root.tag != 'LanguageData':
                    return
                languages.add(language)
                for child in root:
                    if len(child) and all(e.tag=='li' for e in child):
                        keys.update(f'{kind}:{group}:{child.tag}.{i}' for i,_ in enumerate(child))
                    elif child.text:
                        keys.add(f'{kind}:{group}:{child.tag}')
            except ET.ParseError:
                pass
        for file in base.rglob('*.xml'):
            if not file.is_symlink():
                relative = file.relative_to(base)
                if relative.parts[0]!='English':
                    record(relative.parts,file.read_bytes(),relative.parts[0])
        for archive in base.glob('*.tar'):
            if archive.stem=='English' or archive.is_symlink():
                continue
            with tarfile.open(archive) as package:
                for member in package:
                    if member.isfile() and member.name.endswith('.xml') and member.size < 8*1024*1024:
                        record(Path(member.name).parts,package.extractfile(member).read(),archive.stem)
    return keys,sorted(languages)


def independently_validate_export(output):
    """Check exported files without calling the extractor or its validators."""
    about = ET.parse(output/'About/About.xml').getroot()
    assert about.tag=='ModMetaData' and about.findtext('packageId')
    seen,total = set(),0
    for file in (output/'Languages').rglob('*.xml'):
        parts = file.relative_to(output/'Languages').parts
        if parts[1]=='DefInjected':
            assert len(parts)==4, f'Game loader requires a Def type subfolder: {file}'
            group = parts[2]
        else:
            assert parts[1]=='Keyed'
            group = 'Keyed'
        root = ET.parse(file).getroot()
        assert root.tag=='LanguageData'
        for child in root:
            assert not len(child) and child.text
            ident = (parts[0],parts[1],group,child.tag)
            assert ident not in seen, f'Duplicate exported key {ident}'
            seen.add(ident)
            total += 1
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=Path)
    parser.add_argument('--minimum',type=int,default=12)
    parser.add_argument('--report',type=Path,default=ROOT/'artifacts/installed-verification.json')
    args = parser.parse_args(argv)
    installations = discover_installations(custom_paths=[args.game] if args.game else [])
    if not installations:
        raise SystemExit('No installed RimWorld input found; use --game PATH')
    game = installations[0]
    workshop = game.workshop
    sources = sorted([p for p in workshop.iterdir() if p.is_dir() and not p.is_symlink() and (p/'About/About.xml').is_file()],key=lambda p:p.name) if workshop and workshop.is_dir() else []
    sources += [game.root/'Data/Core']
    active = set()
    for source in [*sources,*[p for p in (game.root/'Data').iterdir() if p.is_dir()]]:
        try:
            active.add((ET.parse(source/'About/About.xml').getroot().findtext('packageId') or '').casefold())
        except (OSError,ET.ParseError):
            pass
    managed = next((p for p in game.root.glob('*_Data/Managed/Assembly-CSharp.dll')),None)
    metadata_start = time.perf_counter()
    base_schema = schema_from_assemblies([managed] if managed else [],ROOT/'artifacts/schema-index')
    metadata_seconds = time.perf_counter()-metadata_start
    all_results = []
    with tempfile.TemporaryDirectory(prefix='rimworld-real-inputs-') as temp:
        for number,source in enumerate(sources):
            print(f'[{number+1}/{len(sources)}] {source.name}',file=sys.stderr,flush=True)
            before = fingerprint(source)
            extra_assemblies = content_files(resolve_load_folders(source,game.version,active),'Assemblies','.dll')
            local_schema = schema_from_assemblies(extra_assemblies,ROOT/'artifacts/schema-index')
            schema = TranslationSchema({**base_schema.types,**local_schema.types},[*base_schema.assemblies,*local_schema.assemblies],local_schema.warnings)
            scan_args = dict(game_version=game.version, active_mods=active, cache_path=ROOT/'artifacts/xml-index.sqlite',schema=schema,context_sources=[game.root/'Data/Core'] if source.name!='Core' else [])
            cold = scan_mod(source,**scan_args)
            warm = scan_mod(source,**scan_args)
            assert [(e.id,e.english,e.blocked) for e in cold.entries]==[(e.id,e.english,e.blocked) for e in warm.entries]
            assert warm.stats['parsed_files']==0,'Unchanged XML was reparsed'
            project = Project.create(source,cold)
            workspace = Path(temp)/str(number)
            export_mod(project,workspace/'mod')
            candidate = next((e for e in project.entries if not e.blocked and '{' not in e.english and '<' not in e.english),None)
            if candidate:
                project.set_translation(candidate.id,'SOL_REAL_INPUT_TEST')
            project.save(workspace/'project.json')
            export_mod(project,workspace/'mod')
            exported = independently_validate_export(workspace/'mod')
            assert exported==int(candidate is not None)
            assert snapshot(workspace/'project.json','Verify real MOD without source changes')
            assert not snapshot(workspace/'project.json')
            project.rescan(warm)
            if candidate:
                assert project.get_translation(candidate.id)=='SOL_REAL_INPUT_TEST'
            assert fingerprint(source)==before,'Installed source was modified'
            catalog,languages = catalog_keys(source,game.version,active)
            candidates = {e.id for e in cold.entries}
            match = catalog & candidates
            all_results.append({'sample':source.name,'name':cold.name,'result':'pass','source_unchanged':True,'entries':len(cold.entries),'keyed':sum(e.kind=='Keyed' for e in cold.entries),'blocked_duplicates':sum(e.blocked for e in cold.entries),'warnings':cold.warning_count,'exported':exported,'independent_export_validation':True,'stats':cold.stats,'warm_stats':warm.stats,'existing_catalog':{'keys':len(catalog),'matched_exact':len(match),'exact_coverage':round(len(match)/len(catalog),4) if catalog else None,'languages':languages,'unmatched_examples':sorted(catalog-candidates)[:15]},'confidence':{c:sum(e.confidence==c for e in cold.entries) for c in ('schema','catalog','heuristic')},'warning_examples':cold.warnings[:12],'game_ui_verified':False})
    report = {'schema':2,'game':str(game.root),'game_version':game.version,'metadata_seconds':round(metadata_seconds,4),'metadata_types':len(base_schema.types),'samples':all_results,'summary':{'passed':len(all_results),'failed':0,'minimum_pool_met':len(all_results)-1>=args.minimum,'source_integrity':True,'game_ui_verified':False},'limitations':['Catalog comparison is exact-path overlap, not total engine-generated field coverage. Handles, generated Defs and custom runtime behavior may differ.','Automated export/schema tests do not prove actual game UI rendering.']}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary']))
    return 0 if report['summary']['minimum_pool_met'] else 2


if __name__=='__main__':
    raise SystemExit(main())
