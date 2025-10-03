from __future__ import annotations
import sqlite3, json, re, io, csv
from functools import lru_cache
from typing import List, Tuple, Dict
from unidecode import unidecode
from wordfreq import zipf_frequency

# Removed dependency on .scoring.classify; we classify locally now.
from .phonetics import key_k1, key_k2

# Accept letters with optional apostrophes / hyphens / spaces.
# Reject anything starting with punctuation (e.g. ")close-parentheses").
VALID_WORD_RE = re.compile(r"^[a-z][a-z'\- ]*$")

def _clean(text: str) -> str:
    return re.sub(r"[^a-zA-Z'\- ]+", "", unidecode(text)).strip().lower()

@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    con = sqlite3.connect("data/words_index.sqlite", check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def _get_pron(word: str) -> List[str] | None:
    row = _db().execute("SELECT pron FROM words WHERE word=?", (word,)).fetchone()
    return json.loads(row["pron"]) if row else None

def _keys_for_word(word: str):
    phones = _get_pron(word)
    if not phones:
        return None
    return tuple(key_k1(phones)), tuple(key_k2(phones)), tuple(phones)

def _candidates_by_key(key_col: str, key: Tuple[str,...], limit: int=500) -> List[Dict]:
    key_json = json.dumps(list(key))
    rows = _db().execute(
        f"SELECT word, pron, syls FROM words WHERE {key_col}=? LIMIT ?",
        (key_json, limit)
    ).fetchall()
    return [{"word": r["word"], "pron": json.loads(r["pron"]), "syls": r["syls"]} for r in rows]

def _rarity_score(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0

# ---------------------------
# Phoneme-level classifier
# ---------------------------

_VOWELS = {
    "AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"
}

def _is_vowel(p: str) -> bool:
    core = p[:-1] if p and p[-1].isdigit() else p
    return core in _VOWELS

def _stress_digit(p: str) -> int:
    return int(p[-1]) if p and p[-1].isdigit() else 0

def _vowel_core(p: str) -> str:
    return (p[:-1] if p and p[-1].isdigit() else p)

def _tail_parts(pron: List[str]) -> tuple[list[str], str, tuple[str, ...]]:
    """
    Return (tail, vowel_core, coda_tuple)
    - tail: list from last stressed vowel (1/2) else last vowel to end
    - vowel_core: e.g. 'IH' for 'IH1'
    - coda: tuple of consonants after that vowel within the tail
    """
    if not pron:
        return [], "", ()
    idx = -1
    # last stressed vowel (1/2)
    for i in range(len(pron)-1, -1, -1):
        if _is_vowel(pron[i]) and _stress_digit(pron[i]) in (1, 2):
            idx = i
            break
    # else last vowel
    if idx == -1:
        for i in range(len(pron)-1, -1, -1):
            if _is_vowel(pron[i]):
                idx = i
                break
    if idx == -1:
        return [], "", ()
    tail = pron[idx:]
    nuc = _vowel_core(pron[idx])
    coda = tuple(p for p in tail[1:] if not _is_vowel(p))
    return tail, nuc, coda

def _norm_tail(pron: List[str]) -> tuple[str, ...]:
    """Normalize a tail by stripping stress digits from vowels."""
    tail, _, _ = _tail_parts(pron)
    norm: list[str] = []
    for p in tail:
        if _is_vowel(p):
            norm.append(_vowel_core(p))
        else:
            norm.append(p)
    return tuple(norm)

def _lev(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    la, lb = len(a), len(b)
    dp = [list(range(lb+1))] + [[i] + [0]*lb for i in range(1, la+1)]
    for i in range(1, la+1):
        for j in range(1, lb+1):
            cost = 0 if a[i-1] == b[j-1] else 1
            dp[i][j] = min(
                dp[i-1][j] + 1,
                dp[i][j-1] + 1,
                dp[i-1][j-1] + cost,
            )
    return dp[la][lb]

def classify_rhyme(pron_a: List[str], pron_b: List[str]) -> str:
    """
    Return 'perfect' | 'consonant' | 'assonant' | 'slant' | 'none'
    """
    if not pron_a or not pron_b:
        return "none"
    tail_a, nuc_a, coda_a = _tail_parts(pron_a)
    tail_b, nuc_b, coda_b = _tail_parts(pron_b)
    if not tail_a or not tail_b:
        return "none"

    norm_a, norm_b = _norm_tail(pron_a), _norm_tail(pron_b)

    if norm_a == norm_b:
        return "perfect"
    if coda_a and (coda_a == coda_b) and (nuc_a != nuc_b):
        return "consonant"
    if (nuc_a == nuc_b) and (coda_a != coda_b):
        return "assonant"

    # near on normalized tails => slant
    dist = _lev(norm_a, norm_b)
    max_len = max(len(norm_a), len(norm_b))
    if max_len > 0 and (dist / max_len) <= 0.25:
        return "slant"
    return "none"

def tail_syllables(pron: List[str]) -> int:
    tail, _, _ = _tail_parts(pron)
    return sum(1 for p in tail if _is_vowel(p))

def is_multiword(word: str) -> bool:
    return (" " in word) or ("-" in word)

# ---------------------------
# Search
# ---------------------------

def search_word(
    word: str,
    rhyme_type: str="any",
    slant_strength: float=0.5,   # reserved for future weighting
    syllable_min: int=1,
    syllable_max: int=8,
    max_results: int=150,
    weight_quality: float=0.6,
    weight_rarity: float=0.4,
    include_pron: bool=False,
) -> List[Dict]:
    w = _clean(word)
    info = _keys_for_word(w)
    if not info:
        return []
    k1, k2, src_pron = info
    # We still use keys for candidate recall:
    pool = _candidates_by_key("k1", k1, 800) + _candidates_by_key("k2", k2, 800)

    seen, filtered = set(), []
    for c in pool:
        w_cand = c["word"]
        if w_cand == w:
            continue
        if not (syllable_min <= c["syls"] <= syllable_max):
            continue
        if not VALID_WORD_RE.match(w_cand):
            continue
        if w_cand in seen:
            continue
        seen.add(w_cand)
        filtered.append(c)

    results: List[Dict] = []
    for c in filtered:
        rtype = classify_rhyme(list(src_pron), c["pron"])
        if rhyme_type != "any" and rtype != rhyme_type:
            continue

        # “multisyllabic tail” (phonetic multi), and “multiword” (orthographic multi)
        tail_multi = tail_syllables(c["pron"]) >= 2
        orth_multi = is_multiword(c["word"])

        # quality weighting; bump a little for multisyllabic tails
        rhyme_q_map = {"perfect":1.0, "assonant":0.85, "consonant":0.9, "slant":0.75, "none":0.0}
        rhyme_q = rhyme_q_map.get(rtype, 0.0)
        if tail_multi:
            rhyme_q = min(rhyme_q + 0.05, 1.1)

        rar = _rarity_score(c["word"])
        score = weight_quality * rhyme_q + weight_rarity * rar

        results.append({
            "word": c["word"],
            "pron": c["pron"] if include_pron else None,
            "syls": c["syls"],
            "rhyme_type": ("multisyllabic "+rtype) if (tail_multi and rtype=="perfect") else rtype,
            "is_multiword": orth_multi,
            "score": round(score, 4),
            "why": f"{rtype}; {'multi' if tail_multi else 'mono'}-syllabic tail; rarity={rar:.2f}"
        })

    results.sort(key=lambda x: (-x["score"], x["word"]))
    return results[:max_results]

def search_phrase_to_words(phrase: str, **kwargs) -> List[Dict]:
    parts = _clean(phrase).split()
    if not parts:
        return []
    last = parts[-1]
    return search_word(last, **kwargs)

def make_csv_bytes(word: str, **kwargs) -> bytes:
    rows = search_word(word, **kwargs)
    output = io.StringIO()
    writer = csv.writer(output)
    header = ["word","pron","rhyme_type","score","why"]
    writer.writerow(header)
    for r in rows:
        writer.writerow([
            r.get("word",""),
            " ".join(r.get("pron") or []),
            r.get("rhyme_type",""),
            r.get("score",0.0),
            r.get("why",""),
        ])
    return output.getvalue().encode("utf-8")
