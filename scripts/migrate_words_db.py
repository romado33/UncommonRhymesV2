# scripts/migrate_words_db.py
import os
import sqlite3
from contextlib import closing

from rhyme_core.phonetics import parse_pron_field, tail_keys

DB_PATH = os.environ.get("WORDS_DB_PATH", "data/words_index.sqlite")

def ensure_columns(con: sqlite3.Connection) -> list[str]:
    have = {row[1] for row in con.execute("PRAGMA table_info(words)").fetchall()}
    needed = ["rime_key", "vowel_key", "coda_key"]
    missing = [c for c in needed if c not in have]
    for col in missing:
        con.execute(f"ALTER TABLE words ADD COLUMN {col} TEXT")
    if missing:
        con.commit()
    return missing

def backfill(con: sqlite3.Connection, batch_size: int = 1000) -> int:
    cur = con.cursor()
    cur.execute("""
        SELECT rowid, pron
        FROM words
        WHERE (rime_key IS NULL OR rime_key = '')
           OR (vowel_key IS NULL OR vowel_key = '')
           OR (coda_key  IS NULL OR coda_key  = '')
    """)
    rows = cur.fetchall()
    total = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i+batch_size]
        updates = []
        for rowid, pron in chunk:
            phones = parse_pron_field(pron)
            vowel, coda, rime = tail_keys(phones)
            updates.append((rime, vowel, coda, rowid))
        cur.executemany(
            "UPDATE words SET rime_key=?, vowel_key=?, coda_key=? WHERE rowid=?",
            updates
        )
        con.commit()
        total += len(updates)
    return total

def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"DB not found: {DB_PATH}. Build or provide data/words_index.sqlite first.")
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        missing = ensure_columns(con)
        updated = backfill(con)
        con.execute("CREATE INDEX IF NOT EXISTS idx_words_word ON words(word)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_rime_key ON words(rime_key)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_vowel_key ON words(vowel_key)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_coda_key ON words(coda_key)")
        con.commit()
    print(f"Migration complete. Added columns: {missing or 'none'}. Rows updated: {updated}.")

if __name__ == "__main__":
    main()
