# scripts/migrate_words_add_tail_keys.py
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from rhyme_core.logging_utils import setup_logging
from rhyme_core.phonetics import parse_pron_field, tail_keys

setup_logging()
log = logging.getLogger(__name__)

def ensure_columns(cur: sqlite3.Cursor):
    # Add columns if missing
    cols = {r[1] for r in cur.execute("PRAGMA table_info(words)").fetchall()}
    if "rime_key" not in cols:
        cur.execute("ALTER TABLE words ADD COLUMN rime_key TEXT")
    if "vowel_key" not in cols:
        cur.execute("ALTER TABLE words ADD COLUMN vowel_key TEXT")
    if "coda_key" not in cols:
        cur.execute("ALTER TABLE words ADD COLUMN coda_key TEXT")

def index_sql(cur: sqlite3.Cursor):
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rime_key ON words(rime_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vowel_key ON words(vowel_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_coda_key ON words(coda_key)")

def main():
    ap = argparse.ArgumentParser(description="Add tail-based rhyme keys to words_index.sqlite")
    ap.add_argument("--db", default="data/words_index.sqlite", help="Path to words_index.sqlite")
    ap.add_argument("--limit", type=int, default=0, help="Process only N rows (0 = all)")
    ap.add_argument("--where", default="", help="Optional WHERE clause (e.g. \"word like 's%' \")")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # sanity check
    tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "words" not in tabs:
        log.error("No 'words' table found in %s", args.db)
        sys.exit(2)

    ensure_columns(cur)
    con.commit()

    base = "SELECT rowid, word, pron FROM words"
    if args.where:
        base += " WHERE " + args.where
    if args.limit > 0:
        base += f" LIMIT {args.limit}"

    rows = cur.execute(base).fetchall()
    updated = 0; skipped = 0

    for i, r in enumerate(rows, 1):
        w = r["word"]
        try:
            pron_raw = r["pron"]
        except Exception:
            pron_raw = []

        phones = parse_pron_field(pron_raw)
        vowel, coda, rime = tail_keys(phones)

        if not any((vowel, coda, rime)):
            skipped += 1
            continue

        cur.execute("UPDATE words SET rime_key=?, vowel_key=?, coda_key=? WHERE rowid=?",
                    (rime, vowel, coda, r["rowid"]))
        updated += 1

        if updated % 5000 == 0:
            con.commit()

    con.commit()
    index_sql(cur)
    con.commit()

    log.info("[ok] updated=%s, skipped=%s", updated, skipped)
    con.close()

if __name__ == "__main__":
    main()
