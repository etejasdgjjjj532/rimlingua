"""Independent evidence attribution; fixtures do not enter the real MOD count."""
import tempfile
import json
import logging
from types import SimpleNamespace
import unittest
from pathlib import Path
from tools import audit_mod_corpus as audit
from rimworld_translator.schema import FieldSpec, TranslationSchema, TypeSpec


class ModAuditTests(unittest.TestCase):
    def test_stale_catalog_is_not_confirmed_miss(self):
        item = dict(id='DefInjected:ThingDef:Old.label', origin='catalog', selected=False,
                    text='Ancien', source_file='1.4/Languages/French/DefInjected/ThingDef/a.xml')
        self.assertEqual(audit.classify_candidate(item, set(), {} )['classification'], 'correct_nontranslatable')

    def test_owned_schema_field_without_catalog_is_confirmed(self):
        item = dict(id='DefInjected:ThingDef:Active.label', origin='raw_def', selected=True,
                    text='Visible name', schema_translatable=True, certain=True, owned=True)
        self.assertEqual(audit.classify_candidate(item, set(), {})['classification'], 'confirmed_miss')

    def test_foreign_catalog_cannot_prove_owned_miss(self):
        item = dict(id='DefInjected:ThingDef:Foreign.label', origin='catalog', selected=True,
                    text='Traduit', owner='external_mod')
        self.assertEqual(audit.classify_candidate(item, set(), {})['classification'], 'correct_nontranslatable')

    def test_unresolved_runtime_catalog_remains_possible(self):
        item = dict(id='DefInjected:ThingDef:Generated.label', origin='catalog', selected=True, text='Generated')
        self.assertEqual(audit.classify_candidate(item, set(), {})['classification'], 'possible_miss')

    def test_empty_mod_has_no_candidates_not_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            evidence = audit.raw_def_evidence(source, [source], TranslationSchema(), set(), [])
            self.assertEqual(evidence['candidates'], [])

    def test_independent_inheritance_proves_selected_child_label(self):
        schema = TranslationSchema({'Verse.Def': TypeSpec('Verse.Def', fields={'label':FieldSpec('System.String')}),
                                    'Verse.ThingDef':TypeSpec('Verse.ThingDef','Verse.Def')})
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source/'Defs').mkdir()
            (source/'Defs/a.xml').write_text('<Defs><ThingDef Name="Base" Abstract="True"><label>Inherited text</label></ThingDef><ThingDef ParentName="Base"><defName>Child</defName></ThingDef></Defs>')
            evidence = audit.raw_def_evidence(source, [source], schema, set(), [])
            candidate = next(c for c in evidence['candidates'] if c['id']=='DefInjected:ThingDef:Child.label')
            self.assertTrue(candidate['certain'])
            self.assertEqual(candidate['text'], 'Inherited text')
            self.assertTrue(candidate['inheritance'])

    def test_root_inherit_false_does_not_invent_parent_field(self):
        schema = TranslationSchema({'Verse.Def': TypeSpec('Verse.Def', fields={'label':FieldSpec('System.String')}),
                                    'Verse.ThingDef':TypeSpec('Verse.ThingDef','Verse.Def')})
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)
            (source/'Defs').mkdir()
            (source/'Defs/a.xml').write_text('<Defs><ThingDef Name="Base" Abstract="True"><label>Parent</label></ThingDef><ThingDef ParentName="Base" Inherit="False"><defName>Child</defName></ThingDef></Defs>')
            evidence=audit.raw_def_evidence(source,[source],schema,set(),[])
            self.assertFalse(any(c['id']=='DefInjected:ThingDef:Child.label' for c in evidence['candidates']))

    def test_string_texture_reference_is_semantically_nontranslatable(self):
        schema=TranslationSchema({'PowerDef':TypeSpec('PowerDef',fields={'texPath':FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)
            (source/'Defs').mkdir()
            (source/'Defs/a.xml').write_text('<Defs><PowerDef><defName>Jump</defName><texPath>Powers/Jump</texPath></PowerDef></Defs>')
            raw=audit.raw_def_evidence(source,[source],schema,set(),[])['candidates'][0]
            result=audit.classify_candidate(raw,set(),{})
            self.assertEqual(result['classification'],'correct_nontranslatable')
            self.assertEqual(result['semantic_exclusion'],'asset_or_identifier_field')

    def test_wrong_def_root_cannot_prove_confirmed_schema_miss(self):
        schema=TranslationSchema({'ThingDef':TypeSpec('ThingDef',fields={'label':FieldSpec('System.String')})})
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)
            (source/'Defs').mkdir()
            (source/'Defs/a.xml').write_text('<LanguageData><ThingDef><defName>Wrong</defName><label>Visible</label></ThingDef></LanguageData>')
            evidence=audit.raw_def_evidence(source,[source],schema,set(),[])
            self.assertEqual(evidence['candidates'],[])
            self.assertEqual(evidence['diagnostics'][0]['code'],'independent-xml-root')

    def test_utf16_catalog_dtd_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)
            keyed=source/'Languages/English/Keyed'
            keyed.mkdir(parents=True)
            (keyed/'a.xml').write_bytes('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE LanguageData [<!ENTITY value "Expanded">]><LanguageData><Key>&value;</Key></LanguageData>'.encode('utf-16'))
            diagnostics=[]
            self.assertEqual(audit.catalog_evidence(source,[source],diagnostics),[])
            self.assertIn('DTD',diagnostics[0]['error'])

    def test_warning_events_are_distinct_from_omissions(self):
        self.assertTrue(hasattr(audit,'diagnostic_counts_from_scan'))
        scan=SimpleNamespace(warning_count=1505,diagnostics=[{}]*1503)
        result=audit.diagnostic_counts_from_scan(scan,diagnostic_limit=None)
        self.assertEqual(result['repeated_warning_events'],2)
        self.assertEqual(result['omitted_distinct_diagnostics'],0)
        self.assertEqual(result['distinct_warning_diagnostics'],1503)

    def test_emitted_identity_flag_does_not_claim_candidate_scope(self):
        item=dict(id='Keyed:Keyed:Same',origin='catalog',selected=False)
        result=audit.classify_candidate(item,{item['id']},{})
        self.assertTrue(result.get('emitted_id_unblocked',False))
        self.assertNotIn('usable_extracted_match',result)
        self.assertEqual(result['classification'],'correct_nontranslatable')

    def test_integrity_includes_installed_original_and_game(self):
        self.assertTrue(hasattr(audit,'derive_integrity'))
        result=audit.derive_integrity({'source_unchanged':True,'installed_original_integrity':{'unchanged':False}}, {'game_context_integrity':True,'game_assembly_integrity':True})
        self.assertFalse(result['all_integrity'])
        self.assertTrue(result['mod_source_integrity'])
        self.assertFalse(result['installed_original_integrity'])

    def test_test_and_template_source_roles_are_not_runtime_misses(self):
        self.assertTrue(hasattr(audit,'csharp_source_role'))
        with tempfile.TemporaryDirectory() as folder:
            repo=Path(folder)
            for name in ('Source/UnitTests/Example.cs','ModSupport/CookieCutter/Example.cs','Source/Mod/Example.cs'):
                path=repo/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('"Visible".Translate();')
            for name,role in [('Source/UnitTests/Example.cs','test'),('ModSupport/CookieCutter/Example.cs','template')]:
                evidence=audit.csharp_source_role(repo/name,repo)
                self.assertEqual(evidence['source_role'],role)
                item={'id':'','origin':'csharp_translate','selected':True,**evidence}
                self.assertEqual(audit.classify_candidate(item,set(),{})['classification'],'correct_nontranslatable')
            self.assertEqual(audit.csharp_source_role(repo/'Source/Mod/Example.cs',repo)['source_role'],'unverified_source')

    def test_dnfile_warning_capture_is_scoped_and_structured(self):
        self.assertTrue(hasattr(audit,'capture_dnfile_warnings'))
        diagnostics=[]
        logger=logging.getLogger('dnfile.stream')
        with self.assertLogs('dnfile',level='WARNING'):
            with audit.capture_dnfile_warnings(Path('example.dll'),diagnostics):
                logger.warning('malformed flag %s',3)
            before=len(diagnostics)
            logger.warning('outside audit capture')
        self.assertEqual(len(diagnostics),before)
        self.assertEqual(diagnostics[0]['source_file'],'example.dll')
        self.assertEqual(diagnostics[0]['message'],'malformed flag 3')

    def test_normalization_preserves_raw_reports_and_extraction_fingerprints(self):
        self.assertTrue(hasattr(audit,'normalize_run_reports'))
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)
            per=run/'mods/example'; per.mkdir(parents=True)
            report={'mod':{'source_path':str(run/'source'),'package_id':'test.example','name':'Example'},'identity':{'code_sha256':'baseline-code'},
                    'source_before':{'digest':'source-before'},'source_after':{'digest':'source-before'},'source_unchanged':True,'status':'pass',
                    'counts':{'entries':1},'warning_count':3,'warnings':['same warning'],'diagnostics':[{'code':'warning','message':'same warning'}],
                    'diagnostic_omitted_events':2,'candidate_counts':{'confirmed_miss':1},'candidate_identity_counts':{'confirmed_miss':1}}
            candidate={'id':'DefInjected:PowerDef:Jump.texPath','origin':'raw_def','kind':'DefInjected','group':'PowerDef','key':'Jump.texPath',
                       'text':'Powers/Jump','source_file':'raw.xml','selected':True,'owned':True,'schema_translatable':True,'certain':True,
                       'classification':'confirmed_miss','usable_extracted_match':False}
            audit.json_write(per/'report.json',report); audit.json_write(per/'candidates.json',[candidate])
            audit.json_write(per/'entries.json',[{'id':'Keyed:Keyed:Label','english':'Visible'}])
            audit.json_write(run/'setup.json',{'code':{'digest':'baseline-code'},'game_context_integrity':True,'game_assembly_integrity':True,'command':'original scan'})
            audit.json_write(run/'results.json',{'summary':{'confirmed_candidate_identities':1},'excluded':[],'acquisition_attempts':[]})
            raw=(per/'report.json').read_bytes(); entries=(per/'entries.json').read_bytes()
            summary=audit.normalize_run_reports(run)
            corrected=json.loads((per/'report.json').read_text())
            self.assertEqual((per/'report-original.json').read_bytes(),raw)
            self.assertEqual((per/'entries.json').read_bytes(),entries)
            self.assertEqual(corrected['identity']['code_sha256'],'baseline-code')
            self.assertEqual(corrected['repeated_warning_events'],2)
            self.assertNotIn('diagnostic_omitted_events',corrected)
            self.assertEqual(summary['confirmed_candidate_identities'],0)
            self.assertTrue(corrected['integrity']['all_integrity'])
            self.assertIn('report-original.json',corrected['normalization_provenance']['originals'])

    def test_full_integrity_hash_detects_non_xml_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)
            (source/'texture.png').write_bytes(b'first')
            before=audit.tree_fingerprint(source)
            (source/'texture.png').write_bytes(b'other')
            self.assertNotEqual(before['digest'], audit.tree_fingerprint(source)['digest'])


if __name__=='__main__':
    unittest.main()
