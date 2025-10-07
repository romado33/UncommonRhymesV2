from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con

def ensure_columns(cur, table: str, cols):
    # cols: [(name, type)]
    existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, typ in cols:
        if name not in existing:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN {name} {typ}')

def table_exists(cur, table: str) -> bool:
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone()
    return bool(row)

def main():
    ap = argparse.ArgumentParser(
        description="Add K1/K2 rhyme keys to a patterns table using words_index.sqlite."
    )
    ap.add_argument("--patterns", default="data/patterns_small.db",
                    help="Path to patterns DB (default: data/patterns_small.db)")
    ap.add_argument("--words", default="data/words_index.sqlite",
                    help="Path to words index DB (default: data/words_index.sqlite)")
    ap.add_argument("--table", default="song_rhyme_patterns",
                    help="Patterns table name")
    ap.add_argument("--word-col", default="target_word",
                    help="Which column to use for keying (target_word or source_word)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Optional cap for number of rows to process (0 = all)")
    args = ap.parse_args()

    # Open DBs
    pcon = open_db(args.patterns)
    wcon = open_db(args.words)
    pcur = pcon.cursor(); wcur = wcon.cursor()

    # Verify table exists
    if not table_exists(pcur, args.table):
        log.error("Table '%s' was not found in %s", args.table, args.patterns)
        sys.exit(2)

    # Ensure columns exist
    ensure_columns(pcur, args.table, [
        ("last_word_rime_key", "TEXT"),
        ("last_two_syllables_key", "TEXT"),
    ])
    pcon.commit()

    # Prepare queries
    sel = f'SELECT id, {args.word_col} AS w FROM {args.table}'
    if args.limit > 0:
        sel += f' LIMIT {args.limit}'
    rows = pcur.execute(sel).fetchall()

    # Words index holds JSON strings for k1/k2 already
    wsel = "SELECT k1, k2 FROM words WHERE word = ?"

    updated = 0; missing = 0
    for r in rows:
        wid = r["id"]; w = (r["w"] or "").strip().lower()
        if not w:
            missing += 1
            continue
        wrow = wcur.execute(wsel, (w,)).fetchone()
        if not wrow:
            # try stripping punctuation (simple heuristic)
            w2 = "".join(ch for ch in w if ch.isalpha() or ch in "'-").lower()
            if w2 != w:
                wrow = wcur.execute(wsel, (w2,)).fetchone()
        if not wrow:
            missing += 1
            continue

        # k1/k2 are already JSON in words_index.sqlite -> copy as-is
        k1_json = wrow["k1"]
        k2_json = wrow["k2"]
        pcur.execute(
            f'UPDATE {args.table} SET last_word_rime_key=?, last_two_syllables_key=? WHERE id=?',
            (k1_json, k2_json, wid)
        )
        updated += 1
        if updated % 1000 == 0:
            pcon.commit()

    pcon.commit()
    # Indexes for fast lookup
    pcur.execute(f'CREATE INDEX IF NOT EXISTS idx_last_word_rime_key ON {args.table}(last_word_rime_key)')
    pcur.execute(f'CREATE INDEX IF NOT EXISTS idx_last_two_syllables_key ON {args.table}(last_two_syllables_key)')
    pcon.commit()

    log.info("[ok] Updated rows: %s; missing keys: %s", updated, missing)
    pcon.close(); wcon.close()

if __name__ == "__main__":
    main()
