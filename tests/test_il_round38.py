"""Duplicating a proven IL literal retains evidence for the next direct call."""
import unittest

from rimworld_translator.il_candidates import direct_literal_calls


class ILRound38Tests(unittest.TestCase):
    def test_duplicate_literal_is_still_translate_argument(self):
        body = bytes.fromhex('7201000070 25 280100000a 26 26 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(6, 0x70000001)])

    def test_repeated_duplicates_and_neutral_instructions_keep_top_literal(self):
        body = bytes.fromhex('7201000070 25 00 01 25 280100000a 26 26 26 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(9, 0x70000001)])

    def test_branch_into_duplicate_or_call_cannot_supply_literal(self):
        for delta in (5, 6):
            with self.subTest(delta=delta):
                body = bytes((0x2b, delta)) + bytes.fromhex('7201000070 25 280100000a 26 26 2a')
                self.assertEqual(direct_literal_calls(body, {0x0a000001}), [])

    def test_branch_to_literal_before_duplicate_preserves_argument(self):
        body = bytes.fromhex('2b00 7201000070 25 280100000a 26 26 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(8, 0x70000001)])

    def test_new_literal_replaces_duplicated_top_argument(self):
        body = bytes.fromhex('7201000070 25 7202000070 280100000a 26 26 26 2a')
        self.assertEqual(direct_literal_calls(body, {0x0a000001}), [(11, 0x70000002)])

    def test_duplicate_does_not_restore_consumed_or_unproven_values(self):
        for body in ('7201000070 26 14 25 280100000a 26 26 2a',
                     '7201000070 25 26 280100000a 26 2a',
                     '7201000070 25 280200000a 280100000a 26 2a',
                     '14 25 280100000a 26 26 2a'):
            with self.subTest(body=body):
                self.assertEqual(direct_literal_calls(bytes.fromhex(body), {0x0a000001}), [])


if __name__ == '__main__':
    unittest.main()
