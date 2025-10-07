from __future__ import annotations
import sqlite3, os, json
from .phonetics import (
    parse_cmu_line,
    syllable_count,
    key_k1,
    key_k2,
    tail_keys,
)

def build_words_index(cmu_path: str, sqlite_path: str):
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    con = sqlite3.connect(sqlite_path)
    cur = con.cursor()
    cur.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS words(
            word TEXT PRIMARY KEY,
            pron TEXT NOT NULL,
            syls INTEGER NOT NULL,
            k1   TEXT NOT NULL,
            k2   TEXT NOT NULL,
            rime_key  TEXT NOT NULL,
            vowel_key TEXT NOT NULL,
            coda_key  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_k1 ON words(k1);
        CREATE INDEX IF NOT EXISTS idx_k2 ON words(k2);
        CREATE INDEX IF NOT EXISTS idx_rime_key ON words(rime_key);
        CREATE INDEX IF NOT EXISTS idx_vowel_key ON words(vowel_key);
        CREATE INDEX IF NOT EXISTS idx_coda_key ON words(coda_key);
    """)
    batch=[]
    with open(cmu_path, "r", encoding="utf8", errors="ignore") as f:
        for line in f:
            parsed = parse_cmu_line(line)
            if not parsed:
                continue
            word, phones = parsed
            syls = syllable_count(phones)
            k1 = json.dumps(tuple(key_k1(phones)))
            k2 = json.dumps(tuple(key_k2(phones)))
            vowel, coda, rime = tail_keys(phones)
            batch.append((word, json.dumps(phones), syls, k1, k2, rime, vowel, coda))
            if len(batch) >= 2000:
                cur.executemany(
                    "INSERT OR REPLACE INTO words VALUES(?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()
    if batch:
        cur.executemany(
            "INSERT OR REPLACE INTO words VALUES(?,?,?,?,?,?,?,?)",
            batch,
        )
    con.commit(); con.close()
