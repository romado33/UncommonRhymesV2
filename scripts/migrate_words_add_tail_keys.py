# scripts/migrate_words_add_tail_keys.py
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from typing import List, Tuple

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

VOWELS = {
    "AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"
}

def is_vowel(p: str) -> bool:
    core = p[:-1] if p and p[-1].isdigit() else p
    return core in VOWELS

def stress_digit(p: str) -> int:
    return int(p[-1]) if p and p[-1].isdigit() else 0

def vowel_core(p: str) -> str:
    return p[:-1] if p and p[-1].isdigit() else p

def tail_parts(pron: List[str]) -> Tuple[List[str], str, Tuple[str, ...]]:
    """
    Return (tail, vowel_core, coda_tuple)
      - tail: from last stressed vowel (1/2), else last vowel, to end
      - vowel_core: e.g., 'IH' for 'IH1'
      - coda: consonants after that vowel within the tail
    """
    if not pron:
        return [], "", ()
    idx = -1
    # last stressed vowel
    for i in range(len(pron)-1, -1, -1):
        if is_vowel(pron[i]) and stress_digit(pron[i]) in (1, 2):
            idx = i
            break
    # else last vowel
    if idx == -1:
        for i in range(len(pron)-1, -1, -1):
            if is_vowel(pron[i]):
                idx = i
                break
    if idx == -1:
        return [], "", ()
    tail = pron[idx:]
    nuc = vowel_core(pron[idx])
    coda = tuple(p for p in tail[1:] if not is_vowel(p))
    return tail, nuc, coda

def norm_tail(pron: List[str]) -> Tuple[str, ...]:
    """Normalize tail by removing stress digits from vowels."""
    tail, _, _ = tail_parts(pron)
    out = []
    for p in tail:
        if is_vowel(p):
            out.append(vowel_core(p))
        else:
            out.append(p)
    return tuple(out)

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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_words_rime_key ON words(rime_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_words_vowel_key ON words(vowel_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_words_coda_key ON words(coda_key)")

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
            pron = json.loads(r["pron"])
        except Exception:
            pron = []

        t, v, c = tail_parts(pron)
        if not t:
            skipped += 1
            continue

        rime = json.dumps(list(norm_tail(pron)))
        vowel = v
        coda = json.dumps(list(c))

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
