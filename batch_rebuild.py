#!/usr/bin/env python3
"""Batch original -> lifted C -> rebuilt ZDL -> audio comparison.

Usage:
    python batch_rebuild.py <zdl1> <zdl2> ... --out REPORT.md
"""
import json
import re
import struct
import subprocess
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(os.environ.get("TEMP", ".")) / "opencode"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "toolchain" / "zdl")]
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("zpaths", ROOT / "paths.py")
_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_paths)
TI_ROOT = _paths.TI_ROOT
from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
from custom_covers import make_cover  # noqa: E402

import emit_c  # noqa: E402

CL6X = TI_ROOT / "bin" / "cl6x"
CFLAGS = ["--c99", "--opt_level=2", "--fp_mode=strict", "-mv6740", "--abi=eabi",
          "--mem_model:data=far", f"--include_path={TI_ROOT}/include"]
EMU = ROOT / "emulator" / "build" / "c6xzdl.exe"
SINE = TMP / "eqcheck/sine24.wav"
BAD_RE = re.compile(
    r"_(edit|init|onf|onfaft|open|mute|close|deinit|exit|start|stop|"
    r"set|get|select|update|check|ctl|param)(_|$)"
)


def audio_func(sym):
    funcs = []
    for line in sym.splitlines():
        m = re.match(r"^([0-9A-Fa-f]+)\s+FUNC\s+(\S+)", line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        name = m.group(2)
        low = name.lower()
        if not name.startswith("Fx_"):
            continue
        if BAD_RE.search(low) or "tapmute" in low or "dll" in low:
            continue
        funcs.append((addr, name))
    if not funcs:
        return None
    funcs.sort()
    return funcs[-1][1]


def zdl_info(path):
    """Return (fxid, gid, [(name, max, default)]) from a factory ZDL descriptor."""
    d = Path(path).read_bytes()
    gid, fxid = d[0x3C], d[0x40] | (d[0x41] << 8)
    i = 0
    while True:
        i = d.find(b"OnOff\0", i)
        if i < 0:
            raise ValueError("no descriptor table")
        ents, off = [], i
        while True:
            e = d[off:off + 0x30]
            nm = e[:10].split(b"\0")[0]
            if len(e) < 0x30 or any(c < 0x1F or c > 0x7E for c in nm):
                ents = None
                break
            mx = struct.unpack_from("<I", e, 12)[0]
            df = struct.unpack_from("<I", e, 16)[0]
            fl = struct.unpack_from("<I", e, 0x2C)[0]
            ents.append((nm.decode("latin-1"), mx, df, fl))
            off += 0x30
            if fl & 4 or len(ents) > 12:
                break
        if ents and len(ents) >= 2 and ents[1][1] == 0xFFFFFFFF:
            return fxid, gid, ents[1][0], [(x[0], x[1], x[2], x[3]) for x in ents[2:]
                                          if x[0] and x[1] != 0xFFFFFFFF]
        i += 1


def zdl_soname_prefix(path):
    d = Path(path).read_bytes()
    m = re.search(rb"ZDL_([A-Z0-9]+)_", d)
    return m.group(1).decode("ascii") if m else None


def rebuild(zdl, func, work, undefs=()):
    with tempfile.TemporaryDirectory(prefix="lift_") as td:
        text, sym = emit_c.z.run_disasm(zdl, Path(td))
    insns, labels = emit_c.z.parse_listing(text)
    insns, labels = emit_c.z.function_range(insns, labels, func)
    csrc = emit_c.emit_c(insns, labels, func)
    called = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", csrc))
    defined = set(re.findall(r"\bvoid\s+([A-Za-z_]\w*)\s*\(", csrc))
    skip = {"MEM32", "CODE_SECTION", "DBG", "sat32", "sat_add32", "sat_sub32",
            "sat_shl32", "abs32", "absf32", "dbl_from", "dbl_to", "dbl_abs",
            "if", "while", "for", "switch", "return", "sizeof"}
    needed = sorted((called | set(undefs)) - defined - skip - {func, "none"})
    if needed:
        stubs = "".join("void %s(unsigned int *ctx) { (void)ctx; }\n" % u for u in needed)
        csrc = csrc.replace("#include <stdint.h>\n", "#include <stdint.h>\n" + stubs, 1)
    cpath = work / "effect.c"
    cpath.write_text(csrc, encoding="utf-8")
    obj = work / "effect.obj"
    subprocess.run([str(CL6X), *CFLAGS, "-c", str(cpath), f"--output_file={obj}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = work / "rebuilt.ZDL"
    try:
        fxid, gid, effect_name, knobs = zdl_info(zdl)
        params = [{"name": n, "max": mx, "default": df, "flags": fl}
                  for n, mx, df, fl in knobs]
    except Exception:
        fxid, gid, effect_name = 900, 2, "REBUILT"
        params = [{"name": "P%d" % (i + 1), "max": 100, "default": 50, "flags": 0}
                  for i in range(9)]
    if not params:
        params = [{"name": "P1", "max": 100, "default": 50, "flags": 0}]
    cfg = LinkerConfig(
        materialize_init=True,
        effect_name=effect_name[:12],
        screen_image=make_cover(effect_name[:12], [p["name"] for p in params[:3]]),
        audio_func_name=func,
        gid=gid,
        fxid=fxid,
        params=params_from_manifest(params),
        obj_path=obj,
        output_path=out,
        fxid_version=b"1.00",
        flags_byte=1,
        soname_prefix=zdl_soname_prefix(zdl),
        audio_nop=False,
        allow_large_fardata=True,
        dsp_cost=20.0,
        knob_positions=[(2, 24, 46), (3, 72, 46)],
        allow_fewer_knob_boxes=True,
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
        knob3_blob_path="/tmp/__nonexistent__",
    )
    link(cfg)
    return out


def audio(zdl, func, out):
    subprocess.run([str(EMU), str(zdl), str(SINE), str(out), "--func", func, "--fw-stubs"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out if out.is_file() else None


def main():
    args = [a for a in sys.argv[1:]]
    if len(args) < 2:
        sys.exit("usage: batch_rebuild.py IN_DIR OUT.csv [LIMIT] [START]")
    in_dir = Path(args[0]); out = Path(args[1])
    limit = int(args[2]) if len(args) > 2 else 10
    start = int(args[3]) if len(args) > 3 else 0
    rows = []
    base = TMP / "batch"
    for zdl in sorted(in_dir.glob("*.ZDL"))[start:start + limit]:
        zdl = Path(zdl)
        name = zdl.stem
        work = base / name
        work.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="sym_") as td:
                text, sym = emit_c.z.run_disasm(zdl, Path(td))
            func = audio_func(sym)
            if not func:
                raise RuntimeError("audio function not found")
            undefs = []
            for line in text.splitlines():
                if line.startswith(";") and "undef=" in line:
                    raw = line.split("undef=", 1)[1].split()[0]
                    undefs = [] if raw == "none" else [u for u in raw.split(",") if u]
                    break
            rebuilt = rebuild(zdl, func, work, undefs)
            origf = audio(zdl, func, work / "orig.f32")
            newf = audio(rebuilt, func, work / "new.f32")
            status = "audio_equal" if origf and newf and origf.read_bytes() == newf.read_bytes() else "audio_diff_or_missing"
            rows.append((name, func, "ok", status, len(rebuilt.read_bytes())))
        except Exception as e:
            rows.append((name, "?", "fail:" + str(e)[:120], "", 0))
        print(name, rows[-1][2], rows[-1][3])
    lines = ["| Effect | Func | Build | Audio | Size |", "|---|---|---|---|---|"]
    lines += ["| %s | %s | %s | %s | %d |" % r for r in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report", out)


if __name__ == "__main__":
    main()
