"""Compare original and rebuilt ZDL in full c6xboot with a one-effect FS."""
import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EMU = Path(os.environ.get("C6XBOOT", str(ROOT / "emulator" / "build" / "c6xboot.exe")))
FSEDIT = ROOT / "emulator" / "tools" / "fsedit.py"
FW = ROOT / "vst_zdl" / "fw70"
SINE = Path(r"C:\Users\arsen\AppData\Local\Temp\opencode\hdfw-hd\sine.wav")
FW_FILES = ["129_main_OS.bin", "133_data_133.bin", "136_bootloader.bin"]


def fsname(path):
    base = Path(path).name.upper()
    stem, _, ext = base.rpartition(".")
    return f"{stem[:8]}.{ext[:3]}"


def stock_zdl_names():
    tmp = Path(r"C:\Users\arsen\AppData\Local\Temp\opencode\fs-list-tmp.bin")
    r = subprocess.run([ "python", str(FSEDIT), str(FW / "137_file_system.bin"),
                         str(tmp), "--list" ], capture_output=True, text=True)
    names = []
    for line in (r.stdout + r.stderr).splitlines():
        parts = line.split()
        if parts and parts[0].upper().endswith(".ZDL"):
            names.append(parts[0])
    return names


def prepare_fs(work, zdl, target, remove):
    work.mkdir(parents=True, exist_ok=True)
    for name in FW_FILES:
        shutil.copy2(FW / name, work / name)
    local_zdl = work / target
    shutil.copy2(zdl, local_zdl)
    args = ["python", str(FSEDIT), str(FW / "137_file_system.bin"),
            str(work / "137_file_system.bin"), "--remove", *remove, "--add", str(local_zdl)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)
    shutil.copy2(SINE, work / "sine.wav")


def run_emu(work, seconds, snap_ms=None):
    if snap_ms is None:
        snap_ms = max(1000, min(6500, seconds * 1000 - 500))
    cmd = [str(EMU), "129_main_OS.bin", "-s", str(seconds), "-q", "-flashfast",
           "-wav", "sine.wav", "-snap", f"{snap_ms}:screen.png"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-2000:])
    return work / "out.wav"


def stats(path):
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    rms = math.sqrt(sum(x * x for x in s) / len(s)) / 32768 if s else 0.0
    peak = max((abs(x) for x in s), default=0) / 32768
    return s, rms, peak


def compare(orig, rebuilt, report, seconds=8, snap_ms=None):
    base = Path(report).with_suffix("")
    base.mkdir(parents=True, exist_ok=True)
    target = fsname(orig)
    remove = [n for n in stock_zdl_names() if n != target]
    results = {}
    for kind, zdl in (("orig", orig), ("reb", rebuilt)):
        work = base / kind
        prepare_fs(work, zdl, target, remove)
        run_emu(work, seconds, snap_ms)
        s, rms, peak = stats(work / "out.wav")
        results[kind] = {"samples": s, "rms": rms, "peak": peak,
                         "screen": (work / "screen.png").read_bytes()}
    a0, a1 = results["orig"]["samples"], results["reb"]["samples"]
    diff = [y - x for x, y in zip(a0, a1)]
    out = {
        "target": target,
        "orig_rms": results["orig"]["rms"],
        "reb_rms": results["reb"]["rms"],
        "rms_diff": math.sqrt(sum(x * x for x in diff) / len(diff)) / 32768 if diff else 0.0,
        "max_sample_diff": max((abs(x) for x in diff), default=0),
        "byte_equal": (base / "orig" / "out.wav").read_bytes() == (base / "reb" / "out.wav").read_bytes(),
        "screen_equal": results["orig"]["screen"] == results["reb"]["screen"],
        "orig_peak": results["orig"]["peak"],
        "reb_peak": results["reb"]["peak"],
    }
    Path(report).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("rebuilt")
    ap.add_argument("report")
    ap.add_argument("--seconds", type=int, default=8)
    a = ap.parse_args()
    print(json.dumps(compare(a.orig, a.rebuilt, a.report, a.seconds), ensure_ascii=False))


if __name__ == "__main__":
    main()
