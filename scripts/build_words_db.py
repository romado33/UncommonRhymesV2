import sqlite3
import os
import re
import pathlib

DB_PATH = os.environ.get("WORDS_DB_PATH", "data/words_index.sqlite")
CMU_PATH = os.environ.get("CMUDICT_PATH", "data/cmudict.txt")

VOWELS = {
    "AA","AE","AH","AO","AW","AY",
    "EH","ER","EY",
    "IH","IY",
    "OW","OY",
    "UH","UW",
}
PAREN_VARIANT_RE = re.compile(r"\(\d+\)$")  # WORD(2) -> WORD


def tokens(pron: str):
    return [t for t in pron.split() if t]


def is_vowel(tok: str) -> bool:
    return tok.rstrip("0123456789") in VOWELS


def count_syllables(pron: str) -> int:
    """Count stress digits; good proxy for syllable count in CMUdict."""
    return sum(ch.isdigit() for ch in pron)


def extract_tail_keys(pron: str):
    """Return (vowel_key, coda_key, rime_key) from last vowel to end."""
    toks = tokens(pron)
    if not toks:
        return ("", "", "")
    v_idx = -1
    for i in range(len(toks) - 1, -1, -1):
        if is_vowel(toks[i]):
            v_idx = i
            break
    if v_idx < 0:
        coda = "".join(toks)
        return ("", coda, coda)
    vowel = toks[v_idx]
    after = toks[v_idx + 1 :]
    coda = "".join(after) if after else ""
    rime = f"{vowel}-{coda}" if coda else vowel
    return (vowel, coda, rime)


def onset_coda_keys(pron: str):
    """
    Heuristic:
      - k1: token just before first vowel (or first token if starts with vowel)
      - k2: last token (often final consonant cluster or vowel if no coda)
    """
    toks = tokens(pron)
    if not toks:
        return ("", "")
    # first vowel index
    fv = next((i for i, t in enumerate(toks) if is_vowel(t)), None)
    if fv is None:
        k1 = toks[0]
    elif fv == 0:
        k1 = toks[0]
    else:
        k1 = toks[fv - 1]
    k2 = toks[-1]
    return (k1, k2)


def normalize_word(raw: str) -> str:
    # CMU lines like "WORD(2)  W ER1 D" -> "word"
    w = raw.strip()
    w = PAREN_VARIANT_RE.sub("", w)
    return w.lower()


def cmu_lines(path: str):
    """Yield lines from CMUdict handling encoding quirks (utf-8/latin-1)."""
    with open(path, "rb") as fh:
        for bline in fh:
            try:
                line = bline.decode("utf-8")
            except UnicodeDecodeError:
                line = bline.decode("latin-1", errors="ignore")
            yield line


def build():
    if not pathlib.Path(CMU_PATH).exists():
        raise SystemExit(f"CMUdict not found: {CMU_PATH}")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(
        """
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
        CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
        """
    )

    rows = []
    seen = set()
    for line in cmu_lines(CMU_PATH):
        if not line or line.startswith(";;;"):
            continue
        line = line.rstrip("\r\n")
        # split into "WORD(alt)  PH ON EMS"
        parts = line.split("  ", 1)
        if len(parts) != 2:
            continue
        raw_word, pron = parts
        word = normalize_word(raw_word)
        if not word or word in seen:
            continue
        seen.add(word)
        syls = count_syllables(pron)
        k1, k2 = onset_coda_keys(pron)
        vowel, coda, rime = extract_tail_keys(pron)
        rows.append((word, pron, syls, k1, k2, rime, vowel, coda))
        if len(rows) >= 5000:
            cur.executemany(
                "INSERT OR REPLACE INTO words VALUES (?,?,?,?,?,?,?,?)", rows
            )
            con.commit()
            rows.clear()
    if rows:
        cur.executemany("INSERT OR REPLACE INTO words VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit()

    n = cur.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    con.close()
    print(f"Built {DB_PATH} with {n} words")


if __name__ == "__main__":
    build()
