#!/usr/bin/env python3
"""Re-check only the 50 worst audio diffs with the current emitter."""
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

TMP = Path(os.environ.get("TEMP", ".")) / "opencode"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import batch_rebuild as b
import full_audio_compare as f

REPORT = Path(r"C:\zoom\zdlnew\FULL_AUDIO_ALL_FARDATA.csv")
BATCH = Path(r"C:\zoom\zdlnew\BATCH_ALL.csv")
SRC = TMP / "em_named"
WORK = Path(r"C:\zoom\zdlnew\WORST50_STW_FIX")
OUT = Path(r"C:\zoom\zdlnew\WORST50_STW_FIX.csv")


def load_funcs():
    out = {}
    for line in BATCH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("|---") or "Effect" in line:
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 2 and parts[2] == "ok":
            out[parts[0]] = parts[1]
    return out


def load_worst():
    rows = list(csv.DictReader(REPORT.open(encoding="utf-8")))
    diff = [r for r in rows if r["Audio"] != "equal"]
    diff.sort(key=lambda r: float(r["RMSDiff"]), reverse=True)
    return diff[:50]


def one(row, funcs):
    name = row["Effect"]
    func = funcs.get(name)
    src = SRC / (name + ".ZDL")
    if not func or not src.exists():
        return {"Effect": name, "Status": "skip", "Reason": "missing func or zdl"}
    work = WORK / name
    (work / "build").mkdir(parents=True, exist_ok=True)
    try:
        rebuilt = b.rebuild(src, func, work / "build")
        rep = f.compare(src, rebuilt, work / "cmp.json", seconds=4)
        return {
            "Effect": name,
            "Status": "steady_equal" if rep["steady_equal_1lsb"] and rep["screen_equal"] else "diff",
            "OldRMSDiff": row["RMSDiff"],
            "RMSDiff": rep["rms_diff"],
            "SteadyRMSDiff": rep["steady_rms_diff"],
            "MaxDiff": rep["max_sample_diff"],
            "Screen": rep["screen_equal"],
        }
    except Exception as ex:
        return {"Effect": name, "Status": "error", "Reason": repr(ex)}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    funcs = load_funcs()
    rows = load_worst()
    results = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, row, funcs) for row in rows]
        for i, fut in enumerate(as_completed(futures)):
            results[i] = fut.result()
            print(i + 1, "/", len(rows), results[i]["Effect"], results[i]["Status"],
                  results[i].get("RMSDiff", ""), flush=True)
    fields = ["Effect", "Status", "OldRMSDiff", "RMSDiff", "SteadyRMSDiff",
              "MaxDiff", "Screen", "Reason"]
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in sorted(results, key=lambda r: -float(r.get("RMSDiff") or 0)):
            writer.writerow(r)


if __name__ == "__main__":
    main()
