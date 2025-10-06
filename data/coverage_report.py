#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan the benchmark CSV and print simple coverage stats:
- queries touched
- buckets with changes (vs baseline) per query
- rarity proxy coverage (counts by '::' presence; you can extend to parse rarity if exposed)
- quick heat for which buckets change most under LLM flags
"""

import csv, argparse
from pathlib import Path
from collections import defaultdict, Counter

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
    args = ap.parse_args()

    with Path(args.csv).open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_query = defaultdict(dict)
    for r in rows:
        by_query[r["query"]][r["condition"]] = r

    bucket_changes = Counter()
    queries = sorted(by_query.keys())
    print(f"Queries: {len(queries)}")
    for q in queries:
        conds = by_query[q]
        base = conds.get("baseline")
        if not base: continue
        base_sets = {b: parse_set(base[BUCKET_COLS[b]]) for b in BUCKET_COLS}
        for cond, row in conds.items():
            if cond == "baseline": continue
            for b, col in BUCKET_COLS.items():
                cur = parse_set(row[col])
                add = cur - base_sets[b]
                rem = base_sets[b] - cur
                if add or rem:
                    bucket_changes[b] += 1

    print("Buckets with changes (count of queries impacted):")
    for b, c in bucket_changes.most_common():
        print(f" - {b}: {c}")

if __name__ == "__main__":
    main()
