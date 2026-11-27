#!/usr/bin/env python3
"""Render readable L/R sweep spectrograms from saved comparison arrays."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

BASE = Path(r"C:\zoom\zdlnew\SWEEP_KNOBS_STEREOCHO\REPORT")
OUT = BASE
FS = 44100
START, END = 7.6, 10.4
NPERSEG, NOVERLAP = 2048, 1536
BANDS = [(60, 200), (200, 500), (500, 1500), (1500, 4000), (4000, 12000)]


def load(name):
    x = np.load(BASE / name / "out.npy")
    s = int(START * FS)
    e = min(len(x), int(END * FS))
    return x[s:e]


def calc(x):
    f, t, s = spectrogram(x, FS, nperseg=NPERSEG, noverlap=NOVERLAP)
    sel = (f >= 50) & (f <= 15000)
    return f[sel], t, 10.0 * np.log10(s[sel] + 1e-12), s[sel]


def plot_pair(left_name, right_name, left_title, right_title, out, title, diff=False):
    left, right = load(left_name), load(right_name)
    data = {}
    for name, x in ((left_name, left), (right_name, right)):
        for ch in (0, 1):
            data[name, ch] = calc(x[:, ch])
    if diff:
        lo, hi = -12.0, 12.0
    else:
        vals = np.concatenate([data[k, c][2] for k in (left_name, right_name) for c in (0, 1)])
        lo, hi = np.percentile(vals, 1), np.percentile(vals, 99)

    fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharex=True, sharey=True)
    last = None
    for col, (name, subtitle) in enumerate(((left_name, left_title), (right_name, right_title))):
        for row, ch in enumerate((0, 1)):
            f, t, db, _ = data[name, ch]
            if diff:
                f0, t0, db0, _ = data[left_name, ch]
                f1, t1, db1, _ = data[right_name, ch]
                db = db1 - db0
            last = axes[row, col].pcolormesh(t, f, db, shading="auto", vmin=lo, vmax=hi,
                                             cmap="RdBu_r" if diff else "magma")
            axes[row, col].set_yscale("log")
            axes[row, col].set_ylim(60, 14000)
            axes[row, col].set_title(f"{subtitle} {'L' if ch == 0 else 'R'}", fontsize=12)
            if row:
                axes[row, col].set_xlabel("time, s")
            if col == 0:
                axes[row, col].set_ylabel("frequency, Hz")
    fig.suptitle(title, fontsize=15)
    cax = fig.add_axes([0.91, 0.12, 0.014, 0.76])
    cbar = fig.colorbar(last, cax=cax)
    cbar.set_label("dB difference" if diff else "dB")
    fig.subplots_adjust(left=0.08, right=0.88, top=0.90, bottom=0.10,
                        wspace=0.07, hspace=0.18)
    fig.savefig(str(out), dpi=180)
    plt.close(fig)
    return lo, hi


def band_report():
    rows = []
    names = ["orig_before", "orig_after", "rebuilt_after"]
    data = {n: load(n) for n in names}
    for lo, hi in BANDS:
        row = {"band": f"{lo}-{hi} Hz"}
        for n in names:
            total = 0.0
            for ch in (0, 1):
                f, t, db, s = calc(data[n][:, ch])
                sel = (f >= lo) & (f < hi)
                total += float(s[sel].sum())
            row[n] = round(10 * np.log10(total + 1e-12), 2)
        row["orig_knob_delta"] = round(row["orig_after"] - row["orig_before"], 2)
        row["rebuild_delta"] = round(row["rebuilt_after"] - row["orig_after"], 2)
        rows.append(row)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plot_pair("orig_before", "orig_after", "before knob", "after knob",
              OUT / "SPEC_ORIGINAL_LR_BEFORE_AFTER.png",
              "StereoCho original: L/R sweep before and after knob turn")
    plot_pair("orig_after", "rebuilt_after", "original after", "rebuilt after",
              OUT / "SPEC_LR_ORIGINAL_VS_REBUILT_AFTER.png",
              "StereoCho after same knob turn: original vs rebuilt")
    plot_pair("orig_before", "orig_after", "before", "after",
              OUT / "SPEC_DIFF_ORIGINAL_LR_KNOB.png",
              "StereoCho original: after minus before",
              diff=True)
    plot_pair("orig_after", "rebuilt_after", "original", "rebuilt",
              OUT / "SPEC_DIFF_REBUILT_AFTER.png",
              "StereoCho after knob turn: rebuilt minus original",
              diff=True)
    rows = band_report()
    import json
    (OUT / "BANDS.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
