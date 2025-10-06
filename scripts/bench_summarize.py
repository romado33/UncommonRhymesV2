#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Produce a concise Markdown summary from results/benchmark.csv.
"""

import csv, argparse
from pathlib import Path
from collections import defaultdict

BUCKET_COLS = {
    "uncommon": "uncommon_items",
    "slant":    "slant_items",
    "multi":    "multiword_items",
    "rap":      "rap_items",
}

def parse_set(cell: str):
    if not cell:
        return set()
    return set(s.strip() for s in cell.split("|") if s.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/benchmark.csv")
    ap.add_argument("--out", default="results/summary.md")
    args = ap.parse_args()

    with Path(args.csv).open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_query = defaultdict(dict)
    for r in rows:
        by_query[r["query"]][r["condition"]] = r

    total_added = total_removed = 0
    golden_warns = golden_fails = 0
    err_count = 0

    lines = []
    lines.append("## 🔎 Uncommon Rhymes – Benchmark Summary\n")

    for q in sorted(by_query.keys()):
        conds = by_query[q]
        base = conds.get("baseline")
        if not base:
            continue

        base_sets = {b: parse_set(base[BUCKET_COLS[b]]) for b in BUCKET_COLS}

        gs = (base.get("golden_status") or "").upper()
        if "FAIL" in gs: golden_fails += 1
        elif "WARN" in gs: golden_warns += 1

        errs = []
        for ek in ("error_search","error_patterns","error_prosody"):
            if base.get(ek):
                errs.append(f"{ek}:{base[ek]}")
                err_count += 1

        lines.append(f"### Query: `{q}`")
        counts = f"Uncommon {base['uncommon_count']}, Slant {base['slant_count']}, Multi {base['multiword_count']}, Rap {base['rap_count']}"
        flags = []
        if base.get("consonant_violation","").lower() == "true": flags.append("**ConsonantLeak**")
        if gs: flags.append(f"Golden={gs}")
        if errs: flags.append(f"Errors={'; '.join(errs)}")
        flag_str = (" — " + " | ".join(flags)) if flags else ""
        lines.append(f"- Baseline counts: {counts}{flag_str}")

        for cond, row in sorted(conds.items()):
            if cond == "baseline": continue
            added_any = removed_any = 0
            diffs = []
            for b, col in BUCKET_COLS.items():
                cur = parse_set(row[col])
                add = sorted(cur - base_sets[b])
                rem = sorted(base_sets[b] - cur)
                if add or rem:
                    diffs.append(f"  - **{b.title()}**: +{len(add)} / -{len(rem)}")
                    added_any += len(add); removed_any += len(rem)

            if diffs:
                total_added += added_any; total_removed += removed_any
                lines.append(f"- Condition `{cond}` diffs vs baseline:")
                lines.extend(diffs)
        lines.append("")

    lines.insert(1, f"- Total additions across conditions: **{total_added}**, removals: **{total_removed}**")
    lines.insert(2, f"- Golden WARNs: **{golden_warns}**, FAILs: **{golden_fails}**")
    lines.insert(3, f"- Rows with errors: **{err_count}**")
    lines.append("\n_Artifacts_: `benchmark.csv`, `benchmark_report.html`, and `benchmark.queries_used.txt` are attached to this run.")

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Wrote {outp}")

if __name__ == "__main__":
    main()
