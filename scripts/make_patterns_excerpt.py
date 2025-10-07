import logging
import os
import sqlite3

from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

SRC = "data/patterns.db"         # your full DB (local)
DST = "data/patterns_small.db"   # ship this to HF Spaces
N_PER_KEY = 50                   # tune as needed

os.makedirs("data", exist_ok=True)
src = sqlite3.connect(SRC); src.row_factory = sqlite3.Row
dst = sqlite3.connect(DST)
dcur = dst.cursor()
# Adjust table/columns to your schema
dcur.executescript("""
DROP TABLE IF EXISTS patterns;
CREATE TABLE patterns AS SELECT * FROM main.patterns WHERE 0;
CREATE INDEX IF NOT EXISTS idx_last_word_rime_key ON patterns(last_word_rime_key);
CREATE INDEX IF NOT EXISTS idx_last_two_syllables_key ON patterns(last_two_syllables_key);
""")
keys = [r[0] for r in src.execute("SELECT DISTINCT last_word_rime_key FROM patterns").fetchall()]
for k in keys:
    rows = src.execute("SELECT * FROM patterns WHERE last_word_rime_key=? LIMIT ?", (k, N_PER_KEY)).fetchall()
    if rows:
        cols = rows[0].keys()
        placeholders = ",".join(["?"]*len(cols))
        dcur.executemany(f"INSERT INTO patterns({','.join(cols)}) VALUES ({placeholders})",
                         [tuple(r[c] for c in cols) for r in rows])
dst.commit(); dst.close(); src.close()
log.info("Wrote data/patterns_small.db")
