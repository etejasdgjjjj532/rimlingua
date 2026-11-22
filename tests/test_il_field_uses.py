"""IL evidence that a string field is only ever compared (an internal value), never shown."""
import unittest

from rimworld_translator.il_candidates import field_load_uses

FIELD = 0x04000007
OTHER_FIELD = 0x04000008
EQUALS = 0x0A000001     # System.String.op_Equality
NULL_OR_EMPTY = 0x0A000002
SHOW = 0x0A000003       # any other call, e.g. a label setter or Translate
LITERAL = 0x70000010


def op(code, token=None):
    return bytes([code]) + (token.to_bytes(4, 'little') if token is not None else b'')


LDARG0 = op(0x02)
RET = op(0x2a)
POP = op(0x26)


def uses(*parts):
    return field_load_uses(b''.join(parts), {EQUALS}, {NULL_OR_EMPTY})


class FieldLoadUseTests(unittest.TestCase):
    def test_field_compared_with_a_literal(self):
        self.assertEqual(uses(LDARG0, op(0x7b, FIELD), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET),
                         {FIELD: {'compare'}})

    def test_literal_first_then_field(self):
        self.assertEqual(uses(op(0x72, LITERAL), LDARG0, op(0x7b, FIELD), op(0x28, EQUALS), POP, RET),
                         {FIELD: {'compare'}})

    def test_null_check_is_neutral(self):
        self.assertEqual(uses(LDARG0, op(0x7b, FIELD), op(0x28, NULL_OR_EMPTY), POP, RET), {FIELD: {'neutral'}})

    def test_field_passed_to_any_other_call_is_another_use(self):
        self.assertEqual(uses(LDARG0, op(0x7b, FIELD), op(0x28, SHOW), RET), {FIELD: {'other'}})

    def test_field_returned_or_stored_is_another_use(self):
        self.assertEqual(uses(LDARG0, op(0x7b, FIELD), RET), {FIELD: {'other'}})

    def test_two_fields_compared_with_each_other(self):
        found = uses(LDARG0, op(0x7b, FIELD), LDARG0, op(0x7b, OTHER_FIELD), op(0x28, EQUALS), POP, RET)
        # The first load is followed by another load, not by the comparison: conservatively another use.
        self.assertEqual(found, {FIELD: {'other'}, OTHER_FIELD: {'compare'}})

    def test_branch_into_the_pattern_is_another_use(self):
        # br.s lands on ldstr, so the value under the literal may not be the field.
        code = b''.join((bytes([0x2b, 0x06]), LDARG0, op(0x7b, FIELD), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))
        self.assertEqual(field_load_uses(code, {EQUALS}, {NULL_OR_EMPTY}), {FIELD: {'other'}})


if __name__ == '__main__':
    unittest.main()
