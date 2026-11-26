#!/usr/bin/env python3
"""Copy every lifted C file from the batch workspace into a durable folder."""
import csv
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH = Path(r"C:\Users\arsen\AppData\Local\Temp\opencode\batch")
BATCH_CSV = Path(r"C:\zoom\zdlnew\BATCH_ALL.csv")
OUT = Path(r"C:\zoom\zdlnew\LIFTED_C")
INDEX = Path(r"C:\zoom\zdlnew\LIFTED_C_INDEX.csv")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in BATCH_CSV.read_text(encoding="utf-8").splitlines()[2:]:
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        name, func, build, _audio, size = parts[:5]
        if build != "ok":
            continue
        src = BATCH / name / "effect.c"
        if not src.is_file():
            rows.append((name, func, 0, "missing", 0, 0))
            continue
        text = src.read_text(encoding="utf-8")
        dst = OUT / f"{name}.c"
        shutil.copy2(src, dst)
        rows.append((name, func, len(text.encode("utf-8")),
                     text.count("__unknown"), text.count("unsupported"),
                     text.count("    return;")))
    with open(INDEX, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Effect", "Func", "Bytes", "UnknownOps", "UnsupportedOps", "FallbackReturns"])
        w.writerows(rows)
    print("copied", len(rows), "files to", OUT)
    print("index", INDEX)


if __name__ == "__main__":
    main()
