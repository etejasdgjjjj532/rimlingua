"""Extraction context reads game profiles and only selected XML parents."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from unittest.mock import patch

from rimworld_translator.installation import ModDependency
from rimworld_translator.platforms import GameInstallation
from rimworld_translator.core import Scan
from rimworld_translator.scan_context import (DependencyContext,context_sources,default_context,dependency_context,
                                                report_dependency_gaps,validate_context)
from rimworld_translator.schema import TranslationSchema,TypeSpec
from tests.test_game_library import make_game


class ScanContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = GameInstallation(self.root/'game',self.root/'game/Mods',self.root/'workshop','1.6.4633',None)
        self.source = self.mod(self.root/'source','sample.source')
        self.core = self.mod(self.game.root/'Data/Core','ludeon.rimworld')
        self.royalty = self.mod(self.game.root/'Data/Royalty','ludeon.rimworld.royalty')
        self.other = self.mod(self.game.workshop/'other','sample.other')
        self.config = self.root/'ModsConfig.xml'

    def mod(self,path,package,deps=(),load_after=(),versions=(),alternatives=None):
        (path/'About').mkdir(parents=True)
        items = ''.join(f'<li><packageId>{d}</packageId><displayName>{d} name</displayName>'
                        + (''.join(f'<li>{a}</li>' for a in (alternatives or {}).get(d, ())) and
                           '<alternativePackageIds>' + ''.join(f'<li>{a}</li>' for a in (alternatives or {}).get(d, ())) + '</alternativePackageIds>')
                        + '</li>' for d in deps)
        after = ''.join(f'<li>{a}</li>' for a in load_after)
        supported = ''.join(f'<li>{v}</li>' for v in versions)
        (path/'About/About.xml').write_text(f'<ModMetaData><name>{package}</name><packageId>{package}</packageId>'
                                           f'<supportedVersions>{supported}</supportedVersions>'
                                           f'<modDependencies>{items}</modDependencies><loadAfter>{after}</loadAfter></ModMetaData>')
        return path

    def test_profile_defaults_are_read_only_and_use_detected_major_minor_version(self):
        original = b'<ModsConfigData><activeMods><li>ludeon.rimworld</li><li>ludeon.rimworld.royalty</li></activeMods></ModsConfigData>'
        self.config.write_bytes(original)
        context = default_context(self.source,self.game,self.config)
        self.assertEqual(context['game_version'],'1.6')
        self.assertEqual(context['active_mods'],['ludeon.rimworld','ludeon.rimworld.royalty','sample.source'])
        self.assertEqual(self.config.read_bytes(),original)

    def test_missing_profile_keeps_unknown_distinct_from_explicit_empty_context(self):
        self.assertIsNone(default_context(self.source,self.game,self.config)['active_mods'])
        self.assertEqual(validate_context('1.6',[])['active_mods'],[])

    def test_unreadable_optional_profile_allows_manual_unknown_context(self):
        original = b'<ModsConfigData><broken>'
        self.config.write_bytes(original)
        context = default_context(self.source,self.game,self.config)
        self.assertIsNone(context['active_mods'])
        self.assertTrue(context['warning'])
        self.assertEqual(self.config.read_bytes(),original)
        with self.assertRaises(ET.ParseError):
            default_context(self.source,self.game,self.config,strict_profile=True)

    def test_invalid_optional_profile_package_id_allows_manual_context(self):
        original = b'<ModsConfigData><activeMods><li>invalid/id</li></activeMods></ModsConfigData>'
        self.config.write_bytes(original)
        context = default_context(self.source,self.game,self.config)
        self.assertIsNone(context['active_mods'])
        self.assertTrue(context['warning'])
        self.assertEqual(self.config.read_bytes(),original)
        with self.assertRaises(ValueError):
            default_context(self.source,self.game,self.config,strict_profile=True)

    def test_context_parents_include_only_selected_mods_and_never_source_twice(self):
        self.assertEqual(set(context_sources(self.game,self.source,['ludeon.rimworld','sample.other'])),{self.core,self.other})
        self.assertEqual(context_sources(self.game,self.core,None),[])

    def test_transitive_dependencies_found_even_when_inactive(self):
        a = self.mod(self.game.workshop/'a','sample.a',deps=['sample.b'])
        b = self.mod(self.game.mods/'b','sample.b',deps=['sample.c'])
        c = self.mod(self.game.workshop/'c','sample.c')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a'])
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertEqual(set(ctx.sources),{self.core,a,b,c})
        self.assertEqual(len(ctx.sources),4)
        self.assertEqual(ctx.missing,())

    def test_cycle_and_self_dependency_terminate(self):
        a = self.mod(self.game.workshop/'a','sample.a',deps=['sample.b'])
        b = self.mod(self.game.workshop/'b','sample.b',deps=['sample.a'])
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.src2','sample.a'])
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertEqual(sorted(ctx.sources),sorted([self.core,a,b]))

    def test_missing_dependency_listed_once(self):
        self.mod(self.game.workshop/'a','sample.a',deps=['sample.gone'])
        self.mod(self.game.workshop/'b','sample.b',deps=['sample.gone'])
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a','sample.b'])
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertEqual([(d.package_id,d.display_name) for d in ctx.missing],[('sample.gone','sample.gone name')])

    def test_load_after_is_reported_not_used(self):
        optional = self.mod(self.game.workshop/'opt','sample.opt')
        source = self.mod(self.root/'src2','sample.src2',load_after=['sample.opt','sample.absent'])
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertEqual(ctx.load_after,('sample.opt',))
        self.assertNotIn(optional,ctx.sources)

    def test_unsupported_version_reported(self):
        self.mod(self.game.workshop/'old','sample.old',versions=['1.5'])
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.old'])
        self.assertEqual(dependency_context(self.game,(),source,'1.6',None).unsupported,('sample.old',))
        self.assertEqual(dependency_context(self.game,(),source,'1.5',None).unsupported,())

    def test_version_specific_dependencies_are_used(self):
        old = self.mod(self.game.workshop/'old14','sample.old14')
        new = self.mod(self.game.workshop/'new','sample.new')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.new'])
        about = source/'About/About.xml'
        about.write_text(about.read_text().replace('</ModMetaData>',
            '<modDependenciesByVersion><v1.4><li><packageId>sample.old14</packageId></li></v1.4></modDependenciesByVersion></ModMetaData>'))
        self.assertIn(old,dependency_context(self.game,(),source,'1.4',None).sources)
        self.assertNotIn(new,dependency_context(self.game,(),source,'1.4',None).sources)
        self.assertIn(new,dependency_context(self.game,(),source,'1.6',None).sources)

    def test_alternative_package_id_satisfies_dependency(self):
        fork = self.mod(self.game.workshop/'fork','sample.a.fork')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a'],alternatives={'sample.a':['sample.a.fork']})
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertIn(fork,ctx.sources)
        self.assertEqual(ctx.missing,())

    def test_other_copy_of_source_is_not_a_source(self):
        copy = self.mod(self.game.workshop/'copy','sample.source')
        ctx = dependency_context(self.game,(),self.source,'1.6',['sample.source'])
        self.assertNotIn(copy,ctx.sources)
        self.assertNotIn(self.source,ctx.sources)

    def test_active_ids_include_found_dependencies(self):
        self.mod(self.game.workshop/'a','sample.a')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a','sample.gone'])
        ctx = dependency_context(self.game,(),source,'1.6',[])
        self.assertEqual(set(ctx.active_ids),{'ludeon.rimworld','sample.a'})

    def test_explicit_empty_active_mods_still_gets_core_and_prerequisites(self):
        a = self.mod(self.game.workshop/'a','sample.a')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a'])
        self.assertEqual(set(context_sources(self.game,source,[])),{self.core,a})

    def test_library_copy_finds_dependencies_in_steam_installation(self):
        lib_root = self.root/'lib/1.4/RimWorld'
        lib_core = self.mod(lib_root/'Data/Core','ludeon.rimworld')
        lib = GameInstallation(lib_root,lib_root/'Mods',None,'1.4.3901',None)
        dep = self.mod(self.game.workshop/'dep','sample.dep')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.dep'])
        ctx = dependency_context(lib,[self.game],source,'1.4',None)
        self.assertEqual(set(ctx.sources),{lib_core,dep})

    def test_no_game_reads_dependencies_but_never_reports_game_packages_missing(self):
        dep = self.mod(self.game.workshop/'dep','sample.dep')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.dep','ludeon.rimworld.biotech'])
        ctx = dependency_context(None,[self.game],source,'1.4',None)
        self.assertEqual(ctx.sources,(dep,))
        self.assertEqual(ctx.missing,())

    def test_leftover_dlc_folder_is_not_a_source(self):
        root = make_game(self.root/'old',  '1.1.2654', ['1.1.7459','ludeon.rimworld.royalty'],
                         {'Royalty':'ludeon.rimworld.royalty','Biotech':'ludeon.rimworld.biotech'})
        old = GameInstallation(root,root/'Mods',None,'1.1.2654',None)
        ctx = dependency_context(old,(),self.source,'1.1',['ludeon.rimworld.royalty','ludeon.rimworld.biotech'])
        self.assertEqual({p.name for p in ctx.sources},{'Core','Royalty'})
        self.assertNotIn('ludeon.rimworld.biotech',[d.package_id for d in ctx.missing])

    def test_unknown_profile_assumes_installed_dlcs_and_found_prerequisites(self):
        root = make_game(self.root/'old',  '1.1.2654', ['1.1.7459','ludeon.rimworld.royalty'],
                         {'Royalty':'ludeon.rimworld.royalty','Biotech':'ludeon.rimworld.biotech'})
        old = GameInstallation(root,root/'Mods',None,'1.1.2654',None)
        self.mod(root/'Mods/dep','sample.dep')
        self.mod(root/'Mods/unrelated','sample.unrelated')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.dep'])
        ctx = dependency_context(old,(),source,'1.1',None)
        self.assertEqual(ctx.installed_dlcs,('ludeon.rimworld.royalty',))
        # The source itself, Core, the DLCs this game knows and the prerequisites found; nothing else.
        self.assertEqual(set(ctx.assumed_active),{'sample.src2','ludeon.rimworld','ludeon.rimworld.royalty','sample.dep'})
        # Royalty is assumed loaded, but it is not read as XML context unless something requires it.
        self.assertEqual({p.name for p in ctx.sources},{'Core','dep'})

    def test_unreadable_about_is_reported_not_skipped(self):
        broken = self.mod(self.game.workshop/'broken','sample.broken')
        from rimworld_translator import scan_context
        real = scan_context.read_mod_metadata
        def reader(path,*args):
            if path == broken:
                raise OSError('path too long')
            return real(path,*args)
        with patch.object(scan_context,'read_mod_metadata',reader):
            ctx = dependency_context(self.game,(),self.source,'1.6',None)
        self.assertIn(broken,ctx.unreadable)

    def test_source_without_package_id_still_gets_core(self):
        bare = self.root/'bare'
        (bare/'Defs').mkdir(parents=True)
        ctx = dependency_context(self.game,(),bare,'1.6',None)
        self.assertEqual(ctx.sources,(self.core,))

    def test_symlinked_or_broken_about_is_unreadable_not_missing(self):
        real = self.mod(self.root/'real-about','sample.linked')
        linked = self.game.workshop/'linked'
        (linked/'About').mkdir(parents=True)
        (linked/'About/About.xml').symlink_to(real/'About/About.xml')
        broken = self.game.workshop/'broken'
        (broken/'About').mkdir(parents=True)
        (broken/'About/About.xml').write_text('<ModMetaData><packageId>sample.broken')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.linked'])
        ctx = dependency_context(self.game,(),source,'1.6',None)
        self.assertIn(linked,ctx.sources)
        self.assertIn(broken,ctx.unreadable)
        self.assertEqual(ctx.missing,())

    def test_metadata_is_read_once_per_unchanged_folder(self):
        from rimworld_translator import scan_context
        self.mod(self.game.workshop/'a','sample.a')
        source = self.mod(self.root/'src2','sample.src2',deps=['sample.a'])
        real, calls = scan_context.read_mod_metadata, []
        def counting(path,*args):
            calls.append(Path(path))
            return real(path,*args)
        with patch.object(scan_context,'read_mod_metadata',counting):
            dependency_context(self.game,[self.game],source,'1.4',None)
            first = len(calls)
            dependency_context(self.game,[self.game],source,'1.6',None)
        self.assertEqual(len(calls),first)
        self.assertEqual(len(set(calls)),len(calls))

    def test_cancel_stops_the_folder_walk(self):
        from rimworld_translator.extraction import ScanCancelled
        for index in range(3):
            self.mod(self.game.workshop/f'm{index}',f'sample.m{index}')
        with self.assertRaises(ScanCancelled):
            dependency_context(self.game,(),self.source,'1.6',None,cancel=lambda: True)

    def gaps(self,**kwargs):
        values = dict(sources=(),active_ids=(),missing=(),load_after=(),unsupported=(),unreadable=())
        values.update(kwargs)
        return DependencyContext(**values)

    def unknown(self,owner):
        return {'code':'unknown-field','message':f'Field absent from CLR schema: {owner}','source_file':'Defs/a.xml',
                'entry_id':'','owner_type':owner}

    def test_missing_prerequisite_counts_only_fields_of_unreadable_types(self):
        scan = Scan(diagnostics=[self.unknown('VEF.Foo'),self.unknown('VEF.Foo'),self.unknown('Verse.ThingDef')])
        schema = TranslationSchema(types={'Verse.ThingDef':TypeSpec('Verse.ThingDef','',{})})
        report_dependency_gaps(scan,self.gaps(missing=(ModDependency('sample.gone','Gone MOD'),)),schema)
        found = [d for d in scan.diagnostics if d['code']=='missing-dependency']
        self.assertEqual(len(found),1)
        self.assertEqual((found[0]['count'],found[0]['package_ids']),(2,['sample.gone']))
        self.assertIn('Gone MOD (sample.gone)',found[0]['message'])
        self.assertNotIn('at least',found[0]['message'])
        self.assertEqual((scan.warning_count,scan.warnings[-1]),(1,found[0]['message']))

    def test_dropped_diagnostics_make_the_count_a_lower_bound(self):
        scan = Scan(diagnostics=[self.unknown('VEF.Foo')],
                    warnings=['3 additional distinct warnings omitted (total events 9); inspect source context manually'])
        report_dependency_gaps(scan,self.gaps(missing=(ModDependency('sample.gone','Gone'),)),TranslationSchema())
        self.assertIn('at least 1',scan.diagnostics[-1]['message'])

    def test_without_field_checks_the_message_does_not_claim_zero(self):
        scan = Scan()
        report_dependency_gaps(scan,self.gaps(missing=(ModDependency('sample.gone','Gone'),)),None)
        message = scan.diagnostics[-1]['message']
        self.assertNotIn('0 fields',message)
        self.assertIn('not checked',message)
        self.assertIsNone(scan.diagnostics[-1]['count'])

    def test_no_missing_prerequisite_no_report(self):
        scan = Scan(diagnostics=[self.unknown('VEF.Foo')])
        report_dependency_gaps(scan,self.gaps(),None)
        self.assertEqual([d['code'] for d in scan.diagnostics],['unknown-field'])

    def test_unsupported_load_after_and_unreadable_are_each_reported(self):
        scan = Scan()
        report_dependency_gaps(scan,self.gaps(unsupported=('sample.old','sample.older'),load_after=('sample.opt',),
                                              unreadable=(Path('/long/path'),)),None)
        codes = [d['code'] for d in scan.diagnostics]
        self.assertEqual(codes.count('dependency-version-unverified'),2)
        self.assertEqual(codes.count('dependency-load-after-unused'),1)
        self.assertEqual(codes.count('dependency-unreadable'),1)
        self.assertTrue(all({'source_file','entry_id','suggestion'} <= set(d) for d in scan.diagnostics))
        self.assertEqual(scan.warning_count,4)

    def test_invalid_version_and_package_ids_are_rejected(self):
        for version,packages in [('unknown',[]),('1.6',['bad/path']),('1.6','sample.other')]:
            with self.assertRaises(ValueError):
                validate_context(version,packages)
