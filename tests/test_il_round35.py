"""No-op IL instructions preserve literal evidence without bypassing branches."""
import unittest

from rimworld_translator.il_candidates import direct_literal_calls


class ILRound35Tests(unittest.TestCase):
    def test_nops_between_literal_and_translate_preserve_candidate(self):
        # ECMA-335 nop (0x00) has no stack effect. These literal instruction
        # encodings place the Translate call at offset 7 after two no-ops.
        body = bytes.fromhex('7201000070 00 00 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(7, 0x70000001)])

    def test_branch_entering_nop_chain_cannot_supply_literal_evidence(self):
        # Branch targets are respectively the first nop, second nop, and call;
        # each can bypass ldstr and therefore invalidates this candidate.
        for delta in (5, 6, 7):
            with self.subTest(delta=delta):
                body = bytes((0x2b, delta)) + bytes.fromhex('7201000070 00 00 280100000a 2a')
                self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])

    def test_branch_entering_literal_keeps_nop_chain_candidate(self):
        body = bytes.fromhex('2b00 7201000070 00 00 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(9, 0x70000001)])

    def test_stack_changing_instruction_between_literal_and_call_is_not_supported(self):
        body = bytes.fromhex('7201000070 26 00 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])
