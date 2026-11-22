"""Unsupported fat-header flags cannot supply direct Translate evidence."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import dnfile

from rimworld_translator.il_candidates import inspect_translate_calls
from test_il_round34 import ASSEMBLY


def fat_fixture(flags):
    """Replace one tiny method with a fat method, retaining real CLR metadata."""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'metadata.dll'
        path.write_bytes(ASSEMBLY)
        pe = dnfile.dnPE(str(path))
        try:
            data = bytearray(ASSEMBLY)
            methods = pe.net.mdtables.MethodDef.rows
            offset = pe.get_offset_from_rva(methods[0].Rva)
            # The original tiny method has 11 bytes of IL; the following three
            # fixture methods are disabled because the expanded header uses them.
            body = bytes.fromhex('7201000070 280500000a 2a')
            for method in methods[1:]:
                rva_offset = method.struct.get_field_absolute_offset('Rva')
                data[rva_offset:rva_offset + 4] = bytes(4)
            header = flags.to_bytes(2, 'little') + b'\x08\x00' + b'\x0b\x00\x00\x00' + bytes(4)
            data[offset:offset + len(header) + len(body)] = header + body
            return bytes(data)
        finally:
            pe.close()


class ILRound42Tests(unittest.TestCase):
    def test_supported_fat_headers_keep_direct_candidate(self):
        for flags in (0x3003, 0x3013):
            with self.subTest(flags=hex(flags)), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'Fixture.dll'
                path.write_bytes(fat_fixture(flags))
                before = hashlib.sha256(path.read_bytes()).digest()
                self.assertEqual(inspect_translate_calls(path), [(1, 'Direct', 5, 'Fixture.Direct')])
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_reserved_fat_header_flags_do_not_supply_candidate(self):
        for flag in (0x004, 0x020, 0x040, 0x080, 0x100, 0x200, 0x400, 0x800):
            with self.subTest(flag=hex(flag)), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'Fixture.dll'
                path.write_bytes(fat_fixture(0x3003 | flag))
                self.assertEqual(inspect_translate_calls(path), [])

    def test_extra_method_sections_still_require_separate_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Fixture.dll'
            path.write_bytes(fat_fixture(0x300b))
            self.assertEqual(inspect_translate_calls(path), [])


if __name__ == '__main__':
    unittest.main()
