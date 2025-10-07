#!/usr/bin/env python3
import os, sqlite3, re
from pathlib import Path

WORDS_DB = Path(os.environ.get("UR_WORDS_DB", "data/words_index.sqlite"))
PATTERNS = Path(os.environ.get("UR_PATTERNS_DB", "data/patterns.sqlite"))

def main():
    PATTERNS.parent.mkdir(parents=True, exist_ok=True)
    conw = sqlite3.connect(str(WORDS_DB)); conw.row_factory = sqlite3.Row
    conp = sqlite3.connect(str(PATTERNS))
    curp = conp.cursor()
    curp.executescript("""
    PRAGMA journal_mode=WAL;
    DROP TABLE IF EXISTS patterns;
    CREATE TABLE patterns(
      key     TEXT PRIMARY KEY,
      pattern TEXT NOT NULL,
      lyric   TEXT,
      artist  TEXT,
      song    TEXT
    );
    """)
    rows = conw.execute("SELECT word FROM words").fetchall()
    seen = set()
    ins = []
    for r in rows:
        w = r["word"]
        tail = re.sub(r"[^a-z]+", "", w.lower())
        for n in range(3, 7):            # *3..*6 tails
            if len(tail) >= n:
                pat = "*" + tail[-n:]
                key = f"{pat}:{w}"
                if key in seen: continue
                seen.add(key)
                ins.append((key, pat, w, None, None))
        if len(ins) >= 5000:
            curp.executemany("INSERT OR REPLACE INTO patterns(key,pattern,lyric,artist,song) VALUES(?,?,?,?,?)", ins)
            ins.clear()
    if ins:
        curp.executemany("INSERT OR REPLACE INTO patterns(key,pattern,lyric,artist,song) VALUES(?,?,?,?,?)", ins)
    conp.commit()
    conw.close(); conp.close()
    print(f"Built patterns with {len(seen)} entries at {PATTERNS}")

if __name__ == "__main__":
    main()
