"""Reserved compressed-type prefixes cannot establish Translate evidence."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import dnfile

from rimworld_translator.il_candidates import inspect_translate_calls
from test_il_round34 import ASSEMBLY


class ILRound49Tests(unittest.TestCase):
    def inspect_with_return_token(self, malformed):
        # Keep real method bodies, member identity, and resolution scopes. Only
        # the return-type metadata is supplied in memory to isolate its decoder.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Fixture.dll'
            path.write_bytes(ASSEMBLY)
            before = hashlib.sha256(path.read_bytes()).digest()
            pe = dnfile.dnPE(str(path))
            try:
                md = pe.net.mdtables
                member = next(row for row in md.MemberRef.rows
                              if str(row.Name) == 'Translate'
                              and bytes(row.Signature.value) == b'\x00\x01\x0e\x0e')
                md.TypeRef.rows.append(SimpleNamespace(
                    TypeNamespace='Verse', TypeName='TaggedString',
                    ResolutionScope=member.Class.row.ResolutionScope))
                token = (len(md.TypeRef.rows) << 2) | 1
                self.assertLess(token, 0x80)
                encoded = b'\xe0\x00\x00' + bytes([token]) if malformed else bytes([token])
                member.Signature = SimpleNamespace(value=b'\x00\x01\x11' + encoded + b'\x0e')
                with patch('dnfile.dnPE', return_value=pe):
                    result = inspect_translate_calls(path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)
                return result
            finally:
                pe.close()

    def test_valid_tagged_return_preserves_direct_literal_candidate(self):
        self.assertEqual(self.inspect_with_return_token(False),
                         [(1, 'Direct', 5, 'Fixture.Direct')])

    def test_reserved_type_token_prefix_cannot_supply_candidate(self):
        self.assertEqual(self.inspect_with_return_token(True), [])
