#!/usr/bin/env python3
"""Compare original/rebuilt ZDL after the same UI knob turn in full c6xboot.

The target effect replaces STCHO.ZDL in a full stock FS, so the firmware edit
path has all stock files. Each case captures a Play screenshot before the turn
and an Edit screenshot after it, plus out.wav.
"""
import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EMU = ROOT / "emulator" / "build" / "c6xboot.exe"
FSEDIT = ROOT / "emulator" / "tools" / "fsedit.py"
FW = ROOT / "vst_zdl" / "fw70"
SINE = Path(os.environ.get("TEMP", ".")) / "opencode" / "hdfw-hd" / "sine.wav"
BEFORE_MS = 6200
TURN_MS = 6500
AFTER_MS = 7500


def setup(work, zdl, replace_name):
    work.mkdir(parents=True, exist_ok=True)
    for name in ["129_main_OS.bin", "133_data_133.bin", "136_bootloader.bin"]:
        shutil.copy2(FW / name, work / name)
    shutil.copy2(FW / "137_file_system.bin", work / "137_file_system.bin")
    shutil.copy2(SINE, work / "sine.wav")
    repl = work / replace_name
    shutil.copy2(zdl, repl)
    r = subprocess.run(["python", str(FSEDIT), str(FW / "137_file_system.bin"),
                        str(work / "137_file_system.bin"), "--add", str(repl)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)


def run(work, turn, seconds):
    cmd = [str(EMU), "129_main_OS.bin", "-s", str(seconds), "-q", "-flashfast",
           "-wav", "sine.wav", "-snap", f"{BEFORE_MS}:before.png"]
    if turn:
        cmd += ["-turn", f"{TURN_MS}:{turn[0]}:{turn[1]}:{turn[2]}"]
    cmd += ["-snap", f"{AFTER_MS}:after.png"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-2000:])


def samples(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return struct.unpack("<%dh" % (len(raw) // 2), raw)


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x)) / 32768 if x else 0.0


def diff_stats(a, b, start, end):
    n = min(len(a), len(b))
    s, e = min(start, n), min(end, n)
    d = [y - x for x, y in zip(a[s:e], b[s:e])]
    return {"rms": rms(d), "max": max((abs(v) for v in d), default=0)}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("rebuilt")
    ap.add_argument("report")
    ap.add_argument("--replace", default="STCHO.ZDL")
    ap.add_argument("--seconds", type=int, default=11)
    ap.add_argument("--turn", default="17:30:8", help="PA:PB:steps; empty = no turn")
    args = ap.parse_args()
    turn = tuple(int(x) for x in args.turn.split(":")) if args.turn else None

    base = Path(args.report).with_suffix("")
    base.mkdir(parents=True, exist_ok=True)
    orig, rebuilt = Path(args.orig), Path(args.rebuilt)
    cases = {}
    for name, zdl, use_turn in (("orig_base", orig, False),
                                ("orig_turn", orig, True),
                                ("reb_turn", rebuilt, True)):
        work = base / name
        setup(work, zdl, args.replace)
        run(work, turn if use_turn else None, args.seconds)
        a = samples(work / "out.wav")
        cases[name] = {
            "samples": a,
            "before_sha": sha(work / "before.png"),
            "after_sha": sha(work / "after.png"),
            "rms": rms(a[int(7.6 * 44100):int(10.4 * 44100)]),
        }

    start, end = int(7.6 * 44100), int(10.4 * 44100)
    out = {
        "turn": args.turn,
        "replace": args.replace,
        "orig_rms": cases["orig_turn"]["rms"],
        "rebuilt_rms": cases["reb_turn"]["rms"],
        "knob_effect_original": diff_stats(cases["orig_base"]["samples"],
                                           cases["orig_turn"]["samples"], start, end),
        "orig_vs_rebuilt_after_turn": diff_stats(cases["orig_turn"]["samples"],
                                                 cases["reb_turn"]["samples"], start, end),
        "screen_before_equal": cases["orig_turn"]["before_sha"] == cases["reb_turn"]["before_sha"],
        "screen_after_equal": cases["orig_turn"]["after_sha"] == cases["reb_turn"]["after_sha"],
        "orig_after_sha": cases["orig_turn"]["after_sha"],
        "reb_after_sha": cases["reb_turn"]["after_sha"],
    }
    Path(args.report).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
