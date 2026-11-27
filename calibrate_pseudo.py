#!/usr/bin/env python3
"""Calibrate zdl2pseudo.py against ZDLs that have C sources in effects/.

Compares structural facts, not source text:
  - ctx slots used by the audio function;
  - params indices used;
  - loop count;
  - share of unrecognised instructions.

Usage:
    python cfw/s3k/calibrate_pseudo.py [--out report.md]
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EFFECTS = ROOT / "effects"
EXTRA_SRC = [
    Path(r"C:\zoom\matujuice\zoom-ms-zdl-effects-pack-main\src\custom"),
    Path(r"C:\zoom\themanro\ZoomMultistompZDL-main\src\airwindows"),
]
ZDLNEW = Path(r"C:\zoom\zdlnew")
PSEUDO = HERE / "zdl2pseudo.py"

CTX_RE = re.compile(r"\bctx\s*\[\s*(\d+)\s*\]")
PARAM_ANY_RE = re.compile(r"\bparams\s*\[\s*([A-Za-z_]\w*|\d+)\s*\]")
LOOP_RE = re.compile(r"\b(for|while)\s*\(")
DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+([^\r\n/]+)", re.M)


def resolve(value, macros, seen=()):
    """Resolve #define aliases like EX_SLOT_SLOT -> (EXPR_SLOT_SLOT) -> 5."""
    v = value.strip().strip("()").strip()
    if v.isdigit():
        return int(v)
    if v in seen or not re.fullmatch(r"[A-Za-z_]\w*", v):
        return None
    return resolve(macros.get(v, ""), macros, seen + (v,))


def source_features(cpath):
    t = cpath.read_text(encoding="utf-8", errors="replace")
    macros = {}
    for f in list(cpath.parent.glob("*.h")) + list(cpath.parent.glob("*.c")) \
            + list((cpath.parent.parent / "include").glob("*.h")):
        for name, val in DEFINE_RE.findall(f.read_text(encoding="utf-8", errors="replace")):
            macros[name] = val.strip()
    m = re.search(r"\b(?:void|int)\s+\w*(?:AUDIO_FUNC|Fx_\w+)\s*\([^)]*\)\s*\{", t)
    body = t[m.start():] if m else t
    # Stop at the next top-level function: helper loops after the audio
    # function are not part of the effect's per-block work.
    nxt = re.search(r"\n\s*(?:static\s+)?(?:void|float|int|unsigned|uint32_t)\s+\w+\s*\([^)]*\)\s*\{", body[8:])
    if nxt:
        body = body[:8 + nxt.start()]
    # Community packs generate *_params.h at build time; the manifest is the
    # only surviving source of truth for the knob count.
    for mf in list(cpath.parent.glob("manifest*.json")):
        try:
            man = json.loads(mf.read_text(encoding="utf-8", errors="replace"))
            n = len(man.get("params", []))
            if n:
                prm0 = set(range(5, min(13, 5 + n - 1) + 1))
                break
        except Exception:
            pass
    else:
        prm0 = set()
    prm = set(prm0)
    for token in PARAM_ANY_RE.findall(body):
        if token.isdigit():
            prm.add(int(token))
        else:
            v = resolve(token, macros)
            if v is not None:
                prm.add(v)
    return {
        "ctx": sorted({int(x) for x in CTX_RE.findall(body)}),
        "params": sorted(prm),
        "loops": len(LOOP_RE.findall(body)),
    }


def pseudo_features(pcpath):
    t = pcpath.read_text(encoding="utf-8", errors="replace")
    def grab(label):
        m = re.search(re.escape(label) + r"(.*)", t)
        return m.group(1).strip() if m else ""
    ctx = sorted({int(x) for x in re.findall(r"ctx\[(\d+)\]", grab("/* ctx slots seen:"))})
    prm = sorted({int(x) for x in re.findall(r"p\[(\d+)\]", grab("/* params seen:"))})
    unk = t.count("__unknown(")
    lines = len(t.splitlines())
    return {
        "ctx": ctx,
        "params": prm,
        "loops": t.count("for (;;)"),
        "unknown": unk,
        "lines": lines,
        "unknown_pct": 100.0 * unk / max(1, lines),
    }


def recall(a, b):
    if not a:
        return 1.0 if not b else 0.0
    return len(set(a) & set(b)) / len(set(a))


def pairs():
    out = []
    seen = set()
    roots = [EFFECTS] + [r for r in EXTRA_SRC if r.is_dir()]
    for base in roots:
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            norm = d.name.lower().replace("_", "")
            alias = {"stressparams": "StressP"}.get(norm)
            zdl = ZDLNEW / ((alias or (d.name[0].upper() + d.name[1:])) + ".ZDL")
            if not zdl.is_file():
                cand = [z for z in ZDLNEW.glob("*.ZDL") if z.stem.lower().replace("_", "") == norm]
                if not cand:
                    continue
                zdl = cand[0]
            if zdl.name.lower() in seen:
                continue
            cs = [d / (d.name + ".c")] + sorted(d.glob("*.c"))
            cs = [c for c in cs if c.is_file()]
            if cs:
                seen.add(zdl.name.lower())
                out.append((zdl, cs[0]))
    return out


def main():
    out = None
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    rows = []
    ps = pairs()
    if not ps:
        sys.exit("no ZDL/source pairs found")
    with tempfile.TemporaryDirectory(prefix="calib_pseudo_") as td:
        for zdl, src in ps:
            pc = Path(td) / (zdl.stem + ".pc")
            cmd = [sys.executable, str(PSEUDO), str(zdl), "-o", str(pc)]
            r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            if r.returncode or not pc.is_file():
                rows.append(dict(zdl=zdl.name, src=src.name, error="lift failed"))
                continue
            sf, pf = source_features(src), pseudo_features(pc)
            rows.append(dict(
                zdl=zdl.name, src=src.name,
                src_ctx=sf["ctx"], got_ctx=pf["ctx"], ctx_recall=round(recall(sf["ctx"], pf["ctx"]), 2),
                src_params=sf["params"], got_params=pf["params"],
                param_recall=round(recall(sf["params"], pf["params"]), 2),
                src_loops=sf["loops"], got_loops=pf["loops"],
                unknown_pct=round(pf["unknown_pct"], 1),
            ))
    hdr = "| ZDL | C source | ctx recall | params recall | loops src/got | unknown % |"
    lines = ["# Калибровка zdl2pseudo.py", "", hdr,
             "|---|---|---:|---:|---:|---:|"]
    for r in rows:
        if "error" in r:
            lines.append("| %s | %s | error | | | |" % (r["zdl"], r["src"]))
            continue
        lines.append("| %s | %s | %.2f | %.2f | %d/%d | %.1f |" %
                     (r["zdl"], r["src"], r["ctx_recall"], r["param_recall"],
                      r["src_loops"], r["got_loops"], r["unknown_pct"]))
    ok = [r for r in rows if "error" not in r]
    if ok:
        ac = sum(r["ctx_recall"] for r in ok) / len(ok)
        ap = sum(r["param_recall"] for r in ok) / len(ok)
        lines += ["", "Средняя полнота: ctx %.2f, params %.2f" % (ac, ap)]
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8"))
    if out:
        (out.with_suffix(".json")).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
