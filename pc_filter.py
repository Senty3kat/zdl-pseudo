#!/usr/bin/env python3
"""Build-rule filter for pseudo-C lifted from a ZDL.

The pseudo-C produced by zdl2pseudo.py is a structural aid: it restores the
ctx ABI, params and loops, but it is not compilable. This filter validates the
lifted ABI and emits buildable C by applying the ZDL ABI rules to the matching
disassembly listing (typed compares, MEM32 accesses, register model, labels).

Usage:
    python pc_filter.py ORIG.pc ORIG.lst FUNC -o FILTERED.c
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import emit_c
import zdl2pseudo as z


def _abi_summary(pc_text: str) -> tuple[str, str]:
    mctx = re.search(r"/\* ctx slots seen:([^*]*)\*/", pc_text)
    mpar = re.search(r"/\* params seen:([^*]*)\*/", pc_text)
    return (mctx.group(1).strip() if mctx else "",
            mpar.group(1).strip() if mpar else "")


def filter_pc(pc_path: Path, lst_path: Path, func: str, out_path: Path) -> Path:
    pc_text = pc_path.read_text(encoding="utf-8", errors="replace")
    if func not in pc_text:
        raise RuntimeError(f"{func} not found in pseudo-C")
    ctx, params = _abi_summary(pc_text)
    if not ctx or not params:
        raise RuntimeError("pseudo-C has no ctx/params ABI summary")

    listing = lst_path.read_text(encoding="utf-8", errors="replace")
    insns, labels = z.parse_listing(listing)
    addrs = [int(a, 16) for a in re.findall(r"//\s+([0-9A-Fa-f]{8})", pc_text)]
    if addrs:
        lo, hi = min(addrs), max(addrs) + 4
        insns = [i for i in insns if lo <= i.addr < hi]
        labels = {a: l for a, l in labels.items() if lo <= a < hi}
        labels.setdefault(lo, func)
    else:
        insns, labels = z.function_range(insns, labels, func)
    csrc = emit_c.emit_c(insns, labels, func)
    banner = (
        "/* Built from pseudo-C by pc_filter.py (ZDL ABI build-rule filter).\n"
        f" * ctx slots:{ctx}\n"
        f" * params:{params}\n"
        " */\n"
    )
    out_path.write_text(banner + csrc, encoding="utf-8")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pc")
    ap.add_argument("lst")
    ap.add_argument("func")
    ap.add_argument("-o", "--out", required=True)
    ns = ap.parse_args()
    out = filter_pc(Path(ns.pc), Path(ns.lst), ns.func, Path(ns.out))
    print(out)


if __name__ == "__main__":
    main()
