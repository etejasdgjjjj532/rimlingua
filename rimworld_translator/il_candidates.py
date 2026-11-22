"""Bounded, non-executing IL evidence for direct Translate(string) references.

This is a conservative instruction reader, not a CLR verifier or dataflow engine.
Candidates are diagnostics only; a literal key supplies no English source text.
Opcode and header encodings follow ECMA-335, partitions II.25 and III.
"""
from __future__ import annotations

MAX_METHOD = 1024 * 1024
MAX_ASSEMBLY = 32 * 1024 * 1024


def decode_il(code: bytes):
    """(offset, opcode, operand) of every instruction and the set of branch targets; malformed bodies raise."""
    if len(code) > MAX_METHOD:
        raise ValueError('IL method exceeds inspection limit')
    # Operand widths are encoding facts, independently enumerated from ECMA-335.
    widths = {}
    for start, end in ((0x00, 0x0d), (0x14, 0x1e), (0x25, 0x26), (0x46, 0x6e),
                       (0x82, 0x8b), (0x90, 0xa2), (0xb3, 0xba), (0xd1, 0xdc)):
        widths.update(dict.fromkeys(range(start, end + 1), 0))
    widths.update(dict.fromkeys((0x2a, 0x76, 0x7a, 0x8e, 0xc3, 0xdf, 0xe0), 0))
    widths.update(dict.fromkeys((*range(0x0e, 0x14), 0x1f, *range(0x2b, 0x38), 0xde), 1))
    widths.update(dict.fromkeys((0x20, 0x22, 0x27, 0x28, 0x29, *range(0x38, 0x45),
                                *range(0x6f, 0x76), 0x79, *range(0x7b, 0x82),
                                0x8c, 0x8d, 0x8f, 0xa3, 0xa4, 0xa5, 0xc2, 0xc6, 0xd0, 0xdd), 4))
    widths.update({0x21: 8, 0x23: 8})
    widths.update(dict.fromkeys((0xfe00, *range(0xfe01, 0xfe06), 0xfe0f, 0xfe11,
                                0xfe13, 0xfe14, 0xfe17, 0xfe18, 0xfe1a, 0xfe1d, 0xfe1e), 0))
    widths.update(dict.fromkeys(range(0xfe09, 0xfe0f), 2))
    widths.update(dict.fromkeys((0xfe06, 0xfe07, 0xfe15, 0xfe16, 0xfe1c), 4))
    widths[0xfe12] = 1
    at, instructions, targets = 0, [], set()
    while at < len(code):
        offset = at
        opcode = code[at]
        at += 1
        if opcode == 0xfe:
            if at == len(code):
                raise ValueError('Truncated IL opcode')
            opcode = 0xfe00 | code[at]
            at += 1
        if opcode == 0x45:
            if at + 4 > len(code):
                raise ValueError('Truncated switch count')
            size = 4 + 4 * int.from_bytes(code[at:at + 4], 'little')
        elif opcode in widths:
            size = widths[opcode]
        else:
            raise ValueError('Unsupported IL opcode')
        if at + size > len(code):
            raise ValueError('Truncated IL operand')
        operand = code[at:at + size]
        at += size
        if opcode in (*range(0x2b, 0x45), 0xdd, 0xde):
            targets.add(at + int.from_bytes(operand, 'little', signed=True))
        elif opcode == 0x45:
            for index in range(4, size, 4):
                targets.add(at + int.from_bytes(operand[index:index + 4], 'little', signed=True))
        instructions.append((offset, opcode, int.from_bytes(operand, 'little')))
    boundaries = {item[0] for item in instructions}
    if not targets <= boundaries:
        raise ValueError('IL branch target is not an instruction')
    return instructions, targets


def direct_literal_calls(code: bytes, translate_tokens: set[int]):
    """Return (call offset, user-string token), rejecting malformed bodies."""
    instructions, targets = decode_il(code)
    calls, literal = [], None
    for index, (offset, opcode, token) in enumerate(instructions):
        # A branch entering after ldstr can bypass its stack value, including
        # when it enters a nop/break before the call. A branch to ldstr is safe.
        if offset in targets:
            literal = None
        if opcode == 0x72 and token >> 24 == 0x70:
            literal = token
        elif (opcode == 0xfe14 and index + 2 < len(instructions)
              and instructions[index + 1][1] == 0x28
              and instructions[index + 2][1] == 0x2a):
            # tail. has no stack transition, but only accept its direct
            # call/ret shape. Branch entry still clears literal evidence.
            continue
        elif opcode == 0x25:  # dup preserves the proven value at the stack top.
            continue
        elif opcode not in (0x00, 0x01):  # nop/break leave the evaluation stack unchanged.
            if opcode == 0x28 and token in translate_tokens and literal is not None:
                calls.append((offset, literal))
            literal = None
    return calls


LDFLD, LDSTR, CALL, CALLVIRT = 0x7b, 0x72, 0x28, 0x6f
LDFLDA, LDSFLD, LDSFLDA, LDTOKEN = 0x7c, 0x7e, 0x7f, 0xd0


def field_load_uses(code: bytes, compare_tokens: set[int], neutral_tokens: set[int]) -> dict[int, set[str]]:
    """How each field named in one method body is used: 'compare', 'neutral' or 'other', keyed by the field token.

    compare: the loaded value goes straight into a string equality call, alone or with one string literal
    (``x.f == "A"``, ``"A" == x.f``). neutral: straight into a null/empty check. Anything else, including a branch
    that enters the pattern, is another use. Address loads (ldflda, ldsflda), static loads and a field handle
    (ldtoken) can pass the value anywhere, so they are always another use. Tokens may be Field (0x04) or MemberRef
    (0x0a, a field of a generic or foreign type); the caller resolves them. This reads instruction order only.
    """
    instructions, targets = decode_il(code)
    uses = {}
    for index, (offset, opcode, token) in enumerate(instructions):
        if opcode in (LDFLDA, LDSFLD, LDSFLDA) or (opcode == LDTOKEN and token >> 24 in (0x04, 0x0a)):
            uses.setdefault(token, set()).add('other')
            continue
        if opcode != LDFLD:
            continue
        kind = 'other'
        following = instructions[index + 1:index + 3]
        calls = {CALL, CALLVIRT}
        if token >> 24 in (0x04, 0x0a) and following and following[0][0] not in targets:
            first = following[0]
            if first[1] in calls and first[2] in compare_tokens:
                kind = 'compare'
            elif first[1] in calls and first[2] in neutral_tokens:
                kind = 'neutral'
            elif (first[1] == LDSTR and len(following) == 2 and following[1][0] not in targets
                  and following[1][1] in calls and following[1][2] in compare_tokens):
                kind = 'compare'
        uses.setdefault(token, set()).add(kind)
    return uses


def _method_bodies(pe, md, check_cancel, sections=False):
    """(MethodDef index, row, IL body) of every IL method.

    Bodies with exception-handling sections are skipped unless ``sections``; then their code is still returned
    (the sections follow it) and an unreadable header yields a None body, so a caller can refuse to conclude.
    """
    for index, method in enumerate(md.MethodDef.rows if md.MethodDef else [], 1):
        check_cancel()
        if not method.Rva or method.struct.ImplFlags & 3:  # IL only, no native/runtime bodies.
            continue
        header = pe.get_data(method.Rva, 12)
        if not header:
            if sections:
                yield index, method, None
            continue
        if header[0] & 3 == 2:
            size, start = header[0] >> 2, 1
        elif len(header) == 12 and header[0] & 3 == 3:
            flags = int.from_bytes(header[:2], 'little')
            start = (flags >> 12) * 4
            if start < 12 or flags & 0x0fe4 or (flags & 8 and not sections):
                # Only FatFormat/InitLocals/MoreSects are understood.
                # EH/extra sections still need a separate verifier.
                if sections:
                    yield index, method, None
                continue
            size = int.from_bytes(header[4:8], 'little')
        else:
            if sections:
                yield index, method, None
            continue
        if size > MAX_METHOD:
            raise ValueError('IL method exceeds inspection limit')
        body = pe.get_data(method.Rva + start, size)
        if len(body) != size:
            raise ValueError('Truncated IL method body')
        yield index, method, body


def _blob(value) -> bytes:
    return bytes(getattr(value, 'value', value) or b'')


def _type_name(row) -> str:
    return f'{getattr(row, "TypeNamespace", "")}.{getattr(row, "TypeName", "")}'.strip('.')


def _member_owner(member, md):
    """``Namespace.Type`` a MemberRef field belongs to (a type reference or a generic instance), else None."""
    row = getattr(getattr(member, 'Class', None), 'row', None)
    if row is None:
        return None
    if hasattr(row, 'TypeName'):
        return _type_name(row)
    signature = _blob(getattr(row, 'Signature', None))
    if len(signature) >= 3 and signature[0] == 0x15 and signature[1] in (0x11, 0x12):  # GENERICINST class/valuetype
        from .schema import _compressed
        code, _end = _compressed(signature, 2)
        table = {0: getattr(md, 'TypeDef', None), 1: getattr(md, 'TypeRef', None)}.get(code & 3)
        rows = list(table.rows) if table else []
        if 0 < code >> 2 <= len(rows):
            return _type_name(rows[(code >> 2) - 1])
    return None


def field_evidence_from_metadata(pe, md, check_cancel=lambda: None) -> dict:
    """What one assembly says about string fields: declared ones, how each is read, and whether that is complete.

    ``uses`` maps ``Namespace.Type.field`` to the kinds of use ('compare', 'neutral', 'other'). A read through a
    MemberRef that cannot be resolved to a type goes to ``unresolved`` (field names only). ``complete`` is False
    when any method body could not be read, or a load names an unknown token: nothing may then be concluded.
    The result is plain JSON data so it can be cached per assembly and combined across a MOD's assemblies.
    """
    compare, neutral = set(), set()
    member_rows = list(md.MemberRef.rows) if md.MemberRef else []
    for index, member in enumerate(member_rows, 1):
        owner = getattr(getattr(member, 'Class', None), 'row', None)
        namespace, type_name = str(getattr(owner, 'TypeNamespace', '')), str(getattr(owner, 'TypeName', ''))
        name = str(member.Name)
        if namespace == 'System' and type_name == 'String':
            if name in {'op_Equality', 'op_Inequality', 'Equals'}:
                compare.add(0x0a000000 | index)
            elif name in {'IsNullOrEmpty', 'IsNullOrWhiteSpace'}:
                neutral.add(0x0a000000 | index)
        elif namespace == 'Verse' and type_name == 'GenText' and name == 'NullOrEmpty':
            neutral.add(0x0a000000 | index)
    typedefs = list(md.TypeDef.rows) if md.TypeDef else []
    fields = list(md.Field.rows) if md.Field else []
    names, declared = {}, []
    for i, row in enumerate(typedefs):
        start = row.struct.FieldList_Index
        end = typedefs[i + 1].struct.FieldList_Index if i + 1 < len(typedefs) else len(fields) + 1
        owner = _type_name(row)
        for field_index in range(max(start, 1), min(end, len(fields) + 1)):
            names[field_index] = f'{owner}.{fields[field_index - 1].Name}'
            if _blob(getattr(fields[field_index - 1], 'Signature', None))[1:2] == b'\x0e':  # FIELD of System.String
                declared.append(names[field_index])
    uses, unresolved, complete = {}, set(), True
    for _index, _method, body in _method_bodies(pe, md, check_cancel, sections=True):
        try:
            if body is None:
                raise ValueError('unreadable method body')
            found = field_load_uses(body, compare, neutral)
        except ValueError:
            # An unreadable body may read any field: nothing can be proven compare-only.
            complete = False
            continue
        for token, kinds in found.items():
            table, row_id = token >> 24, token & 0xffffff
            if table == 0x04 and row_id in names:
                uses.setdefault(names[row_id], set()).update(kinds)
            elif table == 0x0a and 0 < row_id <= len(member_rows):
                member = member_rows[row_id - 1]
                owner = _member_owner(member, md)
                if owner is None:
                    unresolved.add(str(member.Name))
                else:
                    uses.setdefault(f'{owner}.{member.Name}', set()).update(kinds)
            else:
                complete = False
    return {'declared': sorted(set(declared)), 'uses': {name: sorted(kinds) for name, kinds in sorted(uses.items())},
            'unresolved': sorted(unresolved), 'complete': complete}


def assembly_field_evidence(path, check_cancel=lambda: None) -> dict:
    """field_evidence_from_metadata for one assembly file (metadata and IL bytes only; nothing is executed)."""
    import dnfile
    from pefile import PEFormatError
    if path.stat().st_size > MAX_ASSEMBLY or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symbolic or oversized assembly excluded')
    pe = None
    try:
        pe = dnfile.dnPE(str(path))
        if not pe.net or not pe.net.mdtables:
            raise ValueError('CLR metadata unavailable')
        return field_evidence_from_metadata(pe, pe.net.mdtables, check_cancel)
    except (PEFormatError, AttributeError, IndexError, TypeError, UnicodeError) as exc:
        raise ValueError('CLR IL unavailable: ' + type(exc).__name__) from exc
    finally:
        if pe is not None:
            pe.close()


def compared_only_from_evidence(evidences) -> set[str]:
    """``Namespace.Type.field`` of string fields the MOD's assemblies, taken together, read only to compare.

    Positive evidence is required: the field is read, at least once in a comparison, and every read anywhere in the
    MOD (any assembly) is a comparison or null check. A field never read is NOT proven internal (a game or other
    assembly may show it), and neither is one read through an address, a MemberRef of unknown owner, or an assembly
    that could not be fully read. Reflection and other MODs' code remain unseen; the caller applies the result only
    to one-word values.
    """
    evidences = list(evidences)
    if not evidences or not all(item.get('complete') for item in evidences):
        return set()
    declared, uses, unresolved = set(), {}, set()
    for item in evidences:
        declared.update(item.get('declared', ()))
        unresolved.update(item.get('unresolved', ()))
        for name, kinds in item.get('uses', {}).items():
            uses.setdefault(name, set()).update(kinds)
    return {name for name in declared
            if 'compare' in uses.get(name, ()) and uses[name] <= {'compare', 'neutral'}
            and name.rsplit('.', 1)[-1] not in unresolved}


def inspect_translate_calls(path, check_cancel=lambda: None):
    """Read target MemberRefs and bounded method bodies using existing dnfile."""
    import dnfile
    from pefile import PEFormatError
    if path.stat().st_size > MAX_ASSEMBLY or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symbolic or oversized assembly excluded')
    pe = None
    try:
        pe = dnfile.dnPE(str(path))
        if not pe.net or not pe.net.mdtables:
            raise ValueError('CLR metadata unavailable')
        md = pe.net.mdtables
        tokens = set()
        for index, member in enumerate(md.MemberRef.rows if md.MemberRef else [], 1):
            check_cancel()
            if str(member.Name) != 'Translate':
                continue
            owner = member.Class.row
            if (str(getattr(owner, 'TypeNamespace', '')) != 'Verse'
                    or str(getattr(owner, 'TypeName', '')) != 'Translator'):
                continue
            scope = getattr(owner, 'ResolutionScope', None)
            scope_row = getattr(scope, 'row', None)
            if (type(scope_row).__name__ != 'AssemblyRefRow'
                    or str(getattr(scope_row, 'Name', '')) != 'Assembly-CSharp'):
                continue
            signature = bytes(getattr(getattr(member, 'Signature', None), 'value', b''))
            # DEFAULT static, one argument, string return or TaggedString value
            # return (compressed type token), followed by exactly one string.
            valid = signature == b'\x00\x01\x0e\x0e'
            if (len(signature) >= 5 and signature[:3] == b'\x00\x01\x11'
                    and signature[3] < 0xe0):
                # ECMA-335 II.23.2 permits 0, 10, or 110 length prefixes;
                # 111 cannot identify a valid compressed TypeDefOrRef token.
                from .schema import _compressed
                code, end = _compressed(signature, 3)
                rows = md.TypeRef.rows if code & 3 == 1 and md.TypeRef else []
                target = rows[(code >> 2) - 1] if 0 < code >> 2 <= len(rows) else None
                valid = (signature[end:] == b'\x0e' and target is not None
                         and str(target.TypeNamespace) == 'Verse' and str(target.TypeName) == 'TaggedString'
                         and type(getattr(getattr(target, 'ResolutionScope', None), 'row', None)).__name__ == 'AssemblyRefRow'
                         and str(getattr(getattr(target.ResolutionScope, 'row', None), 'Name', '')) == 'Assembly-CSharp')
            if valid:
                tokens.add(0x0a000000 | index)
        if not tokens:
            return []
        candidates = []
        for index, method, body in _method_bodies(pe, md, check_cancel):
            try:
                calls = direct_literal_calls(body, tokens)
            except ValueError:
                continue
            for offset, token in calls:
                string = pe.net.user_strings.get(token & 0xffffff)
                value = getattr(string, 'value', None)
                if isinstance(value, str) and value and len(value) <= 512 and all(ord(c) >= 32 for c in value):
                    candidates.append((index, str(method.Name), offset, value))
        return candidates
    except (PEFormatError, AttributeError, IndexError, TypeError, UnicodeError) as exc:
        raise ValueError('CLR IL unavailable: ' + type(exc).__name__) from exc
    finally:
        if pe is not None:
            pe.close()
