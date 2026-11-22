"""Direct IL references remain diagnostic candidates, never invented XML entries."""
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
import zlib

from rimworld_translator.core import scan_mod

# Independently compiled from four own C# methods: direct string Translate,
# dynamic string Translate, two-argument overload, and a plain string return.
# The fixture references an own stub Assembly-CSharp; neither DLL is executed.
ASSEMBLY = zlib.decompress(base64.b64decode(
'eNrtVk1sG0UU/sZxgpu0JlFpBbS0myZAW9FV0kSoFQjy4/6kyp/iNJRSqV3bU2dhvWtm1yGWqqpI9IYqTlxB4tBLDxx6iJCoOCA4lSPlgBDiRCWkcoUD4ZvZdeyYSFURN/qSffPemzdvvpl5b8Yz5z9CB4A0v/V1YA0xjeHhdI1fdv8XWdzedrd/TUzf7V9cdkOrqoKycipW0fH9ILIK0lI133J9KzeXtypBSdo7dnQPJjHmTwDTogO//nHzs0bcn3HA6hFDQBfij/S9HmBtAOs1cirGDTRbAyoVix0Yu65d9X+z3WgMfcC4c8mCv0ptschLwHY2y/Tbi0cg4su0qBnqp1t0O5KrEdsf08m6upq4W0JcslWoikiwjSULzWz2o3nMVtILijFWjdnE2v4Pv4l2mGvJQZw2Qzqxykl/Z0II/DuyFUdWD3YC3Yf3peL2qNpP21MHu7TyrBqncngif2ZCJLNomCuj9pA9MjQyfFxbOuFpTOweuArcZntBy/lIuX45NGdIjNpn4GweVzriMx04dXYqx/ZD6iWtT3hBIcHF7RCndgHbtPKnGMHueI1PJFult1Ukx9CQ4+O4naDsgo+U6MINwyfwAE/igND2JWN5RXyLbvyEo8ZbJFzgfdGLYarPGG1enzU+xoQYpHYh0fqJX6CUaIcwyLnfTbRbRtOxzoltuM+2j7yL8e5zvkPGchzHGEHzXXgRA3gTNnpwkHwnhsn3YB7pa+1nNUVU3S36nk1ag75riq/OBKWaJ19Dvh5GsmLPK3fFiaQ9GSg57RaQq/tOxS1ibkUqL3BKWJIqlFhUjh96dEROFmrlslPw5HjEsyzUaFuQl/POZRnVFxg6bNong0rV5Sg38Bek56waqaV/oeZHbkVqN3YVXM+N6s3eaTeSyvGggppfGhk9EjmqLCO75HkJeIyHoawUvPqRyfyyo6obKAMFu6h5ssic65T9IIzcYtgwJVPbMUSp8lKtuEUZJutjjnKjqC6yxicdzwsxV3hbFiPkXKWbzaDwjqwDz52Ei1VEqEFB8sxy1LVUpA397b1zWGGrWAMBHJ3th2YpRewZ57fIHof5GrLfoVWPmKTkmZo5f+eFXz65dS93vfjylbeu7j+DtCVEpsOC6KTQ15eGyGY7kcpm92au/Hb93p2b9RssqWxGJDfPPp3Ji6ndbyinOhv4J1aLsqpPZ3FZBe+Fgn5x6VDo2SKjetv0W4NN+ZvGPb8FrQ22aheZdTnPm3FcH5WwyBSU5ng1rT/PGL14TI9Iwmza0/Erusmu77OhLeyNt+McH5dSy/tVSo2SLyGPi+QnsEBpilk7S32K/GT86uLL9IO/tnptXm9519uf5ZyZeYn5rKDrwmN+TzHbL7MCNA2aUe014LLXTyJ8nv5a6Bh52hV7fJS3iPSp8Rna+BtFQe8BXiIiseGf4xeySnWc6qZ5LLNnmRbfJVOzYYvPECuz+YGeO+mvMUTG1zdVO0teoQ5aAt4BPit+hHiO0EvvQpl9uvZLSYWDd7/GOE172USY5Lgq6gZlGcv6TjH4Zs18c4ndTeZr4PUfed5Rs95541/iCH17ta+6fc3HzJhxeoT0rHCXPSK1HjruMf0HZMW/v34YfbwV/0f6Gy84bB0='))


class ILRound34Tests(unittest.TestCase):
    def test_direct_call_is_evidenced_without_exportable_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assembly = root / 'Assemblies/Fixture.dll'
            assembly.parent.mkdir()
            assembly.write_bytes(ASSEMBLY)
            before = hashlib.sha256(assembly.read_bytes()).hexdigest()
            result = scan_mod(root)
            self.assertEqual(result.entries, [])
            candidates = [d for d in result.diagnostics if d['code'] == 'dll-translate-candidate']
            self.assertEqual(len(candidates), 1)
            self.assertIn('Fixture.Direct', candidates[0]['message'])
            self.assertIn('Direct', candidates[0]['message'])
            self.assertIn('IL_0005', candidates[0]['message'])
            self.assertEqual(candidates[0]['source_file'], 'Assemblies/Fixture.dll')
            self.assertEqual(candidates[0]['entry_id'], '')
            self.assertEqual(before, hashlib.sha256(assembly.read_bytes()).hexdigest())

    def test_broken_dll_does_not_interrupt_xml_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Assemblies').mkdir()
            (root / 'Assemblies/Broken.dll').write_bytes(b'MZbroken')
            keyed = root / 'Languages/English/Keyed/Own.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Own>Own text</Own></LanguageData>')
            result = scan_mod(root)
            self.assertEqual([e.id for e in result.entries], ['Keyed:Keyed:Own'])
            self.assertTrue(any(d['code'] == 'dll-il-unverified' for d in result.diagnostics))

    def test_instruction_boundaries_and_control_flow_cannot_invent_literal_calls(self):
        from rimworld_translator.il_candidates import direct_literal_calls
        literal = bytes.fromhex('7201000070')
        call = bytes.fromhex('280100000a')
        self.assertEqual(direct_literal_calls(literal + call + b'\x2a', {0x0a000001}), [(5, 0x70000001)])
        # Bytes resembling ldstr/call belong to a ldc.i8 operand.
        self.assertEqual(direct_literal_calls(b'\x21' + literal + call[:3] + b'\x2a', {0x0a000001}), [])
        # A branch can bypass the literal and enter the call directly.
        self.assertEqual(direct_literal_calls(b'\x2b\x05' + literal + call + b'\x2a', {0x0a000001}), [])
        # Branching to the literal is safe to list as an unverified candidate.
        self.assertEqual(direct_literal_calls(b'\x2b\x00' + literal + call + b'\x2a', {0x0a000001}), [(7, 0x70000001)])
        # Bad targets, unsupported opcodes and truncated operands reject a body.
        for body in (b'\x2b\x01' + literal + call, b'\x24' + literal + call, literal + call + b'\x21'):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    direct_literal_calls(body, {0x0a000001})
        self.assertEqual(direct_literal_calls(literal + call + b'\x2a', {0x0a000002}), [])

    def test_target_only_versioned_dlls_are_inspected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, context = root / 'source', root / 'context'
            source.mkdir()
            (source / 'LoadFolders.xml').write_text('<loadFolders><v1.6><li>1.6</li></v1.6>'
                                                   '<v1.10><li>1.10</li></v1.10></loadFolders>')
            for base in (source / '1.6', context / '1.10'):
                file = base / 'Assemblies/Fixture.dll'
                file.parent.mkdir(parents=True)
                file.write_bytes(ASSEMBLY)
            (source / '1.10').mkdir()
            old = scan_mod(source, game_version='1.6', context_sources=[context])
            new = scan_mod(source, game_version='1.10', context_sources=[context])
            self.assertEqual(len([d for d in old.diagnostics if d['code'] == 'dll-translate-candidate']), 1)
            self.assertFalse(any(d['code'] == 'dll-translate-candidate' for d in new.diagnostics))
            self.assertEqual(old.entries, [])
            self.assertEqual(new.entries, [])

    def test_fake_translator_namespace_is_excluded(self):
        from rimworld_translator.il_candidates import inspect_translate_calls
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'Fake.dll'
            self.assertIn(b'Verse\x00', ASSEMBLY)
            file.write_bytes(ASSEMBLY.replace(b'Verse\x00', b'Fakes\x00'))
            self.assertEqual(inspect_translate_calls(file), [])

    def test_inspection_cancellation_preserves_caller_exception(self):
        from rimworld_translator.extraction import ScanCancelled
        from rimworld_translator.il_candidates import inspect_translate_calls
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'Fixture.dll'
            file.write_bytes(ASSEMBLY)
            def cancel():
                raise ScanCancelled('stop')
            with self.assertRaises(ScanCancelled):
                inspect_translate_calls(file, cancel)

    def test_oversized_il_body_is_rejected_without_parsing_it(self):
        from rimworld_translator.il_candidates import direct_literal_calls
        with self.assertRaises(ValueError):
            direct_literal_calls(bytes(1024 * 1024 + 1), {0x0a000001})

    def test_tagged_string_return_type_must_belong_to_game_assembly(self):
        import dnfile
        from rimworld_translator.il_candidates import inspect_translate_calls
        data = zlib.decompress(base64.b64decode('eNrtVk1oXFUU/t5kEiY/jYktwb/YFydiLc1jJIMoiM3PJG0kf2QmqUihfTNzM3n1zXvDfW/SBEQq2J2oKxFX7gquXCgGUSni0oIb0YUL11LQXUGw8bv3vfnJNFAqrjTnzT33nnPPPfc75/7N0mvvowtAkmV/H9hDRFO4P11jGTz55SA+6701tmcs3horbDmBWZN+RdpVs2R7nh+aRWHKumc6nplbyZtVvyysY8f6xmMfq3PAotGFvdff+7Dh91c8ZfYbGaAHUSGdVgPMJrAh3U5EuIFWrUElomYXpq4rU/Vr1c1K089pYCUO+GbikCAvAwOsvqLdE3gAIr5Um5iifL5NtkKxE7LOJOO4elq421xctmQgS4ixTcWBpg7aUT1lSeH6pQirwqx9DdxjN9MJcyBeiPN6SDcuqkm5IQz8M7IkR9ZOdQN9p2fyr8wYsScFZTtrZazJzORzLypNN1zyE+xOv8llY72q2vlQOl4lUBY/JKLUpNfz+CMRrVv63PpCLlpcHWZ6xvWL8dw0Mc6dAHqV8KcxiZEojlScDkPPGqXQaKb72xhhD/EMGT14R/Mp/IWHkDGUvqA1Z40f0YdPkCG/TQ40sqRifMsYwhdsP6qlVQUbH2DeOEmpF3fIh8l72H+H45/Vmmk8z5ieQRrrsNCPcfLjmCB/HItIXuvM7RhLX5s8ckBq0C+t5ktLfrnuipeR3w1CUbVWpbNth8Ka9aVYdIqQft0rT2YnQrtSEWVsCBkIFKTtBS7NkBPFeqViF10xHXJVinXq1sRm3t4U4e4aHQct/axfrTkc5fjemnDtHd1q61+re6FTFcqMXUXHdcLdVm9BA4iWPhZmbdftAGiVqYpCwXQQiGrR3Z2YzW/ZstZE7UtYJcXjkHOOXfH8IHRKQUMVQ7EiyELmhdx2SiKI4yUEpo3iSvGKKIXIOVJVikbn4WAHIeqQEFynAmxU+AmU2X314dkr1c9v5j56++KNC9//dhdJ0zBSXSaMbjaGh7thDI8Opt64ff2nb27svsttODyaMuLT/KTaN4XEyAVp15Z9b26nJGoqh4Ut6V8NDNpF25WN/kNWfahTMd5qPta4Ow+hgfF26RJ3Rs51l2zHQzUocZsInXRF+0/TxxCO6D9Mhl7gR6JX9IBe3XSZQ/SNt+NVPi7ltvernMiSbyCPS+RzWGNrgS/tMuUF8vno1cXXyd/vHvbanG171zuf5ZyeeYNnT0KdSJfnbwEeNuHHW1+NKrDXpjZgv80z67DXiz18mvzOUD7y1Ev2eDzD93r6WNtkml8WRX3vnyEio2mfYwlQ0n5qB+Yxdc5SbbYbLJLWLZsMb5FWAS2P015hCLWtR+wu82WjShnU+Lx9PN43k8QzQavWDWSxuIhO6ymNcZH6ivYwy3E17GqUFWwhjPEt6/lWYr0Tz9fA6z3wvFkd76q2L3NEiZadUXfG/IIeM02LgJZVZtklUvO+447oXyAz+m92JnuUiv8j/Q1i30z1'))
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'Tagged.dll'
            file.write_bytes(data)
            self.assertEqual([c[3] for c in inspect_translate_calls(file)], ['Fixture.Tagged'])
            pe = dnfile.dnPE(str(file))
            try:
                row = next(r for r in pe.net.mdtables.TypeRef.rows if str(r.TypeName) == 'TaggedString')
                other = next(r for r in pe.net.mdtables.TypeRef.rows if str(r.TypeNamespace) == 'System')
                offset = row.struct.get_field_absolute_offset('ResolutionScope_CodedIndex')
                bad = bytearray(data)
                bad[offset:offset + 2] = other.struct.ResolutionScope_CodedIndex.to_bytes(2, 'little')
            finally:
                pe.close()
            file.write_bytes(bad)
            self.assertEqual(inspect_translate_calls(file), [])
