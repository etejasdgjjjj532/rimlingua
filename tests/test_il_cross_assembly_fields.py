"""Compared-only field evidence is combined over every assembly of a MOD and needs positive proof.

The metadata is synthetic (plain objects shaped like dnfile rows); no assembly is executed or even loaded.
"""
import unittest
from types import SimpleNamespace as NS

from rimworld_translator.il_candidates import (
    compared_only_from_evidence, field_evidence_from_metadata, field_load_uses)


def op(code, token=None):
    return bytes([code]) + (token.to_bytes(4, 'little') if token is not None else b'')


LDARG0, POP, RET = op(0x02), op(0x26), op(0x2a)
LITERAL = 0x70000001


def type_ref(namespace, name):
    return NS(TypeNamespace=namespace, TypeName=name)


def member(name, owner_row, signature=b''):
    return NS(Name=name, Class=NS(row=owner_row), Signature=NS(value=signature))


def string_field(name):
    return NS(Name=name, Signature=NS(value=b'\x06\x0e'))


def int_field(name):
    return NS(Name=name, Signature=NS(value=b'\x06\x08'))


def build(types, members=(), bodies=()):
    """(pe, md) for types [(namespace, name, [fields])], extra MemberRefs and method bodies.

    MemberRef 1 is String.op_Equality (token 0x0a000001), MemberRef 2 String.IsNullOrEmpty; extra members follow
    from token 0x0a000003. Field rows are numbered in declaration order across the types, from 1.
    """
    string = type_ref('System', 'String')
    refs = [member('op_Equality', string), member('IsNullOrEmpty', string), *members]
    typedefs, fields = [], []
    for namespace, name, own in types:
        typedefs.append(NS(TypeNamespace=namespace, TypeName=name, struct=NS(FieldList_Index=len(fields) + 1)))
        fields.extend(own)
    methods, image = [], bytearray(0x1000 * (len(bodies) + 2))
    for index, body in enumerate(bodies, 1):
        rva = 0x1000 * index
        image[rva:rva + 1 + len(body)] = bytes([(len(body) << 2) | 2]) + body     # tiny header, then the IL
        methods.append(NS(Rva=rva, struct=NS(ImplFlags=0)))
    md = NS(MemberRef=NS(rows=refs), TypeDef=NS(rows=typedefs), TypeRef=NS(rows=[]), Field=NS(rows=fields),
            MethodDef=NS(rows=methods))
    pe = NS(get_data=lambda rva, size: bytes(image[rva:rva + size]))
    return pe, md


def evidence(types, members=(), bodies=()):
    return field_evidence_from_metadata(*build(types, members, bodies))


EQUALS = 0x0a000001
FIELD1 = 0x04000001            # the first declared field, Mod.Def.kind
SHOW = 0x0a000099              # any other call


def compare_body(field=FIELD1):
    return b''.join((LDARG0, op(0x7b, field), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))


def show_body(token):
    return b''.join((LDARG0, op(0x7b, token), op(0x28, SHOW), RET))


DEF = [('Mod', 'Def', [string_field('kind'), int_field('count')])]
KIND = 'Mod.Def.kind'


class CrossAssemblyFieldTests(unittest.TestCase):
    def test_compare_only_in_one_assembly_is_internal(self):
        core = evidence(DEF, bodies=[compare_body()])
        self.assertEqual(compared_only_from_evidence([core]), {KIND})

    def test_field_declared_in_core_but_shown_in_ui_stays_a_candidate(self):
        core = evidence(DEF, bodies=[compare_body()])
        ui_owner = type_ref('Mod', 'Def')
        ui = evidence([], members=[member('kind', ui_owner), member('Show', type_ref('Mod', 'Ui'))],
                      bodies=[show_body(0x0a000003)])
        self.assertEqual(ui['uses'], {KIND: ['other']})
        self.assertEqual(compared_only_from_evidence([core, ui]), set())
        self.assertEqual(compared_only_from_evidence([ui, core]), set())

    def test_compare_in_ui_and_declaration_in_core_is_internal(self):
        core = evidence(DEF)
        compare_in_ui = b''.join((LDARG0, op(0x7b, 0x0a000003), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))
        ui = evidence([], members=[member('kind', type_ref('Mod', 'Def'))], bodies=[compare_in_ui])
        self.assertEqual(compared_only_from_evidence([core, ui]), {KIND})

    def test_generic_base_class_read_through_a_memberref_is_resolved(self):
        types = [('Mod', 'Base`1', [string_field('kind')])]
        generic_owner = NS(Signature=NS(value=bytes([0x15, 0x12, (1 << 2) | 0, 0x01, 0x0e])))
        shown = evidence(types, members=[member('kind', generic_owner)], bodies=[show_body(0x0a000003)])
        self.assertEqual(shown['uses'], {'Mod.Base`1.kind': ['other']})
        self.assertEqual(compared_only_from_evidence([shown]), set())
        compared_body = b''.join((LDARG0, op(0x7b, 0x0a000003), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))
        compared = evidence(types, members=[member('kind', generic_owner)], bodies=[compared_body])
        self.assertEqual(compared_only_from_evidence([compared]), {'Mod.Base`1.kind'})

    def test_memberref_with_unknown_owner_counts_as_another_use_of_that_field_name(self):
        mystery = NS(Signature=NS(value=bytes([0x1d, 0x0e])))        # not a generic instance of a named type
        item = evidence(DEF, members=[member('kind', mystery)],
                        bodies=[compare_body(), show_body(0x0a000003)])
        self.assertEqual(item['unresolved'], ['kind'])
        self.assertEqual(compared_only_from_evidence([item]), set())

    def test_address_load_is_another_use(self):
        address = b''.join((LDARG0, op(0x7c, FIELD1), op(0x26), RET))
        item = evidence(DEF, bodies=[compare_body(), address])
        self.assertEqual(item['uses'], {KIND: ['compare', 'other']})
        self.assertEqual(compared_only_from_evidence([item]), set())

    def test_field_never_read_is_not_proven_internal(self):
        item = evidence(DEF, bodies=[RET])
        self.assertEqual(item['declared'], [KIND])
        self.assertEqual(compared_only_from_evidence([item]), set())

    def test_null_check_alone_is_not_enough(self):
        body = b''.join((LDARG0, op(0x7b, FIELD1), op(0x28, 0x0a000002), POP, RET))
        self.assertEqual(compared_only_from_evidence([evidence(DEF, bodies=[body])]), set())

    def test_compare_plus_null_check_is_internal(self):
        body = b''.join((LDARG0, op(0x7b, FIELD1), op(0x28, 0x0a000002), POP, RET))
        item = evidence(DEF, bodies=[compare_body(), body])
        self.assertEqual(compared_only_from_evidence([item]), {KIND})

    def test_non_string_fields_are_never_listed(self):
        body = b''.join((LDARG0, op(0x7b, 0x04000002), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))
        self.assertEqual(compared_only_from_evidence([evidence(DEF, bodies=[body])]), set())

    def test_one_unreadable_body_voids_every_conclusion(self):
        broken = bytes([0x20, 1, 0])                                  # ldc.i4 with a truncated operand
        item = evidence(DEF, bodies=[compare_body(), broken])
        self.assertFalse(item['complete'])
        self.assertEqual(compared_only_from_evidence([item]), set())
        good = evidence(DEF, bodies=[compare_body()])
        self.assertEqual(compared_only_from_evidence([good, item]), set())

    def test_no_assemblies_prove_nothing(self):
        self.assertEqual(compared_only_from_evidence([]), set())

    def test_evidence_is_plain_json(self):
        import json
        item = evidence(DEF, bodies=[compare_body()])
        self.assertEqual(json.loads(json.dumps(item)), item)


class FieldLoadTokenTests(unittest.TestCase):
    def test_memberref_field_load_is_tracked(self):
        code = b''.join((LDARG0, op(0x7b, 0x0a000005), op(0x72, LITERAL), op(0x28, EQUALS), POP, RET))
        self.assertEqual(field_load_uses(code, {EQUALS}, set()), {0x0a000005: {'compare'}})

    def test_ldflda_is_another_use(self):
        code = b''.join((LDARG0, op(0x7c, 0x04000007), POP, RET))
        self.assertEqual(field_load_uses(code, {EQUALS}, set()), {0x04000007: {'other'}})

    def test_ldflda_of_memberref_is_another_use(self):
        code = b''.join((LDARG0, op(0x7c, 0x0a000007), POP, RET))
        self.assertEqual(field_load_uses(code, {EQUALS}, set()), {0x0a000007: {'other'}})


if __name__ == '__main__':
    unittest.main()
