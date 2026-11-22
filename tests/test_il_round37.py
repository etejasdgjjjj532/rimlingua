"""Tail-call prefixes preserve only structurally supported direct IL evidence."""
import unittest

from rimworld_translator.il_candidates import direct_literal_calls


class ILRound37Tests(unittest.TestCase):
    def test_tail_call_translate_ret_keeps_literal(self):
        body = bytes.fromhex('7201000070 fe14 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(7, 0x70000001)])

    def test_neutral_instructions_before_tail_preserve_literal(self):
        body = bytes.fromhex('7201000070 000100 fe14 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(10, 0x70000001)])

    def test_branch_to_literal_before_tail_keeps_candidate(self):
        body = bytes.fromhex('2b00 7201000070 fe14 280100000a 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(9, 0x70000001)])

    def test_branch_into_tail_or_call_cannot_supply_literal(self):
        for delta in (5, 7):
            with self.subTest(delta=delta):
                body = bytes((0x2b, delta)) + bytes.fromhex('7201000070 fe14 280100000a 2a')
                self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])

    def test_tail_requires_adjacent_direct_call_and_ret(self):
        for suffix in ('fe14 00 280100000a 2a',
                       'fe14 280100000a 00 2a',
                       'fe14 280100000a',
                       'fe14 6f0100000a 2a',
                       'fe14 290100000a 2a'):
            with self.subTest(suffix=suffix):
                self.assertEqual(direct_literal_calls(bytes.fromhex('7201000070 ' + suffix), {0x0a000001}), [])

    def test_tail_does_not_restore_consumed_or_wrong_target_literal(self):
        for body in ('7201000070 26 fe14 280100000a 2a',
                     '7201000070 fe14 280200000a 2a'):
            with self.subTest(body=body):
                self.assertEqual(direct_literal_calls(bytes.fromhex(body), {0x0a000001}), [])


if __name__ == '__main__':
    unittest.main()
