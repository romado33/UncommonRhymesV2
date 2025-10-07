# scripts/migrate_patterns_add_context.py
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

CANDIDATE_TABLES = ["patterns", "rap_patterns", "pairs"]

def pick_table(cur, preferred: str | None):
    names = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    if preferred and preferred in names:
        return preferred
    for c in CANDIDATE_TABLES:
        if c in names:
            return c
    if not names:
        log.error("No tables found in database.")
        raise SystemExit(1)
    return names[0]

def existing_columns(cur, table: str) -> set[str]:
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}

def ensure_columns(cur, table: str, cols: list[str]):
    have = existing_columns(cur, table)
    for col in cols:
        if col not in have:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")

def ensure_index(cur, table: str, col: str):
    # Only create if the column exists
    have = existing_columns(cur, table)
    if col in have:
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{col} ON {table}({col})")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to patterns db (e.g., data/patterns_small.db)")
    ap.add_argument("--table", help="Table name if not the default (auto-detected otherwise)")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        log.error("DB not found: %s", db_path)
        raise SystemExit(1)

    con = sqlite3.connect(str(db_path))
    try:
        con.isolation_level = None  # autocommit mode for safety
        cur = con.cursor()
        table = pick_table(cur, args.table)

        # Add optional context columns if missing
        cur.execute("BEGIN")
        ensure_columns(cur, table, ["lyric_context", "source_context", "target_context"])
        # Helpful indices (only created if the cols exist)
        for k in ("rime_key", "vowel_key", "coda_key"):
            ensure_index(cur, table, k)
        cur.execute("COMMIT")

        # Show final schema + indices
        log.info("[ok] Updated table: %s", table)
        cols = [row[1] for row in cur.execute(f"PRAGMA table_info({table})")]
        for col in cols:
            log.info("Column: %s", col)
        indices = [row[1] for row in cur.execute(f"PRAGMA index_list({table})")]
        for idx in indices:
            log.info("Index: %s", idx)

    finally:
        con.close()

if __name__ == "__main__":
    main()
