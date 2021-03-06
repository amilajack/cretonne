"""
Generate sources with instruction info.
"""
from __future__ import absolute_import
import srcgen
import constant_hash
from unique_table import UniqueTable, UniqueSeqTable
from cdsl import camel_case
from cdsl.operands import ImmediateKind
from cdsl.formats import InstructionFormat
from cdsl.instructions import Instruction

# The typing module is only required by mypy, and we don't use these imports
# outside type comments.
try:
    from typing import List, Sequence, Set, TYPE_CHECKING  # noqa
    if TYPE_CHECKING:
        from cdsl.isa import TargetISA  # noqa
        from cdsl.instructions import InstructionGroup  # noqa
        from cdsl.operands import Operand  # noqa
        from cdsl.typevar import TypeVar  # noqa

except ImportError:
    pass


def gen_formats(fmt):
    # type: (srcgen.Formatter) -> None
    """Generate an instruction format enumeration"""

    fmt.doc_comment('''
                    An instruction format

                    Every opcode has a corresponding instruction format
                    which is represented by both the `InstructionFormat`
                    and the `InstructionData` enums.
                    ''')
    fmt.line('#[derive(Copy, Clone, PartialEq, Eq, Debug)]')
    with fmt.indented('pub enum InstructionFormat {', '}'):
        for f in InstructionFormat.all_formats:
            fmt.doc_comment(str(f))
            fmt.line(f.name + ',')
    fmt.line()

    # Emit a From<InstructionData> which also serves to verify that
    # InstructionFormat and InstructionData are in sync.
    with fmt.indented(
            "impl<'a> From<&'a InstructionData> for InstructionFormat {", '}'):
        with fmt.indented(
                "fn from(inst: &'a InstructionData) -> InstructionFormat {",
                '}'):
            with fmt.indented('match *inst {', '}'):
                for f in InstructionFormat.all_formats:
                    fmt.line(('InstructionData::{} {{ .. }} => ' +
                              'InstructionFormat::{},')
                             .format(f.name, f.name))
    fmt.line()


def gen_arguments_method(fmt, is_mut):
    # type: (srcgen.Formatter, bool) -> None
    method = 'arguments'
    mut = ''
    rslice = 'ref_slice'
    as_slice = 'as_slice'
    if is_mut:
        method += '_mut'
        mut = 'mut '
        rslice += '_mut'
        as_slice = 'as_mut_slice'

    with fmt.indented(
            'pub fn {f}<\'a>(&\'a {m}self, '
            'pool: &\'a {m}ir::ValueListPool) -> '
            '&{m}[Value] {{'
            .format(f=method, m=mut), '}'):
        with fmt.indented('match *self {', '}'):
            for f in InstructionFormat.all_formats:
                n = 'InstructionData::' + f.name

                # Formats with a value list put all of their arguments in the
                # list. We don't split them up, just return it all as variable
                # arguments. (I expect the distinction to go away).
                if f.has_value_list:
                    arg = ''.format(mut)
                    fmt.line(
                        '{} {{ ref {}args, .. }} => args.{}(pool),'
                        .format(n, mut, as_slice))
                    continue

                # Fixed args.
                if f.num_value_operands == 0:
                    arg = '&{}[]'.format(mut)
                    capture = ''
                elif f.num_value_operands == 1:
                    capture = 'ref {}arg, '.format(mut)
                    arg = '{}(arg)'.format(rslice)
                else:
                    capture = 'ref {}args, '.format(mut)
                    arg = 'args'
                fmt.line(
                        '{} {{ {}.. }} => {},'
                        .format(n, capture, arg))


def gen_instruction_data_impl(fmt):
    # type: (srcgen.Formatter) -> None
    """
    Generate the boring parts of the InstructionData implementation.

    These methods in `impl InstructionData` can be generated automatically from
    the instruction formats:

    - `pub fn opcode(&self) -> Opcode`
    - `pub fn arguments(&self, &pool) -> &[Value]`
    - `pub fn arguments_mut(&mut self, &pool) -> &mut [Value]`
    - `pub fn take_value_list(&mut self) -> Option<ir::ValueList>`
    - `pub fn put_value_list(&mut self, args: ir::ValueList>`
    """

    # The `opcode` method simply reads the `opcode` members. This is really a
    # workaround for Rust's enum types missing shared members.
    with fmt.indented('impl InstructionData {', '}'):
        fmt.doc_comment('Get the opcode of this instruction.')
        with fmt.indented('pub fn opcode(&self) -> Opcode {', '}'):
            with fmt.indented('match *self {', '}'):
                for f in InstructionFormat.all_formats:
                    fmt.line(
                            'InstructionData::{} {{ opcode, .. }} => opcode,'
                            .format(f.name))
        fmt.line()

        fmt.doc_comment('Get the controlling type variable operand.')
        with fmt.indented(
                'pub fn typevar_operand(&self, pool: &ir::ValueListPool) -> '
                'Option<Value> {', '}'):
            with fmt.indented('match *self {', '}'):
                for f in InstructionFormat.all_formats:
                    n = 'InstructionData::' + f.name
                    if f.typevar_operand is None:
                        fmt.line(n + ' { .. } => None,')
                    elif f.has_value_list:
                        # We keep all arguments in a value list.
                        i = f.typevar_operand
                        fmt.line(
                                '{} {{ ref args, .. }} => '
                                'args.get({}, pool),'.format(n, i))
                    elif f.num_value_operands == 1:
                        # We have a single value operand called 'arg'.
                        fmt.line(n + ' { arg, .. } => Some(arg),')
                    else:
                        # We have multiple value operands and an array `args`.
                        # Which `args` index to use?
                        i = f.typevar_operand
                        fmt.line(
                                n +
                                ' {{ ref args, .. }} => Some(args[{}]),'
                                .format(i))
        fmt.line()

        fmt.doc_comment(
                """
                Get the value arguments to this instruction.
                """)
        gen_arguments_method(fmt, False)
        fmt.line()

        fmt.doc_comment(
                """
                Get mutable references to the value arguments to this
                instruction.
                """)
        gen_arguments_method(fmt, True)
        fmt.line()

        fmt.doc_comment(
                """
                Take out the value list with all the value arguments and return
                it.

                This leaves the value list in the instruction empty. Use
                `put_value_list` to put the value list back.
                """)
        with fmt.indented(
                'pub fn take_value_list(&mut self) -> Option<ir::ValueList> {',
                '}'):
            with fmt.indented('match *self {', '}'):
                for f in InstructionFormat.all_formats:
                    n = 'InstructionData::' + f.name
                    if f.has_value_list:
                        fmt.line(
                            n + ' { ref mut args, .. } => Some(args.take()),')
                fmt.line('_ => None,')
        fmt.line()

        fmt.doc_comment(
                """
                Put back a value list.

                After removing a value list with `take_value_list()`, use this
                method to put it back. It is required that this instruction has
                a format that accepts a value list, and that the existing value
                list is empty. This avoids leaking list pool memory.
                """)
        with fmt.indented(
                'pub fn put_value_list(&mut self, vlist: ir::ValueList) {',
                '}'):
            with fmt.indented('let args = match *self {', '};'):
                for f in InstructionFormat.all_formats:
                    n = 'InstructionData::' + f.name
                    if f.has_value_list:
                        fmt.line(n + ' { ref mut args, .. } => args,')
                fmt.line('_ => panic!("No value list: {:?}", self),')
            fmt.line('assert!(args.is_empty(), "Value list already in use");')
            fmt.line('*args = vlist;')


def collect_instr_groups(isas):
    # type: (Sequence[TargetISA]) -> List[InstructionGroup]
    seen = set()  # type: Set[InstructionGroup]
    groups = []
    for isa in isas:
        for g in isa.instruction_groups:
            if g not in seen:
                groups.append(g)
                seen.add(g)
    return groups


def gen_opcodes(groups, fmt):
    # type: (Sequence[InstructionGroup], srcgen.Formatter) -> Sequence[Instruction]  # noqa
    """
    Generate opcode enumerations.

    Return a list of all instructions.
    """

    fmt.doc_comment('''
                    An instruction opcode.

                    All instructions from all supported ISAs are present.
                    ''')
    fmt.line('#[derive(Copy, Clone, PartialEq, Eq, Debug, Hash)]')
    instrs = []

    # We explicitly set the discriminant of the first variant to 1, which
    # allows us to take advantage of the NonZero optimization, meaning that
    # wrapping enums can use the 0 discriminant instead of increasing the size
    # if the whole type, and so SIZEOF(Option<Opcode>>) == SIZEOF(Opcode)
    is_first_opcode = True
    with fmt.indented('pub enum Opcode {', '}'):
        for g in groups:
            for i in g.instructions:
                instrs.append(i)
                i.number = len(instrs)
                fmt.doc_comment('`{}`. ({})'.format(i, i.format.name))
                # Document polymorphism.
                if i.is_polymorphic:
                    if i.use_typevar_operand:
                        opnum = i.value_opnums[i.format.typevar_operand]
                        fmt.doc_comment(
                                'Type inferred from {}.'
                                .format(i.ins[opnum]))
                # Enum variant itself.
                if is_first_opcode:
                    fmt.line(i.camel_name + ' = 1,')
                    is_first_opcode = False
                else:
                    fmt.line(i.camel_name + ',')
    fmt.line()

    with fmt.indented('impl Opcode {', '}'):
        for attr in sorted(Instruction.ATTRIBS.keys()):
            fmt.doc_comment(Instruction.ATTRIBS[attr])
            with fmt.indented('pub fn {}(self) -> bool {{'
                              .format(attr), '}'):
                with fmt.indented('match self {', '}'):
                    for i in instrs:
                        if getattr(i, attr):
                            fmt.format(
                                    'Opcode::{} => true,',
                                    i.camel_name, i.name)

                    fmt.line('_ => false,')
            fmt.line()
    fmt.line()

    # Generate a private opcode_format table.
    with fmt.indented(
            'const OPCODE_FORMAT: [InstructionFormat; {}] = ['
            .format(len(instrs)),
            '];'):
        for i in instrs:
            fmt.format(
                    'InstructionFormat::{}, // {}',
                    i.format.name, i.name)
    fmt.line()

    # Generate a private opcode_name function.
    with fmt.indented('fn opcode_name(opc: Opcode) -> &\'static str {', '}'):
        with fmt.indented('match opc {', '}'):
            for i in instrs:
                fmt.format('Opcode::{} => "{}",', i.camel_name, i.name)
    fmt.line()

    # Generate an opcode hash table for looking up opcodes by name.
    hash_table = constant_hash.compute_quadratic(
            instrs,
            lambda i: constant_hash.simple_hash(i.name))
    with fmt.indented(
            'const OPCODE_HASH_TABLE: [Option<Opcode>; {}] = ['
            .format(len(hash_table)), '];'):
        for i in hash_table:
            if i is None:
                fmt.line('None,')
            else:
                fmt.format('Some(Opcode::{}),', i.camel_name)
    fmt.line()
    return instrs


def get_constraint(op, ctrl_typevar, type_sets):
    # type: (Operand, TypeVar, UniqueTable) -> str
    """
    Get the value type constraint for an SSA value operand, where
    `ctrl_typevar` is the controlling type variable.

    Each operand constraint is represented as a string, one of:

    - `Concrete(vt)`, where `vt` is a value type name.
    - `Free(idx)` where `idx` is an index into `type_sets`.
    - `Same`, `Lane`, `AsBool` for controlling typevar-derived constraints.
    """
    assert op.is_value()
    tv = op.typevar

    # A concrete value type.
    if tv.singleton_type():
        return 'Concrete({})'.format(tv.singleton_type().rust_name())

    if tv.free_typevar() is not ctrl_typevar:
        assert not tv.is_derived
        return 'Free({})'.format(type_sets.add(tv.type_set))

    if tv.is_derived:
        assert tv.base is ctrl_typevar, "Not derived from ctrl_typevar"
        return camel_case(tv.derived_func)

    assert tv is ctrl_typevar
    return 'Same'


# TypeSet indexes are encoded in 8 bits, with `0xff` reserved.
typeset_limit = 0xff


def gen_typesets_table(fmt, type_sets):
    # type: (srcgen.Formatter, UniqueTable) -> None
    """
    Generate the table of ValueTypeSets described by type_sets.
    """
    if len(type_sets.table) == 0:
        return
    fmt.comment('Table of value type sets.')
    assert len(type_sets.table) <= typeset_limit, "Too many type sets"
    with fmt.indented(
            'const TYPE_SETS: [ir::instructions::ValueTypeSet; {}] = ['
            .format(len(type_sets.table)), '];'):
        for ts in type_sets.table:
            with fmt.indented('ir::instructions::ValueTypeSet {', '},'):
                ts.emit_fields(fmt)


def gen_type_constraints(fmt, instrs):
    # type: (srcgen.Formatter, Sequence[Instruction]) -> None
    """
    Generate value type constraints for all instructions.

    - Emit a compact constant table of ValueTypeSet objects.
    - Emit a compact constant table of OperandConstraint objects.
    - Emit an opcode-indexed table of instruction constraints.

    """

    # Table of TypeSet instances.
    type_sets = UniqueTable()

    # Table of operand constraint sequences (as tuples). Each operand
    # constraint is represented as a string, one of:
    # - `Concrete(vt)`, where `vt` is a value type name.
    # - `Free(idx)` where `idx` isan index into `type_sets`.
    # - `Same`, `Lane`, `AsBool` for controlling typevar-derived constraints.
    operand_seqs = UniqueSeqTable()

    # Preload table with constraints for typical binops.
    operand_seqs.add(['Same'] * 3)

    fmt.comment('Table of opcode constraints.')
    with fmt.indented(
            'const OPCODE_CONSTRAINTS: [OpcodeConstraints; {}] = ['
            .format(len(instrs)), '];'):
        for i in instrs:
            # Collect constraints for the value results, not including
            # `variable_args` results which are always special cased.
            constraints = list()
            ctrl_typevar = None
            ctrl_typeset = typeset_limit
            if i.is_polymorphic:
                ctrl_typevar = i.ctrl_typevar
                ctrl_typeset = type_sets.add(ctrl_typevar.type_set)
            for idx in i.value_results:
                constraints.append(
                        get_constraint(i.outs[idx], ctrl_typevar, type_sets))
            for opnum in i.value_opnums:
                constraints.append(
                        get_constraint(i.ins[opnum], ctrl_typevar, type_sets))
            offset = operand_seqs.add(constraints)
            fixed_results = len(i.value_results)
            fixed_values = len(i.value_opnums)
            # Can the controlling type variable be inferred from the designated
            # operand?
            use_typevar_operand = i.is_polymorphic and i.use_typevar_operand
            # Can the controlling type variable be inferred from the result?
            use_result = (fixed_results > 0 and
                          i.outs[i.value_results[0]].typevar == ctrl_typevar)
            # Are we required to use the designated operand instead of the
            # result?
            requires_typevar_operand = use_typevar_operand and not use_result
            fmt.comment(
                    '{}: fixed_results={}, use_typevar_operand={}, '
                    'requires_typevar_operand={}, fixed_values={}'
                    .format(i.camel_name, fixed_results, use_typevar_operand,
                            requires_typevar_operand, fixed_values))
            fmt.comment('Constraints={}'.format(constraints))
            if i.is_polymorphic:
                fmt.comment(
                        'Polymorphic over {}'.format(ctrl_typevar.type_set))
            # Compute the bit field encoding, c.f. instructions.rs.
            assert fixed_results < 8, "Bit field encoding too tight"
            flags = fixed_results
            if use_typevar_operand:
                flags |= 8
            if requires_typevar_operand:
                flags |= 0x10
            assert fixed_values < 8, "Bit field encoding too tight"
            flags |= fixed_values << 5

            with fmt.indented('OpcodeConstraints {', '},'):
                fmt.line('flags: {:#04x},'.format(flags))
                fmt.line('typeset_offset: {},'.format(ctrl_typeset))
                fmt.line('constraint_offset: {},'.format(offset))
    fmt.line()

    gen_typesets_table(fmt, type_sets)
    fmt.line()

    fmt.comment('Table of operand constraint sequences.')
    with fmt.indented(
            'const OPERAND_CONSTRAINTS: [OperandConstraint; {}] = ['
            .format(len(operand_seqs.table)), '];'):
        for c in operand_seqs.table:
            fmt.line('OperandConstraint::{},'.format(c))


def gen_format_constructor(iform, fmt):
    # type: (InstructionFormat, srcgen.Formatter) -> None
    """
    Emit a method for creating and inserting an `iform` instruction, where
    `iform` is an instruction format.

    All instruction formats take an `opcode` argument and a `ctrl_typevar`
    argument for deducing the result types.
    """

    # Construct method arguments.
    args = ['self', 'opcode: Opcode', 'ctrl_typevar: Type']

    # Normal operand arguments. Start with the immediate operands.
    for f in iform.imm_fields:
        args.append('{}: {}'.format(f.member, f.kind.rust_type))
    # Then the value operands.
    if iform.has_value_list:
        # Take all value arguments as a finished value list. The value lists
        # are created by the individual instruction constructors.
        args.append('args: ir::ValueList')
    else:
        # Take a fixed number of value operands.
        for i in range(iform.num_value_operands):
            args.append('arg{}: Value'.format(i))

    proto = '{}({})'.format(iform.name, ', '.join(args))
    proto += " -> (Inst, &'f mut ir::DataFlowGraph)"

    fmt.doc_comment(str(iform))
    fmt.line('#[allow(non_snake_case)]')
    with fmt.indented('fn {} {{'.format(proto), '}'):
        # Generate the instruction data.
        with fmt.indented(
                'let data = ir::InstructionData::{} {{'.format(iform.name),
                '};'):
            fmt.line('opcode,')
            gen_member_inits(iform, fmt)

        fmt.line('self.build(data, ctrl_typevar)')


def gen_member_inits(iform, fmt):
    # type: (InstructionFormat, srcgen.Formatter) -> None
    """
    Emit member initializers for an `iform` instruction.
    """

    # Immediate operands.
    # We have local variables with the same names as the members.
    for f in iform.imm_fields:
        fmt.line('{}: {},'.format(f.member, f.member))

    # Value operands.
    if iform.has_value_list:
        fmt.line('args,')
    elif iform.num_value_operands == 1:
        fmt.line('arg: arg0,')
    elif iform.num_value_operands > 1:
        args = ('arg{}'.format(i) for i in range(iform.num_value_operands))
        fmt.line('args: [{}],'.format(', '.join(args)))


def gen_inst_builder(inst, fmt):
    # type: (Instruction, srcgen.Formatter) -> None
    """
    Emit a method for generating the instruction `inst`.

    The method will create and insert an instruction, then return the result
    values, or the instruction reference itself for instructions that don't
    have results.
    """

    # Construct method arguments.
    if inst.format.has_value_list:
        args = ['mut self']
    else:
        args = ['self']

    # The controlling type variable will be inferred from the input values if
    # possible. Otherwise, it is the first method argument.
    if inst.is_polymorphic and not inst.use_typevar_operand:
        args.append('{}: ir::Type'.format(inst.ctrl_typevar.name))

    tmpl_types = list()  # type: List[str]
    into_args = list()  # type: List[str]
    for op in inst.ins:
        if isinstance(op.kind, ImmediateKind):
            t = 'T{}{}'.format(1 + len(tmpl_types), op.kind.name)
            tmpl_types.append('{}: Into<{}>'.format(t, op.kind.rust_type))
            into_args.append(op.name)
        else:
            t = op.kind.rust_type
        args.append('{}: {}'.format(op.name, t))

    # Return the inst reference for result-less instructions.
    if len(inst.value_results) == 0:
        rtype = 'Inst'
    elif len(inst.value_results) == 1:
        rtype = 'Value'
    else:
        rvals = ', '.join(len(inst.value_results) * ['Value'])
        rtype = '({})'.format(rvals)

    if len(tmpl_types) > 0:
        tmpl = '<{}>'.format(', '.join(tmpl_types))
    else:
        tmpl = ''
    proto = '{}{}({}) -> {}'.format(
            inst.snake_name(), tmpl,  ', '.join(args), rtype)

    fmt.doc_comment('`{}`\n\n{}'.format(inst, inst.blurb()))
    fmt.line('#[allow(non_snake_case)]')
    with fmt.indented('fn {} {{'.format(proto), '}'):
        # Convert all of the `Into<>` arguments.
        for arg in into_args:
            fmt.line('let {} = {}.into();'.format(arg, arg))

        # Arguments for instruction constructor.
        args = ['Opcode::' + inst.camel_name]

        if inst.is_polymorphic and not inst.use_typevar_operand:
            # This was an explicit method argument.
            args.append(inst.ctrl_typevar.name)
        elif not inst.is_polymorphic:
            # No controlling type variable needed.
            args.append('types::VOID')
        else:
            assert inst.is_polymorphic and inst.use_typevar_operand
            # Infer the controlling type variable from the input operands.
            opnum = inst.value_opnums[inst.format.typevar_operand]
            fmt.line(
                    'let ctrl_typevar = self.data_flow_graph().value_type({});'
                    .format(inst.ins[opnum].name))
            # The format constructor will resolve the result types from the
            # type var.
            args.append('ctrl_typevar')

        # Now add all of the immediate operands to the constructor arguments.
        for opnum in inst.imm_opnums:
            args.append(inst.ins[opnum].name)

        # Finally, the value operands.
        if inst.format.has_value_list:
            # We need to build a value list with all the arguments.
            fmt.line('let mut vlist = ir::ValueList::default();')
            args.append('vlist')
            with fmt.indented('{', '}'):
                fmt.line(
                        'let pool = '
                        '&mut self.data_flow_graph_mut().value_lists;')
                for op in inst.ins:
                    if op.is_value():
                        fmt.line('vlist.push({}, pool);'.format(op.name))
                    elif op.is_varargs():
                        fmt.line(
                            'vlist.extend({}.iter().cloned(), pool);'
                            .format(op.name))
        else:
            # With no value list, we're guaranteed to just have a set of fixed
            # value operands.
            for opnum in inst.value_opnums:
                args.append(inst.ins[opnum].name)

        # Call to the format constructor,
        fcall = 'self.{}({})'.format(inst.format.name, ', '.join(args))

        if len(inst.value_results) == 0:
            fmt.line(fcall + '.0')
            return

        fmt.line('let (inst, dfg) = {};'.format(fcall))

        if len(inst.value_results) == 1:
            fmt.line('dfg.first_result(inst)')
            return

        fmt.format(
            'let results = &dfg.inst_results(inst)[0..{}];',
            len(inst.value_results))
        fmt.format('({})', ', '.join(
            'results[{}]'.format(i) for i in range(len(inst.value_results))))


def gen_builder(insts, fmt):
    # type: (Sequence[Instruction], srcgen.Formatter) -> None
    """
    Generate a Builder trait with methods for all instructions.
    """
    fmt.doc_comment("""
            Convenience methods for building instructions.

            The `InstrBuilder` trait has one method per instruction opcode for
            conveniently constructing the instruction with minimum arguments.
            Polymorphic instructions infer their result types from the input
            arguments when possible. In some cases, an explicit `ctrl_typevar`
            argument is required.

            The opcode methods return the new instruction's result values, or
            the `Inst` itself for instructions that don't have any results.

            There is also a method per instruction format. These methods all
            return an `Inst`.
            """)
    with fmt.indented(
            "pub trait InstBuilder<'f>: InstBuilderBase<'f> {",  '}'):
        for inst in insts:
            gen_inst_builder(inst, fmt)
        for f in InstructionFormat.all_formats:
            gen_format_constructor(f, fmt)


def generate(isas, out_dir):
    # type: (Sequence[TargetISA], str) -> None
    groups = collect_instr_groups(isas)

    # opcodes.rs
    fmt = srcgen.Formatter()
    gen_formats(fmt)
    gen_instruction_data_impl(fmt)
    fmt.line()
    instrs = gen_opcodes(groups, fmt)
    gen_type_constraints(fmt, instrs)
    fmt.update_file('opcodes.rs', out_dir)

    # builder.rs
    fmt = srcgen.Formatter()
    gen_builder(instrs, fmt)
    fmt.update_file('builder.rs', out_dir)
