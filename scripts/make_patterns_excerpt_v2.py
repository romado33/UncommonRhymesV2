from __future__ import annotations
import sqlite3, os, argparse, sys

def open_db(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        sys.exit(f"[error] DB not found: {path}")
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
        sys.exit(f"[error] Could not read columns for table '{args.table}' in {args.src}")

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
        sys.exit("[error] No rows selected; did you run the migration to add key columns?")

    placeholders = ",".join(["?"]*len(cols))
    dcur.executemany(f'INSERT INTO patterns({",".join(cols)}) VALUES ({placeholders})',
                     [tuple(r[c] for c in cols) for r in dedup])
    # Indexes
    if "last_word_rime_key" in cols:
        dcur.execute('CREATE INDEX IF NOT EXISTS idx_last_word_rime_key ON patterns(last_word_rime_key)')
    if "last_two_syllables_key" in cols:
        dcur.execute('CREATE INDEX IF NOT EXISTS idx_last_two_syllables_key ON patterns(last_two_syllables_key)')
    dst.commit(); dst.close(); src.close()
    print(f"[ok] Wrote {len(dedup)} rows to {args.dst} with indexes on keys.")
if __name__ == "__main__":
    main()
