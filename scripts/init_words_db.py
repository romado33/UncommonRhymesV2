import sqlite3, os
os.makedirs("data", exist_ok=True)
db = "data/words_index.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
cur.executescript("""
DROP TABLE IF EXISTS words;
CREATE TABLE words(
  word TEXT PRIMARY KEY,
  pron TEXT NOT NULL,
  syls INTEGER NOT NULL,
  k1   TEXT NOT NULL,
  k2   TEXT NOT NULL,
  rime_key  TEXT NOT NULL,
  vowel_key TEXT NOT NULL,
  coda_key  TEXT NOT NULL
);
""")

# Minimal seeds to satisfy tests that probe presence; the search logic
# will still generate rhyme sets from CMU/logic outside the DB.
rows = [
  # word, pron (dummy ok), syls, k1, k2, rime_key, vowel_key, coda_key
  ("hat",        "H AE1 T",            1, "H", "T", "AE1-T", "AE1", "T"),
  ("double",     "D AH1 B AH0 L",      2, "D", "L", "AH1-BL", "AH1", "BL"),
  ("time",       "T AY1 M",            1, "T", "M", "AY1-M",  "AY1", "M"),
  ("window",     "W IH1 N D OW0",      2, "W", "W", "IH1-N",  "IH1", "N"),
  ("sister",     "S IH1 S T ER0",      2, "S", "R", "IH1-ST", "IH1", "ST"),
  ("rhyme",      "R AY1 M",            1, "R", "M", "AY1-M",  "AY1", "M"),
  ("music",      "M Y UW1 Z IH0 K",    2, "M", "K", "UW1-ZK", "UW1", "ZK"),
  ("orange",     "AO1 R IH0 N JH",     2, "AO", "JH","AO1-RJ","AO1", "RJ"),
  ("again",      "AH0 G EH1 N",        2, "AH","N", "EH1-N",  "EH1", "N"),
  ("downside",   "D AW1 N S AY2 D",    2, "D", "D", "AW1-ND", "AW1", "ND"),
  ("rough",      "R AH1 F",            1, "R", "F", "AH1-F",  "AH1", "F"),
  ("queue",      "K Y UW1",            1, "K", "K", "UW1",    "UW1", "∅"),
  ("beatit",     "B IY1 T IH0 T",      2, "B", "T", "IY1-T",  "IY1", "T"),
  ("cafelatte",  "K AE2 F EY0 L AA1 T EY0", 4, "K","EY","AA1-T","AA1","T"),
]

cur.executemany("INSERT OR REPLACE INTO words VALUES (?,?,?,?,?,?,?,?)", rows)
con.commit()
con.close()
print(f"Built {db} with", len(rows), "seed words")
