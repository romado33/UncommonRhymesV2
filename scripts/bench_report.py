#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate a minimal HTML diff report from results/benchmark.csv."""

import argparse
import csv
import html
import logging
from collections import defaultdict
from pathlib import Path

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

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
    ap.add_argument("--out", default="results/benchmark_report.html")
    args = ap.parse_args()

    with Path(args.csv).open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_query = defaultdict(dict)
    for r in rows:
        by_query[r["query"]][r["condition"]] = r

    parts = []
    parts.append("<!doctype html><meta charset='utf-8'><title>Uncommon Rhymes – Benchmark Diff</title>")
    parts.append("<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;padding:24px;} h2{margin-top:32px} code{background:#f6f8fa;padding:2px 4px;border-radius:3px} .add{color:#0a7;} .rem{color:#c33;} .bucket{margin:6px 0 14px;} .cond{margin:10px 0;} .dim{color:#666} .mono{font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:13px;}</style>")
    parts.append("<h1>Benchmark Diff Report</h1>")
    parts.append(f"<p class='dim mono'>Source CSV: {html.escape(args.csv)}</p>")

    for q in sorted(by_query.keys()):
        parts.append(f"<h2>Query: <code>{html.escape(q)}</code></h2>")
        conds = by_query[q]
        base = conds.get("baseline")
        if not base:
            parts.append("<p class='dim'>No baseline row found.</p>")
            continue

        baseline_sets = {bucket: parse_set(base[BUCKET_COLS[bucket]]) for bucket in BUCKET_COLS}

        parts.append("<div class='bucket'><strong>Baseline counts</strong>: "
                     f"Uncommon {base['uncommon_count']}, Slant {base['slant_count']}, "
                     f"Multi {base['multiword_count']}, Rap {base['rap_count']}. "
                     f"<span class='dim'>Golden: {html.escape(base.get('golden_status',''))}</span></div>")

        for cond, row in conds.items():
            if cond == "baseline":
                continue
            parts.append(f"<div class='cond'><strong>Condition:</strong> <code>{html.escape(cond)}</code></div>")
            for bucket, col in BUCKET_COLS.items():
                cur = parse_set(row[col])
                base_set = baseline_sets[bucket]
                added = sorted(cur - base_set)
                removed = sorted(base_set - cur)
                if not added and not removed:
                    continue
                parts.append(f"<div class='bucket'><em>{bucket.title()}</em>: ")
                if added:
                    parts.append(" + " + " , ".join(f"<span class='add'>{html.escape(x)}</span>" for x in added))
                if removed:
                    parts.append(" − " + " , ".join(f"<span class='rem'>{html.escape(x)}</span>" for x in removed))
                parts.append("</div>")

            extra = []
            if row.get("rap_empty_reason"):
                extra.append(f"rap_reason={html.escape(row['rap_empty_reason'])}")
            for ek in ("error_search","error_patterns"):
                if row.get(ek):
                    extra.append(f"{ek}={html.escape(row[ek])}")
            if extra:
                parts.append(f"<div class='dim mono'>{' | '.join(extra)}</div>")

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(parts), encoding="utf-8")
    log.info("📄 Wrote HTML report → %s", outp)

if __name__ == "__main__":
    main()
