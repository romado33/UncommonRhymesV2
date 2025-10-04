"""
Search helpers and CMU‑index lookup. Public API:
- search_word(...)
- _get_pron, _clean
- classify_rhyme, _final_coda, _norm_tail
- stress_pattern_str, syllable_count

Relies on SQLite at data/words_index.sqlite with schema:
  words(word TEXT PRIMARY KEY, pron TEXT JSON, syls INT,
        k1 TEXT, k2 TEXT, rime_key TEXT, vowel_key TEXT, coda_key TEXT)
"""
from __future__ import annotations
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

DATA_DIR = Path("data")
WORDS_DB = DATA_DIR / "words_index.sqlite"

_VOWELS = {"AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"}
_STRIP_STRESS = re.compile(r"\d")
_WORD_CLEAN = re.compile(r"[^a-z0-9\-\s']+")

# Optional LLM OOV fallback
try:
    from llm.oov_g2p import infer_pron_arpabet  # type: ignore
    from config import FLAGS as _FLAGS  # type: ignore
except Exception:
    infer_pron_arpabet = None
    class _Dummy:
        LLM_OOV_G2P = False
    _FLAGS = _Dummy()

# ---------------- Pron helpers ----------------

def _clean(w: str) -> str:
    return _WORD_CLEAN.sub("", (w or "").lower()).strip()

@lru_cache(maxsize=65536)
def _get_pron(word: str) -> List[str] | None:
    w = _clean(word)
    if not w:
        return None
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT pron FROM words WHERE word=?", (w,)).fetchone()
    con.close()
    if not row:
        # OOV LLM fallback (flagged)
        if getattr(_FLAGS, "LLM_OOV_G2P", False) and infer_pron_arpabet:
            try:
                arp = infer_pron_arpabet(w)
                if arp:
                    return arp
            except Exception:
                pass
        return None
    try:
        return json.loads(row["pron"]) or []
    except Exception:
        return None

# stress / syllable helpers

def stress_pattern_str(pron: List[str]) -> str:
    if not pron:
        return ""
    out = []
    for p in pron:
        m = re.search(r"(\d)$", p)
        if m:
            out.append(m.group(1))
    return "-".join(out) if out else ""


def syllable_count(pron: List[str]) -> int:
    if not pron:
        return 0
    return sum(1 for p in pron if p and p[-1].isdigit())

# tail parsing

def _vowel_core(p: str) -> str:
    return _STRIP_STRESS.sub("", p)


def _final_vowel_and_coda(pron: List[str]) -> Tuple[str, Tuple[str, ...]]:
    v = ""
    i = len(pron) - 1
    while i >= 0:
        ph = pron[i]
        base = _vowel_core(ph)
        if base in _VOWELS:
            v = base
            break
        i -= 1
    coda = [_vowel_core(p) for p in pron[i+1:]] if i >= 0 else []
    return v, tuple(coda)


def _final_coda(pron: List[str]) -> Tuple[str, ...]:
    return _final_vowel_and_coda(pron)[1]


def _norm_tail(pron: List[str]) -> Tuple[str, ...]:
    v, c = _final_vowel_and_coda(pron)
    return (v,) + c if v else c

# ---------------- Rhyme classifier ----------------

def classify_rhyme(qpron: List[str], cpron: List[str]) -> str:
    if not qpron or not cpron:
        return "none"
    qv, qc = _final_vowel_and_coda(qpron)
    cv, cc = _final_vowel_and_coda(cpron)
    if qv == cv and qc == cc:
        return "perfect"
    if qv == cv and qc != cc:
        return "assonant"
    if qv != cv and qc == cc and qc:
        return "consonant"
    return "slant" if (qpron and cpron and _vowel_core(qpron[-1]) == _vowel_core(cpron[-1])) else "none"

# ---------------- Candidate pool ----------------

def _db_candidates_for_word(word: str) -> Iterable[sqlite3.Row]:
    w = _clean(word)
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT rime_key,vowel_key,coda_key,k1,k2 FROM words WHERE word=?", (w,)).fetchone()
    if not row:
        con.close()
        return []
    rime, vow, coda, k1, k2 = row["rime_key"], row["vowel_key"], row["coda_key"], row["k1"], row["k2"]
    rows: list = []
    if rime:
        rows += con.execute("SELECT word,pron,syls FROM words WHERE rime_key=? LIMIT 600", (rime,)).fetchall()
    if vow:
        rows += con.execute("SELECT word,pron,syls FROM words WHERE vowel_key=? LIMIT 400", (vow,)).fetchall()
    if coda:
        rows += con.execute("SELECT word,pron,syls FROM words WHERE coda_key=? LIMIT 400", (coda,)).fetchall()
    if k1:
        rows += con.execute("SELECT word,pron,syls FROM words WHERE k1=? LIMIT 600", (k1,)).fetchall()
    if k2:
        rows += con.execute("SELECT word,pron,syls FROM words WHERE k2=? LIMIT 600", (k2,)).fetchall()
    con.close()
    return rows

# ---------------- Core search ----------------

def search_word(
    word: str,
    rhyme_type: str = "any",
    slant_strength: float = 0.5,
    syllable_min: int = 1,
    syllable_max: int = 8,
    max_results: int = 500,
    include_pron: bool = False,
) -> List[dict]:
    w = _clean(word)
    qpron = _get_pron(w) or []
    if not qpron:
        return []

    pool = _db_candidates_for_word(w)

    out: List[dict] = []
    seen: set[str] = set()
    for r in pool:
        cand = r["word"]
        if cand == w or cand in seen:
            continue
        try:
            pron = json.loads(r["pron"]) or []
        except Exception:
            continue
        syls = syllable_count(pron)
        if syls < syllable_min or syls > syllable_max:
            continue
        rtype = classify_rhyme(qpron, pron)
        if rhyme_type != "any" and rtype != rhyme_type:
            continue
        base = {"perfect": 1.0, "consonant": 0.9, "assonant": 0.86, "slant": 0.75, "none": 0.0}[rtype]
        if rtype == "slant":
            base *= (0.5 + 0.5 * max(0.0, min(1.0, slant_strength)))
        # prosody tie-break baked into score a touch
        stress_equal = 1 if (stress_pattern_str(qpron) and stress_pattern_str(qpron) == stress_pattern_str(pron)) else 0
        score = base + 0.02 * stress_equal
        out.append({
            "word": cand,
            "score": score,
            "rhyme_type": rtype,
            "is_multiword": (" " in cand or "-" in cand),
            **({"pron": pron} if include_pron else {}),
        })
        seen.add(cand)

    out.sort(key=lambda x: (-x["score"], x["word"]))
    return out[:max_results]
