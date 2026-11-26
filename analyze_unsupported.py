#!/usr/bin/env python3
"""Find recurring patterns in unsupported operations of lifted factory ZDL C."""
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

SRC = Path(r"C:\zoom\zdlnew\LIFTED_C")
REPORT = Path(r"C:\zoom\zdlnew\UNSUPPORTED_PATTERNS.md")


def main():
    by_file = {}
    pairs = Counter()
    families = Counter()
    contexts = defaultdict(list)
    for path in sorted(SRC.glob("*.c")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        ops = []
        for i, line in enumerate(lines):
            m = re.search(r"/\* unsupported ([A-Z][A-Z0-9_]*)", line)
            if not m:
                continue
            op = m.group(1)
            ops.append(op)
            if len(contexts[op]) < 3:
                lo, hi = max(0, i - 2), min(len(lines), i + 3)
                contexts[op].append((path.stem, "\n".join(lines[lo:hi])))
        by_file[path.stem] = ops
        for a, b in combinations(sorted(set(ops)), 2):
            pairs[(a, b)] += 1
        m = re.search(r"void (Fx_[A-Za-z0-9_]+)\(", text)
        fam = m.group(1).split("_")[1] if m else "?"
        families[fam] += len(ops)

    total = Counter(op for ops in by_file.values() for op in ops)
    out = ["# Неподдерживаемые операции в lifted C", ""]
    out += ["Всего файлов: %d, операций: %d, видов: %d." %
            (len(by_file), sum(total.values()), len(total)), ""]
    out += ["## Частоты", "", "| op | count | files |", "|---|---:|---:|"]
    files_per_op = Counter()
    for stem, ops in by_file.items():
        for op in set(ops):
            files_per_op[op] += 1
    for op, n in total.most_common(40):
        out.append("| %s | %d | %d |" % (op, n, files_per_op[op]))
    out += ["", "## Совстречаемость в одном эффекте", "", "| pair | files |", "|---|---:|"]
    for (a, b), n in pairs.most_common(30):
        out.append("| %s + %s | %d |" % (a, b, n))
    out += ["", "## Семейства аудиофункций", "", "| family | ops |", "|---|---:|"]
    for fam, n in families.most_common(20):
        out.append("| Fx_%s_* | %d |" % (fam, n))
    out += ["", "## Примеры контекста", ""]
    for op, _ in total.most_common(14):
        out.append("### %s" % op)
        for stem, ctx in contexts[op]:
            out.append("`%s`:" % stem)
            out.append("```c")
            out.append(ctx)
            out.append("```")
        out.append("")
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("report", REPORT)
    print("ops", sum(total.values()), "kinds", len(total))
    print("top", total.most_common(12))
    print("pairs", pairs.most_common(12))
    print("families", families.most_common(12))


if __name__ == "__main__":
    main()
