"""Resumable, read-only audit of real MODs using the editor's scan_mod pipeline.

The independent evidence readers do not replace scan_mod. They attribute unmatched
catalog keys and raw XML fields conservatively; catalog overlap is never recall.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import logging
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sys
import tarfile
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rimworld_translator.core import FIELDS, KEY, atomic_write, safe_xml, scan_mod
from rimworld_translator.extraction import content_files, resolve_load_folders
from rimworld_translator.platforms import discover_installations
from rimworld_translator.schema import TranslationSchema, normalized_handle, schema_from_assemblies

AUDIT_SCHEMA = 2
LIMITATIONS = [
    'Catalog exact-key overlap measures corroboration only, never extractor recall.',
    'Active MOD scenario is all manifest packages plus installed DLC; it is not the user installed load profile.',
    'Independent raw XML evidence covers selected concrete Defs, inheritance, schema fields and English Keyed. Custom patch semantics, generated Defs, constructor defaults and runtime text need an isolated game run.',
    'CLR metadata and #US heaps are decoded as data only. No MOD assembly or downloaded program is executed.',
    'DLL natural-language literals and shipped C# .Translate call literals are possible candidates; runtime UI visibility and text/translation intent are not proven.',
    'This audit requests unlimited extractor diagnostics. warning_count includes repeat events; diagnostics contains every distinct message and duplicate event count is separate.',
    'Version branches outside the selected installed-game scenario are inventoried rather than claimed as extracted.',
    'Source-role exclusions apply to explicit tests/CookieCutter/templates/development projects; source filenames and inactive version directories alone never prove non-runtime status.',
    'correct_nontranslatable also covers inactive branches and external MOD/game fields outside this MOD extraction scope; it does not imply the displayed text itself cannot be translated.',
]


def json_write(path, value):
    atomic_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def tree_fingerprint(source):
    """SHA256 every regular file, and record symlink targets without following them."""
    source = Path(source)
    records, errors = [], []
    if not source.is_dir() or source.is_symlink():
        errors.append({'path':str(source),'error':'Missing directory or symbolic-link root'})
    for directory, dirs, names in os.walk(source, followlinks=False):
        dirs.sort()
        names.sort()
        for name in [*dirs, *names]:
            path = Path(directory)/name
            if path.is_symlink():
                records.append({'path':path.relative_to(source).as_posix(),'kind':'symlink','target':os.readlink(path)})
        dirs[:] = [name for name in dirs if not (Path(directory)/name).is_symlink()]
        for name in names:
            path = Path(directory)/name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
                if not path.is_file():
                    records.append({'path':path.relative_to(source).as_posix(), 'kind':'special'})
                    continue
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024), b''):
                        sha.update(chunk)
                records.append({'path':path.relative_to(source).as_posix(), 'kind':'file','size':stat.st_size,'sha256':sha.hexdigest()})
            except OSError as exc:
                errors.append({'path':str(path),'error':str(exc)})
    return {'algorithm':'SHA256-all-regular-files-and-symlink-targets','digest':digest_json(records),
            'files':records,'errors':errors,'file_count':len(records),'bytes':sum(r.get('size',0) for r in records)}


def code_fingerprint():
    paths = [Path(__file__), *sorted((ROOT/'rimworld_translator').glob('*.py'))]
    versions = {}
    for name in ('dnfile','lxml'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'unavailable'
    records = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {'digest':digest_json([records,versions,sys.version]),'files':records,'dependencies':versions,'python':sys.version}


def condition_state(attrs, active):
    """Independent conservative XML conditional check, without extractor callbacks."""
    for key, value in attrs.items():
        key = key.casefold()
        if key not in {'ifmodactive','ifmodactiveall','ifmodactiveany','ifmodnotactive','ifmodnotactiveall','mayrequire','mayrequireanyof'}:
            if key.startswith('ifmod'):
                return False, 'unknown XML condition'
            continue
        if active is None:
            return False, 'active MOD context unavailable'
        packages = [p.strip().casefold() for p in re.split('[,;]',value) if p.strip()]
        present = [p in active for p in packages]
        enabled = any(present) if key in {'ifmodactive','ifmodactiveany','ifmodnotactive','mayrequireanyof'} else all(present)
        if key.startswith('ifmodnot'):
            enabled = not enabled
        if not enabled:
            return False, f'{key}={value} is inactive'
    return True, ''


SEMANTIC_FIELDS = {'defName', 'class', 'Class', 'texPath', 'graphicClass', 'sound', 'soundCast', 'thingClass'}
CANDIDATE_CSV_FIELDS = ['id','origin','classification','classification_reason','kind','group','key','text','source_file','selected','owner','owned','active','certain','schema_translatable','schema_type','schema_field','inheritance','patch_references','translate_call_corroboration','heap_offset','extraction_blocked','emitted_id_unblocked','semantic_exclusion','semantic_evidence','source_role','source_role_reason','compilation_evidence','patch_operations','patch_xpaths','patch_value_xml','patch_value_ordinal','compiled_runtime_assembly_present']


def diagnostic_counts_from_scan(scan, diagnostic_limit=None):
    """Warning event units differ from retained distinct diagnostic units."""
    if diagnostic_limit is not None:
        raise ValueError('Exact omitted-distinct/repeated counts require unlimited diagnostics')
    distinct=len(scan.diagnostics)
    return {'warning_events':scan.warning_count,'distinct_warning_diagnostics':distinct,
            'repeated_warning_events':max(0,scan.warning_count-distinct),'omitted_distinct_diagnostics':0,
            'diagnostic_limit':None}


def derive_integrity(report, setup=None):
    setup=setup or {}
    values={'mod_source_integrity':bool(report.get('source_unchanged')),
            'installed_original_integrity':report.get('installed_original_integrity',{}).get('unchanged',True),
            'repository_integrity':report.get('repository_integrity',{}).get('unchanged',True),
            'game_context_integrity':setup.get('game_context_integrity'),
            'game_assembly_integrity':setup.get('game_assembly_integrity')}
    values['all_integrity']=all(v is True for v in values.values()) if all(v is not None for v in values.values()) else None
    return values


@contextmanager
def capture_dnfile_warnings(path, diagnostics):
    """Capture parser logs as evidence while preserving ordinary stderr handlers."""
    class Capture(logging.Handler):
        def emit(self, record):
            diagnostics.append({'code':'dll-metadata-log','source_file':str(path),'level':record.levelname,
                                'logger':record.name,'message':record.getMessage()})
    logger=logging.getLogger('dnfile')
    handler=Capture(level=logging.WARNING)
    logger.addHandler(handler)
    # Existing configured handlers still receive events. With only our handler,
    # preserve logging's normal lastResort stderr behavior explicitly.
    stderr=None
    if not any(item is not handler for item in logger.handlers) and not logging.getLogger().handlers:
        stderr=logging.StreamHandler()
        stderr.setLevel(logging.WARNING)
        logger.addHandler(stderr)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        if stderr is not None:
            logger.removeHandler(stderr)


def csharp_source_role(path, repository):
    """Conservative source provenance; never infer runtime inclusion from .cs alone."""
    path,repository=Path(path),Path(repository)
    relative=path.relative_to(repository) if path.is_relative_to(repository) else path
    parts=[part.casefold() for part in relative.parts[:-1]]
    role='unverified_source'
    reason='Shipped C# source; compilation/runtime inclusion has not been established'
    if any(p in {'tests','test','unittests','unittest','testprojects','testproject'} or p.endswith('.tests') for p in parts):
        role,reason='test','Source is in an explicit test-project directory'
    elif any(p in {'cookiecutter','templates'} for p in parts):
        role,reason='template','Source is in an explicit template/example directory'
    elif any(p in {'benchmarks','benchmark','devtools','developmenttools'} for p in parts):
        role,reason='development','Source is in an explicit development/benchmark directory'
    evidence=[]
    current=path.parent
    while current.is_relative_to(repository):
        for project in sorted(current.glob('*.csproj')):
            try:
                tree=safe_xml(project)
                nodes=list(tree.iter())
                is_test=any(n.tag.rsplit('}',1)[-1]=='IsTestProject' and (n.text or '').strip().casefold()=='true' for n in nodes)
                is_test=is_test or any(n.tag.rsplit('}',1)[-1]=='PackageReference' and n.get('Include','').casefold() in {'microsoft.net.test.sdk','xunit','nunit','mstest.testframework'} for n in nodes)
                relative_project=path.relative_to(project.parent).as_posix()
                imports=[]
                for node in nodes:
                    if node.tag.rsplit('}',1)[-1]=='Compile':
                        imports.append(dict(node.attrib))
                import fnmatch
                included=any(fnmatch.fnmatch(relative_project,(n.get('Include') or '').replace('\\','/')) for n in imports if n.get('Include'))
                removed=any(fnmatch.fnmatch(relative_project,(n.get('Remove') or '').replace('\\','/')) for n in imports if n.get('Remove'))
                evidence.append({'project':str(project),'is_test_project':is_test,'explicit_compile_include':included,'explicit_compile_remove':removed,'compile_items':imports})
                if is_test:
                    role,reason='test','Containing csproj explicitly declares a test framework/project'
                elif removed:
                    role,reason='development','Containing csproj explicitly removes this source file from compilation'
                elif included and role=='unverified_source':
                    role,reason='runtime_source','Containing non-test csproj explicitly includes this source; built game execution remains unverified'
            except (OSError,ValueError,ET.ParseError) as exc:
                evidence.append({'project':str(project),'error':str(exc)})
        if current==repository:
            break
        current=current.parent
    return {'source_role':role,'source_role_reason':reason,'compilation_evidence':evidence}


_ASSET_SOURCE_CACHE={}
def asset_reference_evidence(item, mod=None):
    """Record texture assets and source ContentFinder use for reserved fields."""
    key=item.get('key','')
    if key.rsplit('.',1)[-1] not in SEMANTIC_FIELDS or item.get('origin') not in {'raw_def','raw_patch','catalog'}:
        return None
    if item.get('origin')=='catalog' and item.get('kind')!='DefInjected':
        return None
    mod=mod or {}
    source=Path(mod.get('source_path') or item.get('owner_path') or '.')
    repo=Path(mod.get('repository_root') or source)
    evidence={'field':key.rsplit('.',1)[-1],'rule':'Reserved asset/reference/identifier field intentionally excluded by the editor',
              'asset_files':[],'content_lookup_source':[]}
    if evidence['field']=='texPath':
        text=item.get('text','').strip().replace('\\','/')
        if text and not Path(text).is_absolute() and '..' not in Path(text).parts:
            roots=[source,*[p for p in source.iterdir() if p.is_dir() and (p.name=='Common' or re.fullmatch(r'\d+(?:\.\d+)+',p.name))]] if source.is_dir() else []
            for root in roots:
                for suffix in ('.png','.jpg','.jpeg','.dds','.tga'):
                    path=root/'Textures'/(text+suffix)
                    if path.is_file() and not path.is_symlink():
                        evidence['asset_files'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        typ=item.get('schema_type',item.get('group','')).rsplit('.',1)[-1]
        cache_key=(str(repo),typ)
        if cache_key not in _ASSET_SOURCE_CACHE:
            refs=[]
            if repo.is_dir() and typ:
                for path in repo.rglob(typ+'.cs'):
                    if path.is_symlink():
                        continue
                    try:
                        for line,text in enumerate(path.read_text(encoding='utf-8-sig',errors='replace').splitlines(),1):
                            if 'ContentFinder' in text and re.search(r'\btexPath\b',text):
                                refs.append({'path':str(path),'line':line,'code':text.strip(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                    except OSError:
                        continue
            _ASSET_SOURCE_CACHE[cache_key]=refs
        evidence['content_lookup_source']=_ASSET_SOURCE_CACHE[cache_key]
    return evidence



def classify_candidate(item, extracted, raw_by_id, blocked_ids=()):
    """Require active owned corroboration before labeling a confirmed miss."""
    result = dict(item)
    ident = item.get('id','')
    result['extraction_blocked'] = ident in blocked_ids
    result.pop('usable_extracted_match',None)
    result['emitted_id_unblocked'] = bool(ident and ident in extracted and ident not in blocked_ids)
    semantic=asset_reference_evidence(item)
    if semantic:
        result['semantic_exclusion']='asset_or_identifier_field'
        result['semantic_evidence']=item.get('semantic_evidence') or semantic
    if result.get('semantic_exclusion'):
        classification, reason = 'correct_nontranslatable', 'Reserved asset/reference/identifier field; CLR string storage does not make this display text'
    elif item.get('source_role') in {'test','template','development'}:
        classification, reason = 'correct_nontranslatable', 'Source belongs to a test/template/development project outside runtime MOD translation scope'
    elif item.get('selected') is False or item.get('active') is False:
        classification, reason = 'correct_nontranslatable', 'Inactive version branch, overridden file or XML condition in this scenario'
    elif item.get('owner') in {'external_mod','game_context'} or item.get('owned') is False:
        classification, reason = 'correct_nontranslatable', 'Catalog targets another MOD/game Def; not an owned active field'
    elif item.get('forbidden'):
        classification, reason = 'correct_nontranslatable', 'CLR field is NoTranslate/Unsaved, numeric, a Def reference or non-string data'
    elif ident and ident in extracted:
        classification, reason = 'matched', ('Extractor emitted identity but blocked its conflicting duplicate; not usable coverage' if ident in blocked_ids else 'Extractor emitted the exact candidate identity')
    elif item.get('origin') == 'english_keyed' and item.get('certain'):
        classification, reason = 'confirmed_miss', 'Selected valid scalar English Keyed source exists but scan_mod did not emit it'
    elif item.get('origin') == 'raw_def' and item.get('schema_translatable') and item.get('certain') and item.get('owned'):
        classification, reason = 'confirmed_miss', 'Selected owned concrete Def field is translatable in installed CLR schema'
    else:
        corroboration = [raw for raw in raw_by_id.get(ident,[]) if raw.get('selected') and raw.get('active',True) and raw.get('owned') and raw.get('schema_translatable') and raw.get('certain') and not raw.get('forbidden')]
        if corroboration:
            classification, reason = 'confirmed_miss', 'Unmatched catalog key corroborated by an owned active CLR translatable field'
            result['raw_corroboration'] = corroboration
        else:
            classification, reason = 'possible_miss', 'Source ownership, engine key/path or runtime translation intent needs manual/isolated-game verification'
    result.update(classification=classification, classification_reason=reason)
    return result


def xml_read(path, diagnostics):
    try:
        return safe_xml(path)
    except (OSError, ValueError, ET.ParseError) as exc:
        diagnostics.append({'code':'independent-xml-parse','source_file':str(path),'error':str(exc)})
        return None


def raw_def_evidence(source, folders, schema, active, contexts):
    """Independent parent overlay and schema traversal, preserving field provenance.

    Scalar/list paths are reconstructed separately from scan_mod. Ambiguous list
    merges/handles or patch effects are explicitly downgraded, never confirmed.
    """
    source=Path(source)
    diagnostics, definitions, parents = [], [], defaultdict(list)
    for owner, selected in [(Path(c),resolve_load_folders(Path(c), '1.6',active)) if not isinstance(c,tuple) else c for c in contexts]+[(source,folders)]:
        for path in content_files(selected,'Defs'):
            root=xml_read(path,diagnostics)
            if root is None:
                continue
            if root.tag!='Defs':
                diagnostics.append({'code':'independent-xml-root','source_file':str(path),'root':root.tag,'expected':'Defs'})
                continue
            for node in root:
                item={'node':node,'file':str(path),'owned':owner==source,'owner_path':str(owner)}
                definitions.append(item)
                if node.get('Name'):
                    parents[node.get('Name')].append(item)
    patches = []
    for path in content_files(folders,'Patches'):
        root=xml_read(path,diagnostics)
        if root is not None:
            patches.append({'source_file':str(path),'operations':[n.attrib.get('Class','') for n in root.iter() if 'Class' in n.attrib],
                            'xpaths':[n.text for n in root.iter('xpath') if n.text],
                            'text':ET.tostring(root,encoding='unicode'),
                            'values':[{'tag':leaf.tag,'text':leaf.text,'xml':ET.tostring(value,encoding='unicode')} for value in root.iter('value') for leaf in value.iter() if not len(leaf) and leaf.text and leaf.text.strip()]})
    candidates, index, abstracts = [], {}, 0
    def effective(item, trail=()):
        node=item['node']
        values={child.tag:(child,item['file'],[]) for child in node if child.tag!='li'}
        parent=node.get('ParentName')
        certain=True
        if parent and node.get('Inherit',node.get('inherit','')).casefold()!='false':
            found=parents.get(parent,[])
            if len(found)!=1 or parent in trail:
                diagnostics.append({'code':'independent-inheritance','source_file':item['file'],'parent':parent,'matches':len(found),'cycle':parent in trail})
                certain=False
            else:
                inherited, certain=effective(found[0],(*trail,parent))
                inherited={tag:(child,path,[parent,*chain]) for tag,(child,path,chain) in inherited.items()}
                inherited.update(values)
                values=inherited
        return values,certain
    def walk(node, typ, prefix, def_item, def_name, group, inherited, certain, parent_active, parent_forbidden=False):
        enabled,condition=condition_state(node.attrib,active)
        enabled=enabled and parent_active
        fields=schema.fields_for(typ)
        spec=fields.get(node.tag)
        # The caller passes the containing object's type for each member node.
        forbidden=parent_forbidden or bool(spec and (spec.forbidden or schema.is_def(spec.type_name)))
        target=node.get('Class') or (spec.type_name if spec else '')
        if len(node):
            if all(child.tag=='li' for child in node):
                loaded=[child for child in node if condition_state(child.attrib,active)[0]]
                handles=[]
                for child in loaded:
                    item_type=child.get('Class') or target
                    handle=''
                    for tag,field in sorted(schema.fields_for(item_type).items(),key=lambda pair:pair[1].handle_priority,reverse=True):
                        if 'TranslationHandleAttribute' in field.attributes and child.findtext(tag):
                            handle=normalized_handle(child.findtext(tag))
                            break
                    handles.append(handle)
                counts=Counter(handles)
                used=Counter()
                for offset,child in enumerate(loaded):
                    handle=handles[offset]
                    if handle and counts[handle]>1:
                        ordinal=used[handle]; used[handle]+=1
                        handle+='-'+str(ordinal)
                    segment=handle or str(offset)
                    if len(child):
                        for member in child:
                            walk(member,child.get('Class') or target,prefix+'.'+segment+'.'+member.tag,def_item,def_name,group,inherited,False,enabled,forbidden)
                    elif child.text and child.text.strip():
                        emit(child,def_name+'.'+prefix+'.'+segment,group,def_item,inherited,False,enabled,forbidden,bool(spec and spec.translatable and spec.is_list),typ,spec,condition)
            else:
                for child in node:
                    walk(child,target,prefix+'.'+child.tag,def_item,def_name,group,inherited,False,enabled,forbidden)
        elif node.text and node.text.strip():
            textual=bool(spec and spec.translatable) or node.tag in FIELDS
            if textual or (spec and (spec.forbidden or schema.is_def(spec.type_name))):
                emit(node,def_name+'.'+prefix,group,def_item,inherited,certain,enabled,forbidden,bool(spec and spec.translatable and not spec.is_list),typ,spec,condition)
    def emit(node,key,group,item,inherited,certain,enabled,forbidden,translatable,typ,spec,condition):
        text=node.text or ''
        numeric=bool(re.fullmatch(r'[-+\d.\s]+',text))
        ident=f'DefInjected:{group}:{key}'
        candidate={'id':ident,'origin':'raw_def','kind':'DefInjected','group':group,'key':key,'text':text,
                   'source_file':item['file'],'def_source_file':item.get('def_file',item['file']),
                   'selected':True,'owned':item['owned'],'owner_path':item['owner_path'],'active':enabled,
                   'condition':condition,'schema_type':typ,'schema_field':asdict(spec) if spec else None,
                   'schema_translatable':translatable,'forbidden':forbidden or numeric,'certain':certain and bool(KEY.fullmatch(key)),
                   'inheritance':inherited,'patch_references':[{'source_file':p['source_file'],'operations':p['operations'],'xpaths':p['xpaths']} for p in patches if key.split('.')[0] in p['text']]}
        # Matching patch text does not prove application/order; downgrade source fields potentially changed.
        if candidate['patch_references']:
            candidate['certain']=False
        candidates.append(candidate)
    for item in definitions:
        node=item['node']
        name=(node.findtext('defName') or '').strip()
        if name:
            index[f'{node.tag}:{name}']={'owned':item['owned'],'source_file':item['file'],'abstract':node.get('Abstract','').casefold()=='true'}
        if not item['owned']:
            continue
        if node.get('Abstract','').casefold()=='true':
            abstracts+=1
            continue
        if not name:
            continue
        values,certain=effective(item)
        typ=node.get('Class') or node.tag
        def_enabled,_=condition_state(node.attrib,active)
        for tag,(child,file,chain) in values.items():
            if tag=='defName':
                continue
            field_item=dict(item,file=file,def_file=item['file'])
            # Inherited nested object/list overlays are deliberately possible-only.
            walk(child,typ,tag,field_item,name,node.tag,chain,certain,def_enabled)
    patch_candidates=[]
    for patch in patches:
        for ordinal,value in enumerate(patch['values']):
            if value['tag'] in FIELDS and value['text'] and not re.fullmatch(r'[-+\d.\s]+',value['text']):
                patch_candidates.append({'id':'','origin':'raw_patch','kind':'Patch','group':'PatchValue','key':value['tag'],
                                         'text':value['text'],'source_file':patch['source_file'],'selected':True,'certain':False,
                                         'patch_operations':patch['operations'],'patch_xpaths':patch['xpaths'],'patch_value_xml':value['xml'],
                                         'patch_value_ordinal':ordinal,'owned':True,'requires_patch_application_verification':True})
    return {'candidates':candidates,'patch_candidates':patch_candidates,'def_index':index,'diagnostics':diagnostics,'abstract_defs':abstracts,
            'patches':[{k:v for k,v in patch.items() if k!='text'} for patch in patches],
            'independent_rule':'Top-level scalar inheritance overlay is certain. Nested/list overlays and textual patch targets remain possible.'}


def catalog_evidence(source, folders, diagnostics):
    """All catalog items, including inactive/stale branches and tar members."""
    source=Path(source)
    selected_cache={}
    records=[]
    def record(data, parts, filename, selected, language):
        if 'DefInjected' in parts:
            at=parts.index('DefInjected')
            group=parts[at+1] if at+2<len(parts) else Path(parts[-1]).stem
            kind='DefInjected'
        elif 'Keyed' in parts:
            group=kind='Keyed'
        else:
            return
        try:
            normalized=data.replace(b'\x00',b'').upper()
            if b'<!DOCTYPE' in normalized or b'<!ENTITY' in normalized:
                raise ValueError('DTD/ENTITY prohibited')
            root=ET.fromstring(data)
        except (ET.ParseError,ValueError) as exc:
            diagnostics.append({'code':'independent-catalog-parse','source_file':filename,'error':str(exc)})
            return
        if root.tag!='LanguageData':
            diagnostics.append({'code':'independent-catalog-root','source_file':filename,'root':root.tag})
            return
        for child in root:
            items=list(enumerate(child)) if len(child) and all(c.tag=='li' for c in child) else [(None,child)]
            for ordinal,node in items:
                key=child.tag+(f'.{ordinal}' if ordinal is not None else '')
                ident=f'{kind}:{group}:{key}'
                text=node.text or ''
                if not text.strip():
                    continue
                english=language=='English' and kind=='Keyed'
                records.append({'id':ident,'kind':kind,'group':group,'key':key,'text':text,'language':language,
                                'source_file':filename,'selected':selected,'origin':'english_keyed' if english else 'catalog',
                                'certain':english and ordinal is None and not len(child) and bool(KEY.fullmatch(key)),
                                'nested':bool(len(child)),'branch_status':'selected' if selected else 'inactive_or_overridden'})
    for directory, dirs, names in os.walk(source,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not d.startswith('.'))
        for name in sorted(names):
            path=Path(directory)/name
            parts=path.relative_to(source).parts
            if path.is_symlink() or 'Languages' not in parts:
                continue
            at=parts.index('Languages')
            after=parts[at+1:]
            if path.suffix.lower()=='.xml' and len(after)>=3:
                language=after[0]
                if 'DefInjected' not in after and 'Keyed' not in after:
                    continue
                category='Keyed' if 'Keyed' in after else 'DefInjected'
                cache_key=(language,category)
                if cache_key not in selected_cache:
                    selected_cache[cache_key]=set(content_files(folders,f'Languages/{language}/{category}'))
                selected=path in selected_cache[cache_key]
                try:
                    if path.stat().st_size>8*1024*1024:
                        raise ValueError('Catalog XML over 8 MiB')
                    record(path.read_bytes(),after,str(path),selected,language)
                except (OSError,ValueError) as exc:
                    diagnostics.append({'code':'catalog-read','source_file':str(path),'error':str(exc)})
            elif path.suffix.lower()=='.tar' and len(after)==1:
                language=path.stem
                selected=any(path.parent==folder/'Languages' for folder in folders)
                try:
                    with tarfile.open(path) as archive:
                        for member in archive:
                            if member.isfile() and member.name.lower().endswith('.xml') and member.size<=8*1024*1024:
                                stream=archive.extractfile(member)
                                if stream is not None:
                                    record(stream.read(),Path(member.name).parts,str(path)+'!'+member.name,selected,language)
                except (OSError,tarfile.TarError) as exc:
                    diagnostics.append({'code':'catalog-archive','source_file':str(path),'error':str(exc)})
    return records


def dll_evidence(paths, source, catalogs, repository_root=None):
    """Read #US literals and corroborate .Translate literals in shipped C# source."""
    import dnfile
    records, diagnostics=[],[]
    translated={}
    for path in Path(repository_root or source).rglob('*.cs'):
        if path.is_symlink() or path.stat().st_size>8*1024*1024:
            continue
        try:
            text=path.read_text(encoding='utf-8-sig',errors='replace')
            for match in re.finditer(r'"((?:\\.|[^"\\])*)"\s*\.\s*Translate\s*\(',text):
                literal=match.group(1)
                translated.setdefault(literal,[]).append({'source_file':str(path),'line':text.count('\n',0,match.start())+1,'code':match.group(0)})
        except OSError as exc:
            diagnostics.append({'code':'csharp-read','source_file':str(path),'error':str(exc)})
    catalog_ids={c['key']:c['id'] for c in catalogs if c['kind']=='Keyed' and c['language']=='English' and c['selected']}
    for literal, calls in translated.items():
        by_file=defaultdict(list)
        for call in calls:
            by_file[call['source_file']].append(call)
        for source_file,file_calls in by_file.items():
            records.append({'id':catalog_ids.get(literal,''),'origin':'csharp_translate','kind':'CSharp','group':'Translate',
                            'key':literal,'text':literal,'source_file':source_file,'selected':True,
                            'translate_call_corroboration':file_calls,**csharp_source_role(Path(source_file),Path(repository_root or source)),
                            'certain':False,'runtime_visibility_verified':False,'compiled_runtime_assembly_present':bool(paths)})
    for path in paths:
        with capture_dnfile_warnings(path,diagnostics):
            pe=None
            try:
                pe=dnfile.dnPE(str(path),clr_lazy_load=True)
                stream=pe.net.user_strings if pe.net else None
                if stream is None:
                    diagnostics.append({'code':'dll-us-absent','source_file':str(path)})
                    continue
                data=stream.__data__
                offset=1
                while offset<len(data):
                    item=stream.get(offset,errors='replace')
                    if item is None or not item.raw_size:
                        break
                    literal=item.value or ''
                    literal_offset=offset
                    offset+=item.raw_size
                    natural=len(literal.strip())>=4 and bool(re.search(r'[A-Za-z]{3}',literal)) and bool(re.search(r'\s',literal)) and not re.fullmatch(r'[\w.\\/:+`<>\[\], -]+\.(?:png|dll|xml|cs|ttf|ogg)',literal)
                    if natural or literal in translated or literal in catalog_ids:
                        records.append({'id':catalog_ids.get(literal,''),'origin':'dll_us','kind':'DLL','group':'#US','key':literal,
                                        'text':literal,'source_file':str(path),'selected':True,'heap_offset':literal_offset,
                                        'translate_call_corroboration':translated.get(literal,[]),'natural_language_heuristic':natural,
                                        'certain':False,'runtime_visibility_verified':False})
            except Exception as exc:
                diagnostics.append({'code':'dll-us-read','source_file':str(path),'error':str(exc)})
            finally:
                if pe is not None:
                    pe.close()
    return {'candidates':records,'diagnostics':diagnostics,'translate_literals':translated}


def csv_write(path, rows, fields):
    import csv
    import io
    output=io.StringIO(newline='')
    writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,tuple)) else value for key,value in row.items()})
    atomic_write(Path(path),output.getvalue().encode('utf-8-sig'))


def metadata(source):
    about=source/'About/About.xml'
    root=safe_xml(about)
    return {'name':root.findtext('name') or source.name,'package_id':(root.findtext('packageId') or '').strip().casefold(),
            'supported_versions':[(n.text or '').strip() for n in root.findall('supportedVersions/li')],
            'dependencies':[(n.findtext('packageId') or '').strip().casefold() for n in root.findall('modDependencies/li')],
            'load_after':[(n.text or '').strip().casefold() for n in root.findall('loadAfter/li')]}


def branch_inventory(source, folders):
    selected=set()
    for category in ('Defs','Patches','Languages/English/Keyed','Languages/English/DefInjected'):
        selected.update(content_files(folders,category))
    files=[]
    for directory, dirs, names in os.walk(source,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not d.startswith('.'))
        for name in sorted(names):
            path=Path(directory)/name
            if path.suffix.lower()!='.xml' or path.is_symlink():
                continue
            relative=path.relative_to(source).as_posix()
            if any(category in path.relative_to(source).parts for category in ('Defs','Patches','Languages')):
                files.append({'path':relative,'selected_for_pipeline':path in selected})
    return {'selected_folders':[str(p.relative_to(source)) for p in folders],
            'version_directories':sorted(p.name for p in source.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)+',p.name)),
            'files':files,'selected_xml_count':sum(f['selected_for_pipeline'] for f in files),
            'unselected_xml_count':sum(not f['selected_for_pipeline'] for f in files)}


def audit_one(mod, destination, version, active, base_schema, contexts, dependency_dlls, schema_cache, identity, before):
    source=Path(mod['source_path'])
    started=time.perf_counter()
    original=Path(mod['original_source_path']) if mod.get('original_source_path') else None
    repository=Path(mod['repository_root']) if mod.get('repository_root') else None
    original_before=tree_fingerprint(original) if original and original!=source else None
    repository_before=tree_fingerprint(repository) if repository and repository!=source else None
    result={'schema':AUDIT_SCHEMA,'mod':mod,'identity':identity,'source_before':before,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'limitations':LIMITATIONS,'game_ui_verified':False,'status':'running'}
    try:
        selection_warnings=[]
        folders=resolve_load_folders(source,version,active,lambda *args:selection_warnings.append(args))
        local_dlls=content_files(folders,'Assemblies','.dll')
        local_schema=schema_from_assemblies([*dependency_dlls,*local_dlls],schema_cache)
        schema=TranslationSchema({**base_schema.types,**local_schema.types},[*base_schema.assemblies,*local_schema.assemblies],[*base_schema.warnings,*local_schema.warnings])
        result['metadata']={'schema_types':len(schema.types),'assemblies':schema.assemblies,'warnings':schema.warnings,
                            'local_dlls':[str(p) for p in local_dlls],'dependency_dlls':[str(p) for p in dependency_dlls],
                            'schema_type_collisions_with_game':sorted(set(base_schema.types)&set(local_schema.types)),
                            'active_runtime_assembly_present':bool(local_dlls),
                            'missing_required_dependency_packages':[p for p in mod.get('dependencies',[]) if p not in active]}
        cache=destination/'xml-cache.sqlite'
        # Clear only this audit's disposable parser cache; sources are never modified.
        if cache.exists():
            cache.unlink()
        import rimworld_translator.extraction as extraction
        extraction._TREE_CACHE.clear()
        extraction._TREE_CACHE_BYTES=0
        scan_args=dict(game_version=version,active_mods=active,cache_path=cache,schema=schema,context_sources=contexts,diagnostic_limit=None)
        cold_start=time.perf_counter()
        cold=scan_mod(source,**scan_args)
        cold_seconds=time.perf_counter()-cold_start
        warm_start=time.perf_counter()
        warm=scan_mod(source,**scan_args)
        warm_seconds=time.perf_counter()-warm_start
        entries=[asdict(e) for e in cold.entries]
        cold_identity=[(e.id,e.english,e.blocked,e.confidence) for e in cold.entries]
        warm_identity=[(e.id,e.english,e.blocked,e.confidence) for e in warm.entries]
        result.update(name=cold.name,package_id=cold.package_id,versions=cold.versions,stats=cold.stats,warm_stats=warm.stats,
                      timings={'cold_seconds':cold_seconds,'warm_seconds':warm_seconds},warm_output_identical=cold_identity==warm_identity,
                      counts={'entries':len(entries),'def_injected':sum(e['kind']=='DefInjected' for e in entries),'keyed':sum(e['kind']=='Keyed' for e in entries),
                              'blocked_duplicates':sum(e['blocked'] for e in entries)},
                      warnings=cold.warnings,warning_count=cold.warning_count,diagnostics=cold.diagnostics,
                      **diagnostic_counts_from_scan(cold,diagnostic_limit=None),load_selection_warnings=selection_warnings)
        result['diagnostic_counts']=dict(Counter(d['code'] for d in cold.diagnostics))
        result['parse_errors']=[d for d in cold.diagnostics if d['code']=='xml']
        result['patch_diagnostics']=[d for d in cold.diagnostics if d['code'].startswith('patch-')]
        result['skip_diagnostics']=[d for d in cold.diagnostics if d['code'] in {'unnamed','list-skipped','nested-keyed','invalid-key','unknown-field','load-path','missing-folder','unknown-condition','conditional-context'}]
        result['unsupported_installed_version']=bool(cold.versions and version not in cold.versions)
        result['branches']=branch_inventory(source,folders)
        independent=raw_def_evidence(source,folders,schema,active,[(c,resolve_load_folders(c,version,active)) for c in contexts])
        catalog_diagnostics=[]
        catalogs=catalog_evidence(source,folders,catalog_diagnostics)
        raw_by_id=defaultdict(list)
        for item in independent['candidates']:
            raw_by_id[item['id']].append(item)
        extracted={e.id for e in cold.entries}
        dlls=dll_evidence(local_dlls,source,catalogs,mod.get('repository_root'))
        blocked_ids={e.id for e in cold.entries if e.blocked}
        all_candidates=[]
        for item in [*independent['candidates'],*independent['patch_candidates'],*catalogs,*dlls['candidates']]:
            if item['origin']=='catalog' and item['kind']=='DefInjected':
                def_name=item['key'].split('.')[0]
                ownership=independent['def_index'].get(f"{item['group']}:{def_name}")
                if ownership:
                    item['owner']='owned_mod' if ownership['owned'] else 'game_context'
                    item['def_corroboration']=ownership
                else:
                    item['owner']='unresolved'
            semantic=asset_reference_evidence(item,mod)
            if semantic:
                item['semantic_evidence']=semantic
            all_candidates.append(classify_candidate(item,extracted,raw_by_id,blocked_ids))
        result['candidate_counts']=dict(Counter(c['classification'] for c in all_candidates))
        result['candidate_identity_counts']={classification:len({c['id'] or (c['source_file'],c.get('origin'),c.get('key'),c.get('heap_offset'),c.get('patch_value_ordinal')) for c in all_candidates if c['classification']==classification}) for classification in result['candidate_counts']}
        result['existing_catalog']={'keys':len({c['id'] for c in catalogs if c['selected'] and c['language']!='English'}),
                                   'matched_exact':len({c['id'] for c in catalogs if c['selected'] and c['language']!='English' and c['id'] in extracted}),
                                   'matched_exact_usable':len({c['id'] for c in catalogs if c['selected'] and c['language']!='English' and c['id'] in extracted and c['id'] not in blocked_ids}),
                                   'measure':'Exact active catalog-key overlap only; blocked duplicates are excluded from usable overlap; not recall',
                                   'languages':sorted({c['language'] for c in catalogs}),
                                   'unmatched_items':[c for c in all_candidates if c['origin'] in {'catalog','english_keyed'} and c['id'] not in extracted]}
        result['independent_evidence']={key:value for key,value in independent.items() if key not in {'candidates','patch_candidates'}}
        result['independent_evidence']['catalog_diagnostics']=catalog_diagnostics
        result['dll_evidence']={key:value for key,value in dlls.items() if key!='candidates'}
        result['blocked_duplicate_entries']=[e for e in entries if e['blocked']]
        result['entries_file']='entries.json'
        result['candidates_file']='candidates.json'
        json_write(destination/'entries.json',entries)
        csv_write(destination/'entries.csv',entries,['id','kind','group','key','english','source_file','confidence','blocked','review','evidence'])
        json_write(destination/'candidates.json',all_candidates)
        csv_write(destination/'candidates.csv',all_candidates,CANDIDATE_CSV_FIELDS)
        result['zero_result_assessment']='has_translatable_entries' if entries else ('possible_runtime_or_unresolved_text' if result['candidate_counts'].get('possible_miss') or result['candidate_counts'].get('confirmed_miss') else 'correct_zero_no_selected_owned_translatable_evidence')
        result['status']='pass' if result['warm_output_identical'] else 'fail'
    except Exception as exc:
        result.update(status='exception',exception={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
    finally:
        after=tree_fingerprint(source)
        result['source_after']=after
        if original_before is not None:
            original_after=tree_fingerprint(original)
            result['installed_original_integrity']={'before':original_before,'after':original_after,
                                                   'unchanged':not original_before['errors'] and not original_after['errors'] and original_before['digest']==original_after['digest']}
        if repository_before is not None:
            repository_after=tree_fingerprint(repository)
            result['repository_integrity']={'before':repository_before,'after':repository_after,
                                           'unchanged':not repository_before['errors'] and not repository_after['errors'] and repository_before['digest']==repository_after['digest']}
        result['source_unchanged']=not before['errors'] and not after['errors'] and before['digest']==after['digest']
        if not result['source_unchanged'] or not result.get('installed_original_integrity',{}).get('unchanged',True) or not result.get('repository_integrity',{}).get('unchanged',True):
            result['status']='integrity_failure'
        result['integrity']=derive_integrity(result)
        result['total_seconds']=time.perf_counter()-started
        result['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        json_write(destination/'report.json',result)
    return result


def summarize(results, destination, manifest, setup):
    rows=[]
    for result in results:
        rows.append({'package_id':result.get('package_id',result['mod'].get('package_id','')),'name':result.get('name',result['mod'].get('name','')),
                     'status':result['status'],'source_path':result['mod']['source_path'],'category':result['mod'].get('category',[]),
                     'source_url':result['mod'].get('source_url',''),'source_sha256':result['source_before']['digest'],'source_unchanged':result['source_unchanged'],
                     **result.get('counts',{}),**{k:result.get('candidate_identity_counts',{}).get(k,0) for k in ('confirmed_miss','possible_miss','correct_nontranslatable')},
                     'warning_count':result.get('warning_count',0),'repeated_warning_events':result.get('repeated_warning_events'),
                     'distinct_warning_diagnostics':result.get('distinct_warning_diagnostics'),
                     'omitted_distinct_diagnostics':result.get('omitted_distinct_diagnostics'),
                     'integrity':derive_integrity(result,setup),'parse_errors':len(result.get('parse_errors',[])),
                     'patch_diagnostic_count':len(result.get('patch_diagnostics',[])),
                     'patch_diagnostic_codes':dict(Counter(d['code'] for d in result.get('patch_diagnostics',[]))),
                     'skip_diagnostic_count':len(result.get('skip_diagnostics',[])),'cold_seconds':result.get('timings',{}).get('cold_seconds'),
                     'warm_seconds':result.get('timings',{}).get('warm_seconds'),'unsupported_version':result.get('unsupported_installed_version'),
                     'report':str(Path(result['report_path']).relative_to(destination)) if result.get('report_path') else ''})
    summary={'distinct_real_mods':len(rows),'successfully_scanned':sum(r['status']=='pass' for r in rows),
             'exceptions':sum(r['status']=='exception' for r in rows),'failures':sum(r['status'] not in {'pass','exception'} for r in rows),
             'source_integrity':all(r['source_unchanged'] for r in rows),
             'all_integrity':all(derive_integrity(r,setup)['all_integrity'] is True for r in results),
             'confirmed_candidate_identities':sum(r['confirmed_miss'] for r in rows),
             'possible_candidate_identities':sum(r['possible_miss'] for r in rows),
             'entries':sum(r.get('entries',0) for r in rows),'minimum_100_met':len(rows)>=100}
    document={'schema':AUDIT_SCHEMA,'summary':summary,'setup':setup,'results':rows,'excluded':manifest.get('excluded',[]),
              'acquisition_attempts':manifest.get('attempts',[]),'limitations':LIMITATIONS}
    json_write(destination/'results.json',document)
    csv_write(destination/'results.csv',rows,['package_id','name','status','source_path','source_url','category','source_sha256','source_unchanged','entries','def_injected','keyed','blocked_duplicates','confirmed_miss','possible_miss','correct_nontranslatable','warning_count','repeated_warning_events','distinct_warning_diagnostics','omitted_distinct_diagnostics','integrity','parse_errors','patch_diagnostic_count','patch_diagnostic_codes','skip_diagnostic_count','cold_seconds','warm_seconds','unsupported_version','report'])
    lines=['# Real MOD extraction audit','',f"Distinct real MODs: {summary['distinct_real_mods']}; successful scans: {summary['successfully_scanned']}; exceptions: {summary['exceptions']}.",
           f"Full source SHA256 integrity unchanged: {summary['source_integrity']}. Extracted entries: {summary['entries']}.",
           f"Confirmed candidate identities: {summary['confirmed_candidate_identities']}; possible: {summary['possible_candidate_identities']}.",'',
           'Candidate counts are evidence classifications, not recall. Catalog keys may be stale or target other MODs; the complete evidence is in each per-MOD candidates.json/CSV.','',
           '## Highest-priority findings','', '| Package | Status | Entries | Confirmed | Possible | Warnings |','| --- | --- | ---: | ---: | ---: | ---: |']
    for row in sorted(rows,key=lambda r:(r['status']!='pass',r['confirmed_miss'],r['possible_miss']),reverse=True):
        lines.append(f"| {row['package_id']} | {row['status']} | {row.get('entries',0)} | {row['confirmed_miss']} | {row['possible_miss']} | {row['warning_count']} |")
    lines.extend(['','## Reproduction','', '```sh',setup['command'],'```','','## Limitations','',*['- '+lim for lim in LIMITATIONS]])
    atomic_write(destination/'report.md',('\n'.join(lines)+'\n').encode())
    return summary


def normalize_run_reports(run_directory):
    """Correct derived reporting only, preserving raw outputs and baseline identity.

    No extraction is re-run; entries/source/code evidence remain byte-for-byte
    unchanged. Baseline stderr cannot be retroactively attributed to DLLs.
    """
    from types import SimpleNamespace
    run=Path(run_directory).resolve()
    setup=json.loads((run/'setup.json').read_text())
    aggregate=json.loads((run/'results.json').read_text())
    originals={}
    def preserve(path):
        if not path.exists():
            return
        original=path.with_name(path.stem+'-original'+path.suffix)
        if not original.exists():
            atomic_write(original,path.read_bytes())
        originals[str(original.relative_to(run))]=hashlib.sha256(original.read_bytes()).hexdigest()
    for name in ('results.json','results.csv','report.md','setup.json'):
        preserve(run/name)
    aggregate=json.loads((run/'results-original.json').read_text())
    results=[]
    changed_counts=Counter()
    for report_path in sorted((run/'mods').glob('*/report.json')):
        folder=report_path.parent
        preserve(report_path)
        for name in ('candidates.json','candidates.csv'):
            preserve(folder/name)
        report=json.loads((folder/'report-original.json').read_text())
        immutable={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('entries.json','entries.csv') if (folder/name).exists()}
        entries=json.loads((folder/'entries.json').read_text()) if (folder/'entries.json').exists() else []
        extracted={entry['id'] for entry in entries}
        blocked={entry['id'] for entry in entries if entry.get('blocked')}
        source_candidates=json.loads((folder/'candidates-original.json').read_text()) if (folder/'candidates-original.json').exists() else []
        raw_by_id=defaultdict(list)
        for candidate in source_candidates:
            if candidate.get('origin')=='raw_def':
                raw_by_id[candidate.get('id','')].append(candidate)
        candidates=[]
        for candidate in source_candidates:
            item=dict(candidate)
            if item.get('origin')=='csharp_translate':
                calls=item.get('translate_call_corroboration') or [{'source_file':item['source_file']}]
                roles=[csharp_source_role(Path(call['source_file']),Path(report['mod'].get('repository_root') or report['mod']['source_path'])) for call in calls]
                item['source_role_evidence']=roles
                eligible=[role for role in roles if role['source_role'] not in {'test','template','development'}]
                if eligible:
                    item.update(eligible[0])
                elif roles:
                    item.update(roles[0])
            semantic=asset_reference_evidence(item,report['mod'])
            if semantic:
                item['semantic_evidence']=semantic
            corrected=classify_candidate(item,extracted,raw_by_id,blocked)
            if corrected['classification']!=candidate.get('classification'):
                changed_counts[candidate.get('classification','unknown')+' -> '+corrected['classification']]+=1
            candidates.append(corrected)
        if 'warning_count' in report:
            report.pop('diagnostic_omitted_events',None)
            report.update(diagnostic_counts_from_scan(SimpleNamespace(warning_count=report['warning_count'],diagnostics=report.get('diagnostics',[])),None))
        if source_candidates:
            report['candidate_counts']=dict(Counter(c['classification'] for c in candidates))
            report['candidate_identity_counts']={classification:len({c['id'] or (c['source_file'],c.get('origin'),c.get('key'),c.get('heap_offset'),c.get('patch_value_ordinal')) for c in candidates if c['classification']==classification}) for classification in report['candidate_counts']}
            if 'existing_catalog' in report:
                report['existing_catalog']['unmatched_items']=[c for c in candidates if c['origin'] in {'catalog','english_keyed'} and c['id'] not in extracted]
        report['schema']=AUDIT_SCHEMA
        report['integrity']=derive_integrity(report,setup)
        report['normalization_provenance']={'version':2,'processing_tool_code':code_fingerprint(),'operation':'Derived reporting normalization; no extraction rerun',
            'originals':{Path(key).name:value for key,value in originals.items() if str(folder.relative_to(run)) in key},
            'immutable_entry_sha256':immutable,'baseline_extraction_code_sha256':report.get('identity',{}).get('code_sha256'),
            'changes':['Correct warning event/distinct/repeat units; omitted distinct=0 for unlimited baseline diagnostics',
                       'Asset/identifier semantic exclusion overrides CLR string storage',
                       'Annotate test/template/development C# source role with path/project evidence; preserve uncertain runtime source',
                       'Rename emitted identity flag and derive full integrity from original evidence'],
            'limitations':['Baseline dnfile stderr messages were not structured per DLL; original runlog remains the evidence. No per-DLL warning mapping is invented.',
                           'Reader security guards are improved for future runs; baseline raw XML/entries were not re-extracted.']}
        report['report_path']=str(report_path)
        if source_candidates:
            json_write(folder/'candidates.json',candidates)
            csv_write(folder/'candidates.csv',candidates,CANDIDATE_CSV_FIELDS)
        json_write(report_path,report)
        for name,sha in immutable.items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=sha:
                raise RuntimeError('Normalization changed immutable extracted entries: '+str(folder/name))
        results.append(report)
    manifest={'excluded':aggregate.get('excluded',[]),'attempts':aggregate.get('acquisition_attempts',[])}
    summary=summarize(results,run,manifest,setup)
    provenance={'version':2,'operation':'Derived reporting normalization; no extraction rerun','command':f'.venv/bin/python tools/audit_mod_corpus.py --normalize-run {run}',
                'processed_reports':len(results),'original_files_sha256':originals,'classification_changes':dict(changed_counts),
                'baseline_extraction_code':setup.get('code'),'processing_tool_code':code_fingerprint(),
                'raw_summary':aggregate.get('summary'),'normalized_summary':summary,
                'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'limitation':'Historical stderr warning-to-DLL mapping was not structured; original runlog is preserved and no mappings are invented.'}
    json_write(run/'normalization-provenance.json',provenance)
    return summary



def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--normalize-run',type=Path,help='Normalize derived reports preserving original files; no extraction rerun')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/mod-100-audit')
    parser.add_argument('--run-label')
    parser.add_argument('--game',type=Path)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--only',action='append',default=[])
    parser.add_argument('--force',action='store_true',help='Preserve previous reports and re-run even with identical fingerprints')
    args=parser.parse_args(argv)
    if args.normalize_run:
        print(json.dumps(normalize_run_reports(args.normalize_run),ensure_ascii=False))
        return 0
    if not args.manifest or not args.game or not args.run_label:
        parser.error('--manifest --game --run-label are required for extraction runs')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',args.run_label) or args.run_label in {'.','..'}:
        parser.error('run-label must be a simple directory name')
    destination=args.output.resolve()/args.run_label
    destination.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.manifest.read_text())
    installations=discover_installations(custom_paths=[args.game])
    game=next((item for item in installations if item.root==args.game.resolve()),None)
    if game is None:
        raise SystemExit('Specified installed game has no Core and executable/Version.txt')
    version='.'.join(game.version.split('.')[:2])
    if not re.fullmatch(r'\d+\.\d+',version):
        raise SystemExit('Installed game version unavailable')
    code=code_fingerprint()
    selected=[]
    seen=set()
    exclusions=[]
    for mod in manifest.get('mods',[]):
        source=Path(mod['source_path']).resolve()
        try:
            meta=metadata(source)
            package=meta['package_id']
            reason=''
            if not package:
                reason='missing_package_id'
            elif package.startswith('ludeon.rimworld') or source.is_relative_to(game.root/'Data'):
                reason='game_core_or_dlc_not_real_mod'
            elif source.is_relative_to(ROOT/'tests') or mod.get('synthetic') or mod.get('fixture'):
                reason='test_fixture_not_real_mod'
            elif package in seen:
                reason='duplicate_package_id'
            if reason:
                exclusions.append({'source_path':str(source),'package_id':package,'reason':reason})
                continue
            seen.add(package)
            selected.append({**mod,**meta,'source_path':str(source)})
        except Exception as exc:
            exclusions.append({'source_path':str(source),'reason':'metadata_error','error':str(exc)})
    packages={mod['package_id']:mod for mod in selected}
    game_contexts=[]
    active=set(packages)
    for source in sorted((game.root/'Data').iterdir()):
        if source.is_dir() and (source/'About/About.xml').is_file():
            try:
                active.add(metadata(source)['package_id'])
                game_contexts.append(source)
            except (OSError,ValueError,ET.ParseError):
                continue
    # Core/DLC are context only and never enter the real MOD count.
    context_fingerprints={str(path):tree_fingerprint(path) for path in game_contexts}
    managed=next(iter(sorted(game.root.glob('*_Data/Managed/Assembly-CSharp.dll'))),None)
    if managed is None:
        raise SystemExit('Installed Assembly-CSharp.dll is required for grounded schema audit')
    managed_fingerprint=hashlib.sha256(managed.read_bytes()).hexdigest()
    schema_cache=args.output.resolve()/'metadata-cache'
    base=schema_from_assemblies([managed],schema_cache)
    if not base.types:
        raise SystemExit('Installed CLR schema could not be read: '+str(base.warnings))
    setup={'game':str(game.root),'game_version':version,'active_scenario':sorted(active),'code':code,'game_assembly_sha256':managed_fingerprint,
           'game_context_fingerprints':context_fingerprints,'command':'.venv/bin/python '+ ' '.join(sys.argv),
           'scenario':'All distinct manifest packages plus installed game DLC. No game runtime executed.'}
    json_write(destination/'setup.json',setup)
    selected=[mod for mod in selected if not args.only or mod['package_id'] in args.only or mod.get('workshop_id') in args.only]
    if args.limit is not None:
        selected=selected[:max(0,args.limit)]
    manifest={**manifest,'excluded':[*manifest.get('excluded',[]),*exclusions]}
    results=[]
    source_fingerprints={}
    def source_hash(path):
        key=str(path)
        if key not in source_fingerprints:
            source_fingerprints[key]=tree_fingerprint(path)
        return source_fingerprints[key]
    def dependencies(mod,trail=()):
        result=[]
        for package in mod.get('dependencies',[]):
            if package in trail or package==mod['package_id']:
                continue
            if package in packages:
                parent=packages[package]
                result.extend(dependencies(parent,(*trail,mod['package_id'])))
                result.append(parent)
        return list({item['package_id']:item for item in result}.values())
    for number,mod in enumerate(selected,1):
        print(f"[{number}/{len(selected)}] {mod['package_id']} {mod['name']}",file=sys.stderr,flush=True)
        source=Path(mod['source_path'])
        if source==destination or source in destination.parents or destination in source.parents or destination==game.root or game.root in destination.parents:
            raise SystemExit('Audit outputs must be separate from MOD/game originals')
        deps=dependencies(mod)
        contexts=[*game_contexts,*[Path(dep['source_path']) for dep in deps]]
        dep_dlls=[]
        for dep in deps:
            path=Path(dep['source_path'])
            dep_dlls.extend(content_files(resolve_load_folders(path,version,active),'Assemblies','.dll'))
        before=tree_fingerprint(source)
        source_fingerprints[str(source)]=before
        identity={'source_sha256':before['digest'],'code_sha256':code['digest'],'game_version':version,
                  'game_assembly_sha256':managed_fingerprint,'active_scenario':sorted(active),
                  'repository_sha256':source_hash(Path(mod['repository_root']))['digest'] if mod.get('repository_root') else None,
                  'installed_original_sha256':tree_fingerprint(Path(mod['original_source_path']))['digest'] if mod.get('original_source_path') else None,
                  'manifest_mod':mod,'context_sha256':{str(c):source_hash(c)['digest'] if str(c) not in context_fingerprints else context_fingerprints[str(c)]['digest'] for c in contexts}}
        slug=re.sub(r'[^A-Za-z0-9_.-]','_',mod['package_id'])+'-'+hashlib.sha256(mod['package_id'].encode()).hexdigest()[:8]
        folder=destination/'mods'/slug
        previous=folder/'report.json'
        result=None
        if previous.exists():
            old=json.loads(previous.read_text())
            if not args.force and old.get('identity')==identity and old.get('source_unchanged') and old.get('status')=='pass' and (folder/'entries.json').exists() and (folder/'candidates.json').exists():
                result=old
                result['resumed']=True
            else:
                history=destination/'superseded'
                history.mkdir(exist_ok=True)
                label=slug+'-'+str(time.time_ns())
                folder.rename(history/label)
        if result is None:
            folder.mkdir(parents=True,exist_ok=True)
            result=audit_one(mod,folder,version,active,base,contexts,dep_dlls,schema_cache,identity,before)
        result['report_path']=str(folder/'report.json')
        results.append(result)
        summary=summarize(results,destination,manifest,setup)
        json_write(args.output/'tooling-progress.json',{'run_label':args.run_label,'processed':number,'selected':len(selected),'summary':summary,'current':mod['package_id']})
    context_after={str(path):tree_fingerprint(path) for path in game_contexts}
    setup['game_context_integrity']=all(context_after[key]['digest']==value['digest'] and not context_after[key]['errors'] for key,value in context_fingerprints.items())
    setup['game_context_after_fingerprints']=context_after
    setup['game_assembly_integrity']=hashlib.sha256(managed.read_bytes()).hexdigest()==managed_fingerprint
    for result in results:
        result['integrity']=derive_integrity(result,setup)
        json_write(Path(result['report_path']),result)
    json_write(destination/'setup.json',setup)
    summary=summarize(results,destination,manifest,setup)
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if summary['source_integrity'] and not summary['exceptions'] and not summary['failures'] and setup['game_context_integrity'] and setup['game_assembly_integrity'] and summary['all_integrity'] else 1


if __name__=='__main__':
    raise SystemExit(main())
