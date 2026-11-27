#!/usr/bin/env python3
"""Sweep-based UI knob check with clear L/R spectrograms."""
import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import spectrogram

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EMU = ROOT / "emulator" / "build" / "c6xboot.exe"
FSEDIT = ROOT / "emulator" / "tools" / "fsedit.py"
FW = ROOT / "vst_zdl" / "fw70"

BEFORE_MS = 6200
TURN_MS = 6500
AFTER_MS = 7500


def setup(work, zdl, replace_name, sweep):
    work.mkdir(parents=True, exist_ok=True)
    for name in ["129_main_OS.bin", "133_data_133.bin", "136_bootloader.bin"]:
        shutil.copy2(FW / name, work / name)
    shutil.copy2(FW / "137_file_system.bin", work / "137_file_system.bin")
    shutil.copy2(sweep, work / "sweep.wav")
    repl = work / replace_name
    shutil.copy2(zdl, repl)
    r = subprocess.run(["python", str(FSEDIT), str(FW / "137_file_system.bin"),
                        str(work / "137_file_system.bin"), "--add", str(repl)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)


def run(work, turn, seconds):
    cmd = [str(EMU), "129_main_OS.bin", "-s", str(seconds), "-q", "-flashfast",
           "-wav", "sweep.wav", "-snap", f"{BEFORE_MS}:before.png"]
    if turn:
        cmd += ["-turn", f"{TURN_MS}:{turn[0]}:{turn[1]}:{turn[2]}"]
    cmd += ["-snap", f"{AFTER_MS}:after.png"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-2000:])


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        fs = w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768.0
    return fs, x


def rms(x):
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def diff(a, b, start_sec, end_sec, fs):
    n = min(len(a), len(b))
    s, e = min(int(start_sec * fs), n), min(int(end_sec * fs), n)
    d = b[s:e] - a[s:e]
    return {
        "rms": rms(d),
        "max": float(np.max(np.abs(d))) if len(d) else 0.0,
    }


def spec_bytes(x, fs):
    f, t, s = spectrogram(x, fs, nperseg=1024, noverlap=768)
    return f, t, 10.0 * np.log10(s + 1e-12)


def save_spec(path, cases, fs, title):
    fig, axes = plt.subplots(2, len(cases), figsize=(7 * len(cases), 7),
                             sharex=True, sharey=True)
    if len(cases) == 1:
        axes = np.array([axes]).T
    lo, hi = None, None
    data = {}
    for name, x in cases:
        for ch in (0, 1):
            data[name, ch] = spec_bytes(x[:, ch], fs)
            d = data[name, ch][2]
            a, b = np.percentile(d, 2), np.percentile(d, 98)
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
    for col, (name, _) in enumerate(cases):
        for row, ch in enumerate((0, 1)):
            f, t, d = data[name, ch]
            axes[row, col].pcolormesh(t, f, d, shading="auto", vmin=lo, vmax=hi,
                                      cmap="magma")
            axes[row, col].set_yscale("log")
            axes[row, col].set_ylim(60, 15000)
            axes[row, col].set_title(f"{name} {'L' if ch == 0 else 'R'}", fontsize=12)
            if row:
                axes[row, col].set_xlabel("time, s")
            if col == 0:
                axes[row, col].set_ylabel("frequency, Hz")
    fig.suptitle(title, fontsize=15)
    fig.colorbar(axes[0, 0].collections[0], ax=axes, label="dB")
    fig.tight_layout()
    fig.savefig(str(path), dpi=170)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("rebuilt")
    ap.add_argument("report")
    ap.add_argument("--sweep")
    ap.add_argument("--replace", default="STCHO.ZDL")
    ap.add_argument("--seconds", type=int, default=12)
    ap.add_argument("--turn", default="17:30:8")
    ap.add_argument("--start", type=float, default=7.6)
    ap.add_argument("--end", type=float, default=10.4)
    args = ap.parse_args()
    sweep = Path(args.sweep)
    turn = tuple(int(x) for x in args.turn.split(":"))
    base = Path(args.report).with_suffix("")
    base.mkdir(parents=True, exist_ok=True)

    cases = {}
    for name, zdl, use_turn in (("orig_before", Path(args.orig), False),
                                ("orig_after", Path(args.orig), True),
                                ("rebuilt_after", Path(args.rebuilt), True)):
        work = base / name
        setup(work, zdl, args.replace, sweep)
        run(work, turn if use_turn else None, args.seconds)
        fs, x = read_wav(work / "out.wav")
        cases[name] = x
        np.save(work / "out.npy", x)

    save_spec(base / "SPEC_LR_BEFORE_AFTER_ORIGINAL.png",
              [("orig_before", cases["orig_before"]),
               ("orig_after", cases["orig_after"])], fs,
              "StereoCho original: L/R before and after knob turn")
    save_spec(base / "SPEC_LR_ORIGINAL_VS_REBUILT_AFTER.png",
              [("orig_after", cases["orig_after"]),
               ("rebuilt_after", cases["rebuilt_after"])], fs,
              "After same knob turn: original vs rebuilt")

    out = {
        "turn": args.turn,
        "sweep": str(sweep),
        "orig_before_rms": rms(cases["orig_before"]),
        "orig_after_rms": rms(cases["orig_after"]),
        "rebuilt_after_rms": rms(cases["rebuilt_after"]),
        "orig_knob_effect": diff(cases["orig_before"], cases["orig_after"],
                                 args.start, args.end, fs),
        "orig_vs_rebuilt_after": diff(cases["orig_after"], cases["rebuilt_after"],
                                      args.start, args.end, fs),
        "spec_before_after": str(base / "SPEC_LR_BEFORE_AFTER_ORIGINAL.png"),
        "spec_orig_vs_rebuilt": str(base / "SPEC_LR_ORIGINAL_VS_REBUILT_AFTER.png"),
    }
    Path(args.report).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
