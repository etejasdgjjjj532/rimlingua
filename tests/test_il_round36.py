"""Stack-neutral debugging instructions preserve bounded IL evidence."""
import unittest

from rimworld_translator.il_candidates import direct_literal_calls


class ILRound36Tests(unittest.TestCase):
    def test_break_between_literal_and_translate_preserves_candidate(self):
        # ECMA-335 III.3.16: break (01) has no evaluation-stack effect.
        body = bytes.fromhex('7201000070 01 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(6, 0x70000001)])

    def test_mixed_nops_and_breaks_preserve_candidate(self):
        body = bytes.fromhex('7201000070 00 01 00 01 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(9, 0x70000001)])

    def test_branch_bypassing_literal_via_break_or_nop_has_no_candidate(self):
        # Entry into any neutral instruction or the call bypasses ldstr.
        for delta in (5, 6, 7, 8, 9):
            with self.subTest(delta=delta):
                body = bytes((0x2b, delta)) + bytes.fromhex('7201000070 00 01 00 01 280100000a 2a')
                self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])

    def test_branch_to_literal_before_break_keeps_candidate(self):
        body = bytes.fromhex('2b00 7201000070 01 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(8, 0x70000001)])

    def test_break_does_not_restore_literal_consumed_by_pop(self):
        body = bytes.fromhex('7201000070 26 01 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])


if __name__ == '__main__':
    unittest.main()
