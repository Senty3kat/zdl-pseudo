#!/usr/bin/env python3
"""Ten native byte-equal factory ZDLs rebuilt and tested with sweep+knob UI."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import batch_rebuild as b
import compare_sweep_turn as cs

TMP = Path(os.environ.get("TEMP", ".")) / "opencode"
SRC = TMP / "em_named"
OLD_REPORT = (TMP / "zdlnew_my_artifacts_20261127_115136"
              / "FULL_AUDIO_ALL_FARDATA.csv")
OUT = Path(r"C:\zoom\zdlnew\SWEEP10_NATIVE")
SWEEP = OUT / "sweep.wav"
NAMES = ["Echo", "Flanger", "HPS", "Limiter", "optcomp",
         "DynaRev", "DualDigiD", "DualRev", "DynaFlanger", "ER"]
assert all("_1" not in n and "(1)" not in n and not n.startswith("Reb_") for n in NAMES)
TARGETS = {
    "Echo": "ECHO.ZDL",
    "Flanger": "FLANGER.ZDL",
    "HPS": "HPS.ZDL",
    "Limiter": "LIMITER.ZDL",
    "optcomp": "OPTCOMP.ZDL",
    "DynaRev": "DYNAREV.ZDL",
    "DualDigiD": "DUALDIGD.ZDL",
    "DualRev": "DUAL_REV.ZDL",
    "DynaFlanger": "DYNFLNGR.ZDL",
    "ER": "EARLYREF.ZDL",
}


def make_sweep():
    import math
    import struct
    import wave
    fs, dur = 44100, 11.0
    f0, f1 = 80.0, 12000.0
    n = int(fs * dur)
    k = math.log(f1 / f0) / dur
    phase = 0.0
    fade = int(0.02 * fs)
    frames = bytearray()
    for i in range(n):
        t = i / fs
        phase += 2 * math.pi * (f0 * math.exp(k * t)) / fs
        if phase > 2 * math.pi:
            phase -= 2 * math.pi
        w = min(1.0, i / fade, (n - i) / fade)
        v = int(max(-1, min(1, 0.22 * w * math.sin(phase))) * 32767)
        frames += struct.pack("<hh", v, v)
    SWEEP.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SWEEP), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(bytes(frames))


def stock_names():
    import full_audio_compare as f
    return f.stock_zdl_names()


def fsname(name):
    return name.upper()[:8] + ".ZDL"


def setup_full(work, zdl, target_name):
    work.mkdir(parents=True, exist_ok=True)
    for n in ["129_main_OS.bin", "133_data_133.bin", "136_bootloader.bin", "137_file_system.bin"]:
        shutil.copy2(cs.FW / n, work / n)
    shutil.copy2(SWEEP, work / "sweep.wav")
    repl = work / target_name
    shutil.copy2(zdl, repl)
    r = subprocess.run(["python", str(cs.FSEDIT), str(cs.FW / "137_file_system.bin"),
                        str(work / "137_file_system.bin"), "--add", str(repl)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)


def run(work, turn, seconds=12):
    cmd = [str(cs.EMU), "129_main_OS.bin", "-s", str(seconds), "-q", "-flashfast",
           "-wav", "sweep.wav", "-snap", "6200:before.png"]
    if turn:
        cmd += ["-turn", "6500:17:30:12"]
    cmd += ["-snap", "7500:after.png"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-2000:])


def main():
    make_sweep()
    stocks = stock_names()
    results = []
    for name in NAMES:
        src = SRC / f"{name}.ZDL"
        fxid, gid, desc, knobs = b.zdl_info(src)
        target = TARGETS.get(name, fsname(name))
        if target not in stocks:
            print("skip missing in stock FS", name, target)
            continue
        work_root = OUT / name
        rebuilt_src = work_root / "rebuilt.ZDL"
        if not rebuilt_src.exists():
            rebuilt_src.parent.mkdir(parents=True, exist_ok=True)
            b.rebuild(src, None, rebuilt_src.parent) if False else None
            # rebuild with explicit function from BATCH_ALL
            func = None
            batch_csv = (TMP / "zdlnew_my_artifacts_20261127_115136"
                         / "BATCH_ALL.csv")
            for line in batch_csv.read_text(encoding="utf-8").splitlines():
                p = [x.strip() for x in line.strip("|").split("|")]
                if len(p) > 1 and p[0] == name:
                    func = p[1]
                    break
            if not func:
                print("skip no func", name)
                continue
            build_dir = rebuilt_src.parent / "build"
            build_dir.mkdir(parents=True, exist_ok=True)
            out = b.rebuild(src, func, build_dir)
            rebuilt_src.write_bytes(out.read_bytes())
            reb_named = rebuilt_src.parent / f"Reb_{name}.ZDL"
            reb_named.write_bytes(out.read_bytes())
        row = {"effect": name, "desc": desc, "fxid": fxid, "gid": gid, "target": target}
        for kind, zdl, turn in (("orig_before", src, False),
                                ("orig_after", src, True),
                                ("reb_after", rebuilt_src, True)):
            work = work_root / kind
            setup_full(work, zdl, target)
            run(work, turn)
            row[kind] = str(work / "after.png")
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (OUT / "INDEX.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
