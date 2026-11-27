#!/usr/bin/env python3
"""Turn a ZDL/S3K disassembly listing into readable pseudo-C.

This is NOT a decompiler in the sense of recovering the original C source.
It lifts TI C6000 assembly (as printed by disasm_zdl.py + dis6x) into commented
pseudo-C with basic blocks, loops and ctx/params/buf symbols from the Zoom ABI.

Usage:
    python zdl2pseudo.py HDHALL.ZDL -o HDHALL.pc --cfg HDHALL.dot
    python zdl2pseudo.py HDHALL.lst -o HDHALL.pc --func Fx_REV_HD_Hall
"""
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DISASM = HERE / "disasm_zdl.py"

LINE_RE = re.compile(r"^([0-9A-Fa-f]{8})\s+([0-9a-fA-F]{4,8})?\s*(\|\|)?\s*(.*?)\s*$")
LABEL_RE = re.compile(r"^([0-9A-Fa-f]{8})\s+(\$C\$L\d+|[A-Za-z_][\w]*):\s*$")
BRANCH_TARGET_RE = re.compile(r"(\$C\$L\d+)\s*\(PC[+-]\d+\s*=\s*(0x)?([0-9A-Fa-f]+)\)")
BRANCH_RAW_RE = re.compile(r"(?<![\w])0x([0-9A-Fa-f]{4,8})\b")


def abs_addr(v):
    """dis6x prints either absolute S3K addresses or raw ELF vaddrs."""
    if v >= 0xC0000000:
        return v
    if v >= 0x80000000:
        return 0xC0500000 + (v - 0x80000000)
    return 0xC0400000 + v


def branch_target(ins):
    """Return (label, absolute target) for a branch, or None."""
    m = BRANCH_TARGET_RE.search(ins.args)
    if m:
        return m.group(1), int(m.group(3), 16)
    m = BRANCH_RAW_RE.search(ins.args)
    if m:
        v = int(m.group(1), 16)
        return "L_%08X" % abs_addr(v), abs_addr(v)
    return None
MEM_RE = re.compile(r"^\*\+?([AB]\d+)\s*(?:\[([^\]]+)\])?$")
REG_RE = re.compile(r"^([AB])(\d+)$")


@dataclass
class Insn:
    addr: int
    words: str
    parallel: bool
    text: str
    predicate: str = ""
    op: str = ""
    args: str = ""
    alias: dict = field(default_factory=dict)

    def __post_init__(self):
        t = self.text.strip()
        m = re.match(r"^(\[\s*!?[AB]\d+\s*\])\s*(.*)$", t)
        if m:
            self.predicate = m.group(1).strip()[1:-1].strip()
            t = m.group(2)
        parts = t.split(None, 1)
        self.op = parts[0] if parts else ""
        self.args = parts[1].strip() if len(parts) > 1 else ""


@dataclass
class Block:
    addr: int
    label: str = ""
    insns: list = field(default_factory=list)
    succ: list = field(default_factory=list)
    loop: bool = False
    loop_end: int = 0


def run_disasm(inp, work):
    lst = work / "effect.lst"
    sym = work / "effect.sym.txt"
    if inp.suffix.lower() == ".lst":
        lst.write_text(inp.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        cmd = [sys.executable, str(DISASM), str(inp), "-o", str(lst),
               "--symbols", str(sym), "--lines", "0"]
        subprocess.run(cmd, cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    symtxt = sym.read_text(encoding="utf-8", errors="replace") if sym.is_file() else ""
    return lst.read_text(encoding="utf-8", errors="replace"), symtxt


def parse_listing(text):
    insns, labels = [], {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith(";") or line.startswith("TEXT Section") \
                or line.startswith("DATA Section") or line.startswith("BSS Section"):
            continue
        m = LABEL_RE.match(line)
        if m:
            labels[int(m.group(1), 16)] = m.group(2)
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        words, par, body = m.group(2) or "", bool(m.group(3)), m.group(4)
        if not body or body.startswith((".fphead", ".", "^")):
            continue
        insns.append(Insn(addr, words, par, body))
    return insns, labels


def function_range(insns, labels, func):
    """Restrict analysis to one exported function, not the whole ELF."""
    fns = [(a, l) for a, l in labels.items() if not l.startswith("$C$L")]
    start = None
    if func:
        for a, l in sorted(fns):
            if l == func:
                start = a
                break
    if start is None and func:
        for a, l in sorted(fns):
            if l.startswith(func):
                start = a
                break
    if start is None:
        for a, l in sorted(fns):
            if l.startswith("Fx_") and not l.endswith(("_init", "_onf", "_edit", "_onf_aft")):
                start = a
                break
    if start is None:
        return insns, labels
    later = sorted(a for a, l in fns if a > start)
    end = later[0] if later else max(i.addr for i in insns) + 4
    insns = [i for i in insns if start <= i.addr < end]
    labels = {a: l for a, l in labels.items() if start <= a < end}
    labels.setdefault(start, func or "Fx_unknown")
    return insns, labels


def make_blocks(insns, labels):
    starts = set(labels) | {insns[0].addr}
    for ins in insns:
        if not ins.op.startswith("B"):
            continue
        bt = branch_target(ins)
        if bt:
            starts.add(bt[1])
            labels.setdefault(bt[1], bt[0])
    starts = sorted(starts)
    blocks = {}
    by_addr = {i.addr: i for i in insns}
    for idx, st in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else max(i.addr for i in insns) + 4
        b = Block(st, labels.get(st, ""))
        b.insns = [i for i in insns if st <= i.addr < end]
        blocks[st] = b
    for b in blocks.values():
        for ins in b.insns:
            if not ins.op.startswith("B"):
                continue
            bt = branch_target(ins)
            if bt:
                target = bt[1]
                b.succ.append(target)
                if target <= ins.addr and target in blocks and (ins.addr - target) >= 64:
                    blocks[target].loop = True
                    blocks[target].loop_end = max(blocks[target].loop_end, b.addr)
    # A source DSP loop either writes the audio buffer or, when the effect has
    # no fxBuf slot, contains substantial float work. Stack/register cleanup
    # loops and pipeline stages do neither.
    has_fx = any("fxBuf" in i.alias.values() for i in insns)
    for b in blocks.values():
        if not b.loop:
            continue
        body = [i for i in insns if b.addr <= i.addr <= b.loop_end]
        nfloat = sum(1 for i in body if "SP" in i.op or "DP" in i.op or "MPY" in i.op)
        naudio = 0
        for i in body:
            if not i.op.startswith("STW"):
                continue
            a = [x.strip() for x in i.args.split(",")]
            if len(a) < 2:
                continue
            m = MEM_RE.match(a[1])
            if m and i.alias.get(m.group(1)) == "fxBuf":
                naudio += 1
        span = b.loop_end - b.addr
        total = max(i.addr for i in insns) - min(i.addr for i in insns)
        if nfloat < 2 or span < max(32, total // 10):
            b.loop = False
            b.loop_end = 0
    # Software pipelining creates several back-edges for one source loop:
    # keep only the outermost range when ranges overlap.
    kept = []
    for b in sorted([x for x in blocks.values() if x.loop], key=lambda x: x.addr):
        drop = False
        for k in kept:
            # Only merge back-edges to the same header or with the same end:
            # nested source loops have different starts and must stay separate.
            span = max(b.loop_end, k.loop_end) - min(b.addr, k.addr)
            if b.addr == k.addr or abs(b.loop_end - k.loop_end) <= max(64, span // 10):
                drop = True
                if (k.loop_end - k.addr) < (b.loop_end - b.addr):
                    k.loop = False
                    k.loop_end = 0
                    kept.remove(k)
                    kept.append(b)
                break
        if drop:
            if not b.loop:
                continue
            b.loop = False
            b.loop_end = 0
        else:
            kept.append(b)
    if not any(b.loop for b in blocks.values()):
        best = None
        for b in blocks.values():
            for ins in b.insns:
                if not ins.op.startswith("B"):
                    continue
                bt = branch_target(ins)
                if not bt or bt[1] > ins.addr or bt[1] not in blocks:
                    continue
                span = ins.addr - bt[1]
                if span < 32:
                    continue
                if best is None or span > best[0]:
                    best = (span, bt[1], b.addr)
        if best:
            blocks[best[1]].loop = True
            blocks[best[1]].loop_end = best[2]
    return blocks


def zdl_knob_count(path):
    """Count knob entries in SonicStomp so variable-index param loops can be named."""
    if not path or not str(path).lower().endswith(".zdl"):
        return 0
    try:
        from zdl2s3k import parse_zdl, zdl_map
        segs, syms, _u, _nr, _nb, _ts, _cs = parse_zdl(str(path))
        base = None
        for name, val, shndx in syms:
            if name == "SonicStomp" and shndx:
                base = zdl_map(val)
                break
        if base is None:
            return 0
        data = bytearray()
        for at, buf, _msz in segs:
            if at <= base < at + len(buf):
                data = buf[base - at:]
                break
        if not data:
            return 0
        for i in range(0, min(len(data) - 48, 16 * 48), 48):
            if data[i + 0x2C] & 0x04:
                return max(0, i // 48 - 1)   # OnOff + name + knobs
    except Exception:
        pass
    return 0


def symbolic(insns, func, nknobs=0):
    """Propagate ABI names and params-pointer offsets; return (alias, slots, params)."""
    alias = {"A4": "ctx"}
    poff = {}                            # register -> byte offset from params base
    stack_alias, stack_poff = {}, {}     # B15 slots preserve pointers across spills
    ever_params = set()                  # registers that once held the params pointer
    slots, params = set(), set()
    for ins in insns:
        ins.alias = dict(alias)          # snapshot BEFORE this instruction
        op = ins.op.split(".")[0]
        args = [a.strip() for a in ins.args.split(",")]
        dst = args[-1] if args and not args[-1].startswith("*") else ""
        if op == "MV" and len(args) == 2:
            src, dst = args
            if src in alias:
                alias[dst] = alias[src]
                if src in poff:
                    poff[dst] = poff[src]
                else:
                    poff.pop(dst, None)
            else:
                alias.pop(dst, None)
                poff.pop(dst, None)
        elif op in ("ADD", "ADDK", "ADDAD") and len(args) == 3 and alias.get(args[0]) == "params":
            imm = args[1]
            try:
                v = int(imm, 0)
            except ValueError:
                v = 0
            alias[dst] = "params"
            poff[dst] = poff.get(args[0], 0) + v
        elif op == "STW" and len(args) == 2:
            m1 = MEM_RE.match(args[1])
            if m1 and m1.group(1) == "B15" and (m1.group(2) or "").isdigit():
                key = int(m1.group(2))
                if args[0] in alias:
                    stack_alias[key] = alias[args[0]]
                    stack_poff[key] = poff.get(args[0], 0)
        elif op == "LDW" and len(args) == 2:
            mem = args[0].replace("++", "").replace("--", "")
            m = MEM_RE.match(mem)
            if m and m.group(1) == "B15" and (m.group(2) or "").isdigit():
                key = int(m.group(2))
                if key in stack_alias:
                    alias[args[1]] = stack_alias[key]
                    poff[args[1]] = stack_poff[key]
                    continue
            if m:
                root = alias.get(m.group(1), m.group(1))
                off = m.group(2) or "0"
                if root == "params":
                    ever_params.add(m.group(1))
                if root == "ctx" and off.isdigit():
                    slot = int(off)
                    slots.add(slot)
                    if slot == 1:
                        alias[args[1]] = "params"
                        poff[args[1]] = 0
                    elif slot == 5:
                        alias[args[1]] = "fxBuf"
                    elif slot == 3:
                        alias[args[1]] = "arena"
                    elif slot in (11, 12):
                        alias[args[1]] = "magic%d" % slot
                    else:
                        alias.pop(args[1], None)
                else:
                    alias.pop(args[1], None)
                if root != "params" and m.group(1) in ever_params and off.isdigit():
                    idx = int(off)
                    if 5 <= idx <= 13:
                        params.add(idx)
                if root == "params":
                    base = poff.get(m.group(1), 0)
                    if off.isdigit():
                        idx = base // 4 + int(off)
                        if 0 <= idx <= 13:
                            params.add(idx)
                        if "++" in args[0]:
                            if nknobs:
                                params.update(range(5, min(13, 5 + nknobs - 1) + 1))
                            poff[m.group(1)] = base + int(off) * 4
                    elif nknobs:
                        params.update(range(5, min(13, 5 + nknobs - 1) + 1))
                    else:
                        params.add("reg:" + off)
        elif op in ("MVK", "MPYSP", "MPY", "ADDSP", "SUBSP", "ADD", "SUB",
                    "ADDAD", "ADDK", "SET", "ZERO", "CLR", "LDNDW", "LDDW"):
            if dst:
                alias.pop(dst, None)
                poff.pop(dst, None)
    return alias, sorted(slots), sorted(params, key=str)


def reg_name(token, alias):
    token = token.strip()
    if REG_RE.match(token) and token in alias:
        return alias[token]
    return token


def lift_insn(ins):
    op = ins.op.split(".")[0]
    a = [x.strip() for x in ins.args.split(",")]
    al = ins.alias
    rn = lambda t: reg_name(t, al)
    p = ("if (%s) " % ins.predicate) if ins.predicate else ""
    c = "// %08X" % ins.addr
    if op == "NOP":
        n = a[0] if a else ""
        return "  /* delay%s @ %s */" % ((" " + n) if n else "", c[3:])
    if op == "MVK":
        return "  %s%s = %s; %s" % (p, rn(a[1]) if len(a) > 1 else "?", a[0], c)
    if op in ("MV",):
        return "  %s%s = %s; %s" % (p, rn(a[1]) if len(a) > 1 else "?", rn(a[0]) if a else "?", c)
    if op in ("MPYSP", "ADDSP", "SUBSP", "ADD", "SUB", "MPY"):
        sym = {"MPYSP": "*", "MPY": "*", "ADDSP": "+", "ADD": "+", "SUBSP": "-", "SUB": "-"}[op]
        if len(a) >= 3:
            return "  %s%s = %s %s %s; %s" % (p, rn(a[2]), rn(a[0]), sym, rn(a[1]), c)
    if op in ("LDW", "LDNDW", "LDDW"):
        if len(a) >= 2:
            return "  %s%s = read(%s); %s" % (p, rn(a[1]), rn(a[0]), c)
    if op in ("STW", "STDW", "STNDW"):
        if len(a) >= 2:
            return "  %swrite(%s, %s); %s" % (p, rn(a[1]), rn(a[0]), c)
    if op in ("B", "BNOP", "BDEC"):
        bt = branch_target(ins)
        if bt:
            return "  %sgoto %s; %s" % (p, bt[0].replace("$", ""), c)
        return "  %sindirect_branch(%s); %s" % (p, ins.args, c)
    if op.startswith("B") and op.endswith("X"):
        return "  %sindirect_branch(%s); %s" % (p, ins.args, c)
    if op.startswith("MVKH"):
        return "  %s%s = (%s << 16); %s" % (p, rn(a[-1]) if a else "?", a[0] if a else "0", c)
    if op.startswith("MVK"):
        return "  %s%s = %s; %s" % (p, rn(a[-1]) if a else "?", a[0] if a else "0", c)
    if op.startswith("CALLP"):
        return "  %scall %s; %s" % (p, ins.args, c)
    if op.startswith("ADDKPC"):
        return "  %s%s = pc + %s; %s" % (p, rn(a[-1]) if a else "?", a[0] if a else "0", c)
    if op.startswith("SPMASK"):
        return "  /* saturation mask @ %s */" % c[3:]
    if op.startswith("CMP"):
        sym = {"CMPEQ": "==", "CMPGT": ">", "CMPLT": "<", "CMPGE": ">=", "CMPLE": "<="}
        s = next((v for k, v in sym.items() if op.startswith(k)), "!=")
        if len(a) >= 3:
            return "  %s%s = (%s %s %s); %s" % (p, rn(a[2]), rn(a[0]), s, rn(a[1]), c)
    if op.startswith("SHL"):
        if len(a) >= 3:
            return "  %s%s = %s << %s; %s" % (p, rn(a[2]), rn(a[0]), rn(a[1]), c)
    if op.startswith("SHR"):
        if len(a) >= 3:
            return "  %s%s = %s >> %s; %s" % (p, rn(a[2]), rn(a[0]), rn(a[1]), c)
    if op.startswith("XOR"):
        if len(a) >= 3:
            return "  %s%s = %s ^ %s; %s" % (p, rn(a[2]), rn(a[0]), rn(a[1]), c)
    if op.startswith("AND"):
        if len(a) >= 3:
            return "  %s%s = %s & %s; %s" % (p, rn(a[2]), rn(a[0]), rn(a[1]), c)
    if op.startswith("OR"):
        if len(a) >= 3:
            return "  %s%s = %s | %s; %s" % (p, rn(a[2]), rn(a[0]), rn(a[1]), c)
    if op.startswith("STB"):
        if len(a) >= 2:
            return "  %swrite_byte(%s, %s); %s" % (p, rn(a[1]), rn(a[0]), c)
    if op.startswith("LDB"):
        if len(a) >= 2:
            return "  %s%s = read_byte(%s); %s" % (p, rn(a[1]), rn(a[0]), c)
    if op == "ZERO":
        return "  %s%s = 0; %s" % (p, rn(a[0]) if a else "?", c)
    if op == "SET":
        return "  /* set bits %s @ %s */" % (ins.args, c[3:])
    if op == "CLR":
        return "  /* clear bits %s @ %s */" % (ins.args, c[3:])
    return "  __unknown(%s, %s); %s" % (ins.op, ins.args, c)


def emit_pseudo(blocks, alias, slots, params, func, src):
    out = []
    out.append("/* Pseudo-C lifted from %s by zdl2pseudo.py" % src)
    out.append(" * WARNING: structure aid, not original source. Verify with c6xzdl. */")
    out.append("/* audio function: %s */" % func)
    out.append("void %s(unsigned int *ctx)" % (func or "Fx_unknown"))
    out.append("{")
    out.append("  float *params = ctx[1];   /* ABI slot 1 */")
    out.append("  float *fxBuf  = ctx[5];   /* ABI slot 5, 8+8 samples */")
    out.append("  /* ctx slots seen: %s */" % (", ".join("ctx[%d]" % s for s in slots) or "none"))
    out.append("  /* params seen: %s */" % (", ".join("p[%s]" % p for p in params) or "none"))
    out.append("")
    for addr in sorted(blocks):
        b = blocks[addr]
        if b.label:
            out.append("label_%s:" % b.label.replace("$", ""))
        if b.loop:
            out.append("  for (;;) { /* pipelined loop @ %08X */" % addr)
        for ins in b.insns:
            out.append(lift_insn(ins))
        if b.succ:
            out.append("  /* next: %s */" % ", ".join("%08X" % s for s in b.succ))
        if b.loop_end == addr:
            out.append("  } /* end loop @ %08X */" % addr)
        out.append("")
    out.append("}")
    return "\n".join(out) + "\n"


def emit_dot(blocks):
    lines = ["digraph cfg {", "  node [shape=box,fontname=Courier];"]
    for addr, b in blocks.items():
        lines.append('  n%08X [label="%08X\\n%s\\n%d insns%s"];' %
                     (addr, addr, b.label, len(b.insns), " LOOP" if b.loop else ""))
        for s in b.succ:
            lines.append("  n%08X -> n%08X;" % (addr, s))
    lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    inp = Path(args[0])
    if not inp.is_file():
        sys.exit("input not found: %s" % inp)
    out = None
    cfg = None
    func = ""
    i = 1
    while i < len(args):
        if args[i] in ("-o", "--output") and i + 1 < len(args):
            out = Path(args[i + 1]); i += 2
        elif args[i] == "--cfg" and i + 1 < len(args):
            cfg = Path(args[i + 1]); i += 2
        elif args[i] == "--func" and i + 1 < len(args):
            func = args[i + 1]; i += 2
        else:
            sys.exit("unknown option: %s" % args[i])
    if not func and inp.suffix.lower() != ".lst":
        m = re.search(r"audio_func=([^\s]+)", inp.read_bytes().decode("latin-1", "replace"))
        func = m.group(1) if m else ""
    with tempfile.TemporaryDirectory(prefix="zdl_pseudo_") as td:
        text, symtxt = run_disasm(inp, Path(td))
        insns, labels = parse_listing(text)
        for line in symtxt.splitlines():
            m = re.match(r"^([0-9A-Fa-f]{8})\s+FUNC\s+(\S+)", line)
            if m:
                labels.setdefault(int(m.group(1), 16), m.group(2))
    if not insns:
        sys.exit("no instructions parsed")
    if not func:
        for line in symtxt.splitlines():
            m = re.search(r"\b(Fx_\w+)\b", line)
            if m and not m.group(1).endswith(("_init", "_onf", "_edit", "_onf_aft")):
                func = m.group(1)
                break
    if not func:
        for a in labels.values():
            if a.startswith("Fx_") and not a.endswith(("_init", "_onf", "_edit")):
                func = a
                break
    insns, labels = function_range(insns, labels, func)
    nknobs = zdl_knob_count(inp) if inp.suffix.lower() == ".zdl" else 0
    alias, slots, params = symbolic(insns, func, nknobs)  # sets ins.alias snapshots
    blocks = make_blocks(insns, labels)
    pseudo = emit_pseudo(blocks, alias, slots, params, func, str(inp))
    if out:
        out.write_text(pseudo, encoding="utf-8")
    if cfg:
        cfg.write_text(emit_dot(blocks), encoding="utf-8")
    print("parsed %d instructions, %d labels, %d blocks, %d loops" %
          (len(insns), len(labels), len(blocks), sum(1 for b in blocks.values() if b.loop)))
    print("ctx slots: %s" % (", ".join("ctx[%d]" % s for s in slots) or "none"))
    print("params: %s" % (", ".join("p[%s]" % p for p in params) or "none"))
    print("pseudo-C: %s" % (out or "<stdout>"))
    if not out:
        sys.stdout.write(pseudo)


if __name__ == "__main__":
    main()
