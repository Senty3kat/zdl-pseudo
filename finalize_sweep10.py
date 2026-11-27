#!/usr/bin/env python3
"""Validate names, collect Reb_* files and render L/R sweep spectrograms."""
import hashlib
import json
import os
import shutil
import wave
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

HERE = Path(__file__).resolve().parent
OUT = Path(r"C:\zoom\zdlnew\SWEEP10_NATIVE")
SRC = Path(os.environ.get("TEMP", ".")) / "opencode" / "em_named"
REBUILDS = Path(r"C:\zoom\zdlnew\REBUILDS")
FS = 44100
START, END = 7.6, 10.4


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        fs = w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(float) / 32768.0
    return fs, x


def rms(x):
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def diff(a, b):
    n = min(len(a), len(b))
    s, e = min(int(START * FS), n), min(int(END * FS), n)
    return {"rms": rms(b[s:e] - a[s:e]),
            "max": float(np.max(np.abs(b[s:e] - a[s:e]))) if e > s else 0.0}


def image_sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None


def plot_pair(base, name, left, right, left_title, right_title, title, diff_mode=False):
    data = {}
    for key, arr in ((left[0], left[1]), (right[0], right[1])):
        for ch in (0, 1):
            f, t, s = spectrogram(arr[:, ch], FS, nperseg=2048, noverlap=1536)
            sel = (f >= 50) & (f <= 15000)
            data[key, ch] = (f[sel], t, 10 * np.log10(s[sel] + 1e-12))
    if diff_mode:
        lo, hi = -12, 12
    else:
        vals = np.concatenate([v[2] for v in data.values()])
        lo, hi = np.percentile(vals, 1), np.percentile(vals, 99)
    fig, axes = plt.subplots(2, 2, figsize=(15, 8), sharex=True, sharey=True)
    last = None
    k0 = left[0]
    for col, (k1, t1) in enumerate(((left[0], left_title), (right[0], right_title))):
        for row, ch in enumerate((0, 1)):
            f, t, db = data[k1, ch]
            if diff_mode and k1 == right[0]:
                db = db - data[k0, ch][2]
            last = axes[row, col].pcolormesh(t, f, db, shading="auto", vmin=lo, vmax=hi,
                                             cmap="RdBu_r" if diff_mode else "magma")
            axes[row, col].set_yscale("log")
            axes[row, col].set_ylim(60, 14000)
            axes[row, col].set_title(f"{t1} {'L' if ch == 0 else 'R'}", fontsize=11)
            if row:
                axes[row, col].set_xlabel("time, s")
            if col == 0:
                axes[row, col].set_ylabel("frequency, Hz")
    fig.suptitle(title, fontsize=14)
    cax = fig.add_axes([0.91, 0.12, 0.014, 0.76])
    fig.colorbar(last, cax=cax, label="dB diff" if diff_mode else "dB")
    fig.subplots_adjust(left=0.08, right=0.88, top=0.90, bottom=0.10,
                        wspace=0.07, hspace=0.18)
    path = base / f"SPEC_{name}_{'DIFF' if diff_mode else 'LR'}.png"
    fig.savefig(str(path), dpi=170)
    plt.close(fig)
    return path


def main():
    index = json.loads((OUT / "INDEX.json").read_text(encoding="utf-8"))
    report = []
    REBUILDS.mkdir(parents=True, exist_ok=True)
    for row in index:
        name = row["effect"]
        if "_1" in name or "(1)" in name or name.startswith("Reb_"):
            raise ValueError(f"bad original name: {name}")
        work = OUT / name
        orig = SRC / f"{name}.ZDL"
        rebuilt = work / f"Reb_{name}.ZDL"
        if not rebuilt.exists():
            rebuilt = work / "rebuilt.ZDL"
            if not rebuilt.exists():
                print("missing rebuilt", name)
                continue
        target = REBUILDS / f"Reb_{name}.ZDL"
        target.write_bytes(rebuilt.read_bytes())
        before_wav = work / "orig_before" / "out.wav"
        after_wav = work / "orig_after" / "out.wav"
        reb_wav = work / "reb_after" / "out.wav"
        if not (before_wav.exists() and after_wav.exists() and reb_wav.exists()):
            print("missing wav", name)
            continue
        _, before = read_wav(before_wav)
        _, after = read_wav(after_wav)
        _, reb = read_wav(reb_wav)
        entry = {
            "effect": name,
            "original": str(orig),
            "rebuilt": str(target),
            "fxid": row.get("fxid"),
            "gid": row.get("gid"),
            "screen_after_equal": image_sha(work / "orig_after" / "after.png") ==
                                  image_sha(work / "reb_after" / "after.png"),
            "orig_knob_effect": diff(before, after),
            "orig_vs_rebuilt_after": diff(after, reb),
        }
        base = work / "SPEC"
        base.mkdir(parents=True, exist_ok=True)
        entry["spec_before_after"] = str(plot_pair(
            base, name + "_BEFORE_AFTER",
            ("orig_before", before), ("orig_after", after),
            "before", "after", f"{name}: original before/after knob"))
        entry["spec_orig_vs_rebuilt"] = str(plot_pair(
            base, name + "_ORIG_VS_REB",
            ("orig_after", after), ("reb_after", reb),
            "original", "rebuilt", f"{name}: original vs rebuilt after knob",
            diff_mode=False))
        report.append(entry)
        print(name, "knob", entry["orig_knob_effect"]["rms"],
              "diff", entry["orig_vs_rebuilt_after"]["rms"])
    out = OUT / "FINAL_REPORT.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("report", out)


if __name__ == "__main__":
    main()
