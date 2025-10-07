# scripts/migrate_words_db.py
import os
import sqlite3
from contextlib import closing

DB_PATH = os.environ.get("WORDS_DB_PATH", "data/words_index.sqlite")

VOWELS = {
    "AA","AE","AH","AO","AW","AY",
    "EH","ER","EY",
    "IH","IY",
    "OW","OY",
    "UH","UW",
}

def _tokens(pron: str):
    # Normalize whitespace, split into ARPABET tokens (e.g., 'T AY1 M')
    return [t for t in pron.strip().split() if t]

def _is_vowel(tok: str) -> bool:
    # Accept both 'AY1' and 'AY' as vowel tokens; compare by stripping digits
    base = tok.rstrip("0123456789")
    return base in VOWELS

def _vowel_key(tok: str) -> str:
    # Preserve stress number if present; e.g., 'AY1'
    return tok

def _extract_tail_keys(pron: str):
    """
    Given an ARPABET pron string, return (vowel_key, coda_key, rime_key).
    - vowel_key: last vowel token (incl. stress), e.g., 'AY1'
    - coda_key: concatenated consonant tokens after that vowel, e.g., 'M' or 'ND'
    - rime_key: f'{vowel_key}-{coda_key}' (or just vowel_key if no coda)
    """
    toks = _tokens(pron)
    if not toks:
        return ("", "", "")
    # Find last vowel index
    v_idx = -1
    for i in range(len(toks) - 1, -1, -1):
        if _is_vowel(toks[i]):
            v_idx = i
            break
    if v_idx == -1:
        # No vowel found; treat entire tail as coda
        return ("", "".join(toks), "".join(toks))
    vowel = _vowel_key(toks[v_idx])
    after = toks[v_idx + 1 :]
    coda = "".join(after) if after else ""
    rime = f"{vowel}-{coda}" if coda else vowel
    return (vowel, coda, rime)

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
            vowel, coda, rime = _extract_tail_keys(pron or "")
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
        con.commit()
    print(f"Migration complete. Added columns: {missing or 'none'}. Rows updated: {updated}.")

if __name__ == "__main__":
    main()
