"""Full-emulator audio comparison for an already rebuilt batch."""
import argparse
import csv
import json
import os
from pathlib import Path

import full_audio_compare as fac

TMP = Path(os.environ.get("TEMP", ".")) / "opencode"
HERE = Path(__file__).resolve().parent
BATCH = TMP / "batch"
FULL = Path(r"C:\zoom\zdlnew\FULL_AUDIO")


def built_names(batch_csv):
    names = []
    lines = Path(batch_csv).read_text(encoding="utf-8").splitlines()
    for line in lines[2:]:
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 3 and parts[2] == "ok":
            names.append(parts[0])
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_dir")
    ap.add_argument("batch_csv")
    ap.add_argument("out_csv")
    ap.add_argument("limit", type=int)
    ap.add_argument("start", type=int)
    ap.add_argument("--seconds", type=int, default=8)
    a = ap.parse_args()

    FULL.mkdir(parents=True, exist_ok=True)
    names = built_names(a.batch_csv)[a.start:a.start + a.limit]
    rows = []
    for name in names:
        orig = Path(a.in_dir) / f"{name}.ZDL"
        reb = BATCH / name / "rebuilt.ZDL"
        report = FULL / f"{name}.json"
        try:
            r = fac.compare(orig, reb, report, a.seconds)
            status = "equal" if r["byte_equal"] and r["screen_equal"] else "diff"
            rows.append((name, status, "%.8f" % r["rms_diff"], r["max_sample_diff"]))
        except Exception as e:
            rows.append((name, "error", str(e)[:120], 0))
        print(name, rows[-1][1], rows[-1][2])
    with open(a.out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Effect", "Audio", "RMSDiff", "MaxSampleDiff"])
        w.writerows(rows)
    print("report", a.out_csv)


if __name__ == "__main__":
    main()
