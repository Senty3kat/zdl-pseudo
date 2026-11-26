"""Parallel full-emulator audio check for every rebuilt ZDL in BATCH_ALL.csv."""
import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import full_audio_compare as fac

HERE = Path(__file__).resolve().parent
IN_DIR = Path(r"C:\Users\arsen\AppData\Local\Temp\opencode\em_named")
BATCH = Path(r"C:\zoom\zdlnew\BATCH_ALL.csv")
BUILT = Path(r"C:\Users\arsen\AppData\Local\Temp\opencode\batch")
FULL = Path(r"C:\zoom\zdlnew\FULL_AUDIO")


def built_names():
    names = []
    for line in BATCH.read_text(encoding="utf-8").splitlines()[2:]:
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 3 and parts[2] == "ok":
            names.append(parts[0])
    return names


def check(name, seconds):
    report = FULL / f"{name}.json"
    try:
        r = fac.compare(IN_DIR / f"{name}.ZDL", BUILT / name / "rebuilt.ZDL",
                        report, seconds=seconds)
        status = "equal" if r["byte_equal"] and r["screen_equal"] else "diff"
        return (name, status, "%.8f" % r["rms_diff"], r["max_sample_diff"])
    except Exception as e:
        return (name, "error", str(e)[:120], 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(Path(r"C:\zoom\zdlnew\FULL_AUDIO_ALL.csv")))
    a = ap.parse_args()
    FULL.mkdir(parents=True, exist_ok=True)
    names = built_names()
    print("effects", len(names), "seconds", a.seconds, "workers", a.workers, flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(check, n, a.seconds): n for n in names}
        for i, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            rows.append(row)
            if i % 25 == 0:
                print(i, "done", flush=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Effect", "Audio", "RMSDiff", "MaxSampleDiff"])
        w.writerows(rows)
    equal = sum(1 for r in rows if r[1] == "equal")
    diff = sum(1 for r in rows if r[1] == "diff")
    err = sum(1 for r in rows if r[1] == "error")
    print("report", a.out, "equal", equal, "diff", diff, "error", err, flush=True)


if __name__ == "__main__":
    main()
