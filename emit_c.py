#!/usr/bin/env python3
"""Emit compilable C for one ZDL audio function.

Registers are represented by a union so integer pointer arithmetic and float
values share the same 32-bit storage, like the C674x register file.

Usage:
    python emit_c.py EFFECT.ZDL -o EFFECT.c --func Fx_...
"""
import re
import sys
import tempfile
from pathlib import Path

import zdl2pseudo as z

HERE = Path(__file__).resolve().parent

FUNC_RANGE = None
LABEL_PREFIX = ""
REG = re.compile(r"^[AB]\d+$")
MEM = re.compile(r"^\*(\+\+|[+-])?([AB]\d+)(--|\+\+)?(?:\[([AB]\d+|-?\d+)\]|\(([AB]\d+|-?\d+)\))?$")


def c_ident(name):
    """Turn a disassembler symbol into a valid C identifier."""
    name = name.strip().split(".")[-1]
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = "_" + name
    return name or "_unknown"


PRELUDE = r"""typedef union { unsigned long long u; double d; } dbl_t;
#pragma CODE_SECTION(sat32, ".audio")
#pragma CODE_SECTION(sat_add32, ".audio")
#pragma CODE_SECTION(sat_sub32, ".audio")
#pragma CODE_SECTION(sat_shl32, ".audio")
#pragma CODE_SECTION(abs32, ".audio")
#pragma CODE_SECTION(absf32, ".audio")
#pragma CODE_SECTION(dbl_from, ".audio")
#pragma CODE_SECTION(dbl_to, ".audio")
#pragma CODE_SECTION(dbl_abs, ".audio")
static unsigned int sat32(long long x) {
  if (x > 2147483647LL) return 0x7FFFFFFFu;
  if (x < -2147483648LL) return 0x80000000u;
  return (unsigned int)(int)x;
}
static unsigned int sat_add32(unsigned int a, unsigned int b) {
  return sat32((long long)(int)a + (int)b);
}
static unsigned int sat_sub32(unsigned int a, unsigned int b) {
  return sat32((long long)(int)a - (int)b);
}
static unsigned int sat_shl32(unsigned int a, unsigned int n) {
  unsigned int lost;
  if (n == 0) return a;
  if (n >= 32) return (a & 0x80000000u) ? 0x80000000u : 0x7FFFFFFFu;
  lost = a >> (32 - n);
  if (a & 0x80000000u) {
    if (lost != 0xFFFFFFFFu) return 0x80000000u;
  } else if (lost != 0) {
    return 0x7FFFFFFFu;
  }
  return a << n;
}
static unsigned int abs32(unsigned int a) {
  return sat32(-(long long)(int)a < 0 ? -(long long)(int)a : (long long)(int)a);
}
static float absf32(float x) { return x < 0.0f ? -x : x; }
static double dbl_from(unsigned int hi, unsigned int lo) {
  dbl_t x; x.u = ((unsigned long long)hi << 32) | lo; return x.d;
}
static void dbl_to(double x, unsigned int *hi, unsigned int *lo) {
  dbl_t y; y.d = x; *hi = (unsigned int)(y.u >> 32); *lo = (unsigned int)y.u;
}
static double dbl_abs(double x) { return x < 0.0 ? -x : x; }
"""


def v(x):
    x = x.strip()
    return f"{x}.u" if REG.match(x) else x


def fv(x):
    x = x.strip()
    return f"{x}.f" if REG.match(x) else x


def mem(s):
    """Return base, byte offset, action: none, pre_inc, pre_dec, post_inc."""
    s = s.strip()
    m = MEM.match(s)
    if not m:
        raise ValueError("unsupported memory operand: %s" % s)
    pre, base, post, idx, paren = m.groups()
    if idx is not None and REG.match(idx):
        off = f"{idx}.u * 4"
    elif idx is not None:
        off = int(idx) * 4
    elif paren is not None:
        off = f"{paren}.u" if REG.match(paren) else int(paren)
    else:
        off = 0
    if pre == "-":
        off = -off if isinstance(off, int) else "-(%s)" % off
    if pre == "++":
        action = "pre_inc"
    elif post == "--":
        action = "pre_dec"
    elif post == "++":
        action = "post_inc"
    else:
        action = "none"
    return base, off, action


def off_add(off, n):
    return off + n if isinstance(off, int) else "(%s) + %d" % (off, n)


def mem_read(base, off, action):
    out = []
    if action == "pre_inc":
        out.append("%s += %s;" % (v(base), off))
    elif action == "pre_dec":
        out.append("%s -= %s;" % (v(base), off))
    out.append("MEM32(%s, %s)" % (v(base), off))
    if action == "post_inc":
        out.append("%s += %s;" % (v(base), off))
    return out


def mem_write(base, off, action, value):
    out = []
    if action == "pre_inc":
        out.append("%s += %s;" % (v(base), off))
    elif action == "pre_dec":
        out.append("%s -= %s;" % (v(base), off))
    out.append("MEM32(%s, %s) = %s;" % (v(base), off, value))
    if action == "post_inc":
        out.append("%s += %s;" % (v(base), off))
    return out


def regnum(s):
    m = re.match(r"^([AB])(\d+)$", s.strip())
    return (m.group(1), int(m.group(2))) if m else None


def mvd_copy(src, dst):
    s, d = regnum(src), regnum(dst)
    if not s or not d:
        return []
    if s[1] + 1 > 31 or d[1] + 1 > 31:
        return [f"{d[0]}{d[1]}.u = {s[0]}{s[1]}.u;"]
    return [f"{d[0]}{d[1]}.u = {s[0]}{s[1]}.u;",
            f"{d[0]}{d[1] + 1}.u = {s[0]}{s[1] + 1}.u;"]


def pred(ins):
    p = ins.predicate.strip()
    if not p:
        return ""
    if p.startswith("!"):
        return "if (!%s) " % v(p[1:])
    return "if (%s) " % v(p)


def label_for(addr):
    return "L_%s_%08X" % (LABEL_PREFIX, addr)


def branch_addr(s):
    m = re.search(r"PC[+-]\d+\s*=\s*(0x)?([0-9A-Fa-f]+)", s)
    return int(m.group(2), 16) if m else None


def emit_insn(ins):
    op = ins.op.split(".")[0]
    a = [x.strip() for x in ins.args.split(",")]
    p = pred(ins)
    if op.endswith(":") or op.startswith("$C$RL"):
        return ["%s:" % label_for(ins.addr)]
    if op in ("NOP", "SPKERNEL", "SPLOOPD", "SPMASK", "MVC",
              "DPSP", "DINT", "RINT", "ADDKPC", ".fphead") or op.startswith(".fphead"):
        return []
    if op == "MV":
        return [f"{p}{v(a[1])} = {v(a[0])};"]
    if op == "MVK":
        return [f"{p}{v(a[1])} = {a[0]};"]
    if op == "MVKH":
        return [f"{p}{v(a[1])} = ({v(a[1])} & 0xFFFFu) | {a[0]};"]
    if op == "ADD":
        return [f"{p}{v(a[2])} = {v(a[0])} + {v(a[1])};"]
    if op == "ADDK":
        return [f"{p}{v(a[1])} += {a[0]};"]
    if op == "ADDAW":
        return [f"{p}{v(a[2])} = {v(a[0])} + ({v(a[1])} << 2);"]
    if op == "ADDAD":
        return [f"{p}{v(a[2])} = {v(a[0])} + ({v(a[1])} << 1);"]
    if op == "SUB":
        return [f"{p}{v(a[2])} = {v(a[0])} - {v(a[1])};"]
    if op == "SHL":
        return [f"{p}{v(a[2])} = {v(a[0])} << {v(a[1])};"]
    if op == "SET":
        start, end = int(a[1], 0), int(a[2], 0)
        mask = ((1 << (end - start + 1)) - 1) << start
        return [f"{p}{v(a[3])} = {v(a[0])} | 0x{mask:08X}u;"]
    if op == "MPYSPDP":
        return []
    if op in ("MPYSP", "ADDSP", "SUBSP"):
        sym = {"MPYSP": "*", "ADDSP": "+", "SUBSP": "-"}[op]
        return [f"{p}{a[-1]}.f = {fv(a[0])} {sym} {fv(a[1])};"]
    if op in ("CMPLTSP", "CMPGTSP"):
        sym = "<" if op == "CMPLTSP" else ">"
        return [f"{p}{v(a[2])} = ({fv(a[0])} {sym} {fv(a[1])});"]
    if op in ("CMPLTU", "CMPGTU", "CMPGT", "CMPLT"):
        sym = {"CMPLTU": "<", "CMPGTU": ">", "CMPGT": ">", "CMPLT": "<"}[op]
        return [f"{p}{v(a[2])} = ({v(a[0])} {sym} {v(a[1])});"]
    if op in ("LDW", "LDDW", "LDNDW"):
        base, off, action = mem(a[0])
        dst = a[1]
        if op == "LDW":
            out = []
            if action == "pre_inc":
                out.append("%s += %s;" % (v(base), off))
            elif action == "pre_dec":
                out.append("%s -= %s;" % (v(base), off))
            out.append("%s%s = MEM32(%s, %s);" % (p, v(dst), v(base), off))
            if action == "post_inc":
                out.append("%s += %s;" % (v(base), off))
            return out
        hi, lo = dst.split(":")
        step = off_add(off, 8)
        out = []
        if action == "pre_inc":
            out.append("%s += %s;" % (v(base), step))
        elif action == "pre_dec":
            out.append("%s -= %s;" % (v(base), step))
        out.append("%s%s = MEM32(%s, %s);" % (p, v(lo), v(base), off))
        out.append("%s%s = MEM32(%s, %s);" % (p, v(hi), v(base), off_add(off, 4)))
        if action == "post_inc":
            out.append("%s += %s;" % (v(base), step))
        return out
    if op in ("STW", "STDW", "STNDW"):
        base, off, action = mem(a[1])
        if op == "STW":
            out = []
            if action == "pre_inc":
                out.append(p + "%s += %s;" % (v(base), off))
            elif action == "pre_dec":
                out.append(p + "%s -= %s;" % (v(base), off))
            out.append("%sMEM32(%s, %s) = %s;" % (p, v(base), off, v(a[0])))
            if action == "post_inc":
                out.append(p + "%s += %s;" % (v(base), off))
            return out
        hi, lo = a[0].split(":")
        step = off_add(off, 8)
        out = []
        if action == "pre_inc":
            out.append("%s += %s;" % (v(base), step))
        elif action == "pre_dec":
            out.append("%s -= %s;" % (v(base), step))
        out.append("%sMEM32(%s, %s) = %s;" % (p, v(base), off, v(lo)))
        out.append("%sMEM32(%s, %s) = %s;" % (p, v(base), off_add(off, 4), v(hi)))
        if action == "post_inc":
            out.append("%s += %s;" % (v(base), step))
        return out
    if op == "BDEC":
        addr = branch_addr(a[0])
        return [f"{p}if (--{v(a[1])} != 0) goto {label_for(addr)};"]
    if op in ("B", "BNOP"):
        addr = branch_addr(ins.args)
        if addr:
            if FUNC_RANGE and not (FUNC_RANGE[0] <= addr < FUNC_RANGE[1]):
                name = a[0].split()[0]
                if name.startswith(".") or name.startswith("$"):
                    parts = [x for x in re.split(r"[.$]", name) if x]
                    name = parts[-1]
                if re.match(r"^[A-Za-z_]\w*$", name):
                    return [f"{p}{name}(ctx);", "return;"]
            return [f"{p}goto {label_for(addr)};"]
        name = a[0].split()[0]
        if REG.match(name):
            return ["return;"]
        return [f"{p}{c_ident(name)}(ctx);", "return;"]
    if op == "CALLP":
        name = a[0].split()[0]
        return [f"{p}{c_ident(name)}(ctx);"]

    if op == "SMPY32":
        return [f"{p}{v(a[-1])} = sat32((long long)(int){v(a[0])} * (int){v(a[1])});"]
    if op in ("SADD", "SSUB"):
        fn = "sat_add32" if op == "SADD" else "sat_sub32"
        return [f"{p}{v(a[-1])} = {fn}({v(a[0])}, {v(a[1])});"]
    if op == "SAT":
        src = a[0].split(":")[1] if ":" in a[0] else a[0]
        return [f"{p}{v(a[-1])} = sat32((int){v(src)});"]
    if op == "ABS":
        return [f"{p}{v(a[-1])} = abs32({v(a[0])});"]
    if op in ("SHR", "SHRU"):
        sh = v(a[1])
        expr = (f"(int){v(a[0])} >> {sh}" if op == "SHR"
                else f"{v(a[0])} >> {sh}")
        return [f"{p}{v(a[-1])} = (unsigned int)({expr});"]
    if op == "SSHL":
        return [f"{p}{v(a[-1])} = sat_shl32({v(a[0])}, {v(a[1])});"]
    if op in ("AND", "OR", "XOR"):
        sym = {"AND": "&", "OR": "|", "XOR": "^"}[op]
        return [f"{p}{v(a[-1])} = {v(a[0])} {sym} {v(a[1])};"]
    if op == "NEG":
        return [f"{p}{v(a[-1])} = sat32(-(long long)(int){v(a[0])});"]
    if op == "ROTL":
        n = int(a[1], 0) & 31
        if n == 0:
            return [f"{p}{v(a[-1])} = {v(a[0])};"]
        return [f"{p}{v(a[-1])} = ({v(a[0])} << {n}) | ({v(a[0])} >> {32 - n});"]
    if op == "EXTU":
        start, width = int(a[1], 0), int(a[2], 0)
        mask = "0xFFFFFFFFu" if width >= 32 else "((1u << %d) - 1u)" % width
        return [f"{p}{v(a[-1])} = ({v(a[0])} >> {start}) & {mask};"]
    if op == "INTSP":
        return [f"{p}{fv(a[-1])} = (float)(int){v(a[0])};"]
    if op == "INTSPU":
        return [f"{p}{fv(a[-1])} = (float){v(a[0])};"]
    if op == "SPTRUNC":
        return [f"{p}{v(a[-1])} = (unsigned int)(int){fv(a[0])};"]
    if op == "ABSSP":
        return [f"{p}{fv(a[-1])} = absf32({fv(a[0])});"]
    if op in ("CMPEQSP", "CMPEQ"):
        lhs = fv(a[0]) if op == "CMPEQSP" else v(a[0])
        rhs = fv(a[1]) if op == "CMPEQSP" else v(a[1])
        return [f"{p}{v(a[-1])} = ({lhs} == {rhs});"]
    if op == "MVD":
        return [p + line for line in mvd_copy(a[0], a[-1])]
    if op == "SPDP":
        hi, lo = a[-1].split(":")
        return [f"{p}dbl_to((double){fv(a[0])}, &{v(hi)}, &{v(lo)});"]
    if op == "ABSDP":
        sh, sl = a[0].split(":")
        dh, dl = a[-1].split(":")
        return [f"{p}dbl_to(dbl_abs(dbl_from({v(sh)}, {v(sl)})), &{v(dh)}, &{v(dl)});"]
    if op in ("ADDDP", "SUBDP", "MPYDP"):
        sym = {"ADDDP": "+", "SUBDP": "-", "MPYDP": "*"}[op]
        a1h, a1l = a[0].split(":")
        a2h, a2l = a[1].split(":")
        dh, dl = a[-1].split(":")
        expr = (f"dbl_from({v(a1h)}, {v(a1l)}) {sym} "
                f"dbl_from({v(a2h)}, {v(a2l)})")
        return [f"{p}dbl_to({expr}, &{v(dh)}, &{v(dl)});"]
    if op == "ADDAH":
        return [f"{p}{v(a[-1])} = {v(a[0])} + ({v(a[1])} << 1);"]
    if op == "SUBAW":
        return [f"{p}{v(a[-1])} = {v(a[0])} - ({v(a[1])} << 2);"]
    return ["/* unsupported %s %s */" % (ins.op, ins.args)]


def emit_c(insns, labels, func):
    global FUNC_RANGE, LABEL_PREFIX
    FUNC_RANGE = (min(i.addr for i in insns), max(i.addr for i in insns) + 8)
    LABEL_PREFIX = re.sub(r"\W", "_", func)
    targets = set(labels)
    for ins in insns:
        bt = z.branch_target(ins)
        if bt:
            targets.add(bt[1])
    regs = ["%s%d" % (side, n) for side in "AB" for n in range(32)]
    out = [
        "/* Generated by emit_c.py from a ZDL audio function. */",
        "#include <stdint.h>",
        "typedef union { unsigned int u; float f; } reg_t;",
        "#define MEM32(base, off) (*(unsigned int *)((unsigned int)(base) + (off)))",
        PRELUDE.rstrip(),
        '#pragma CODE_SECTION(%s, ".audio")' % func,
        "void %s(unsigned int *ctx)" % func,
        "{",
        "  reg_t %s;" % ", ".join(regs),
        "  unsigned int stack_mem[4096];",
        "  A4.u = (unsigned int)ctx;",
        "  B15.u = (unsigned int)(stack_mem + 2048);",
    ]
    emitted = set()
    for ins in insns:
        if ins.addr in targets and ins.addr not in emitted:
            out.append("%s:" % label_for(ins.addr))
            emitted.add(ins.addr)
        for line in emit_insn(ins):
            if line.endswith(":"):
                lab = line[:-1]
                m = re.search(r"_([0-9A-F]{8})$", lab)
                addr = int(m.group(1), 16) if m else None
                if addr is not None:
                    if addr in emitted:
                        continue
                    emitted.add(addr)
            out.append("    " + line)
    for addr in sorted(targets - emitted):
        out.append("%s:" % label_for(addr))
        out.append("    return;")
    out.append("}")
    return "\n".join(out) + "\n"


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    inp = Path(args[0])
    out = None
    func = ""
    i = 1
    while i < len(args):
        if args[i] in ("-o", "--output") and i + 1 < len(args):
            out = Path(args[i + 1]); i += 2
        elif args[i] == "--func" and i + 1 < len(args):
            func = args[i + 1]; i += 2
        else:
            sys.exit("unknown option: %s" % args[i])
    with tempfile.TemporaryDirectory(prefix="emit_c_") as td:
        text, symtxt = z.run_disasm(inp, Path(td))
    insns, labels = z.parse_listing(text)
    insns, labels = z.function_range(insns, labels, func)
    c = emit_c(insns, labels, func)
    if out:
        out.write_text(c, encoding="utf-8")
    else:
        sys.stdout.write(c)


if __name__ == "__main__":
    main()
