from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

def open_db(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        log.error("DB not found: %s", path)
        sys.exit(1)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

def main():
    ap = argparse.ArgumentParser(description="Create a small excerpt of patterns.db with key columns.")
    ap.add_argument("--src", default="data/patterns.db")
    ap.add_argument("--dst", default="data/patterns_small.db")
    ap.add_argument("--table", default="song_rhyme_patterns")
    ap.add_argument("--key1", default="last_word_rime_key")
    ap.add_argument("--key2", default="last_two_syllables_key")
    ap.add_argument("--limit-per-key", type=int, default=50)
    args = ap.parse_args()

    src = open_db(args.src); scur = src.cursor()
    # Create destination table with same schema
    dst = sqlite3.connect(args.dst); dcur = dst.cursor()
    cols = [r[1] for r in scur.execute(f"PRAGMA table_info({args.table})").fetchall()]
    if not cols:
        log.error("Could not read columns for table '%s' in %s", args.table, args.src)
        sys.exit(1)

    dcur.executescript("""
        DROP TABLE IF EXISTS patterns;
    """)
    col_defs = ", ".join(f'"{c}"' for c in cols)
    dcur.executescript(f'CREATE TABLE patterns ({col_defs});')

    # Build excerpt by iterating distinct keys
    def sample_for_key(col):
        if col not in cols:
            return []
        keys = [r[0] for r in scur.execute(
            f'SELECT DISTINCT "{col}" FROM {args.table} WHERE "{col}" IS NOT NULL AND "{col}" != ""'
        ).fetchall()]
        out = []
        for k in keys:
            out += scur.execute(
                f'SELECT * FROM {args.table} WHERE "{col}"=? LIMIT ?',
                (k, args.limit_per_key)
            ).fetchall()
        return out

    rows = sample_for_key(args.key1) + sample_for_key(args.key2)
    # Dedup rows
    seen = set(); dedup = []
    for r in rows:
        sig = tuple(r[c] for c in cols)
        if sig in seen: 
            continue
        seen.add(sig); dedup.append(r)

    if not dedup:
        log.error("No rows selected; did you run the migration to add key columns?")
        sys.exit(1)

    placeholders = ",".join(["?"]*len(cols))
    dcur.executemany(f'INSERT INTO patterns({",".join(cols)}) VALUES ({placeholders})',
                     [tuple(r[c] for c in cols) for r in dedup])
    # Indexes
    if "last_word_rime_key" in cols:
        dcur.execute('CREATE INDEX IF NOT EXISTS idx_last_word_rime_key ON patterns(last_word_rime_key)')
    if "last_two_syllables_key" in cols:
        dcur.execute('CREATE INDEX IF NOT EXISTS idx_last_two_syllables_key ON patterns(last_two_syllables_key)')
    dst.commit(); dst.close(); src.close()
    log.info("[ok] Wrote %s rows to %s with indexes on keys.", len(dedup), args.dst)
if __name__ == "__main__":
    main()
