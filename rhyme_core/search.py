from __future__ import annotations
import sqlite3, json, re, io, csv
from functools import lru_cache
from typing import List, Tuple, Dict
from unidecode import unidecode
from wordfreq import zipf_frequency
from .phonetics import key_k1, key_k2
from .scoring import classify, syllables

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

def search_word(
    word: str,
    rhyme_type: str="any",
    slant_strength: float=0.5,
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
    src_tail = tuple(key_k1(list(src_pron)))
    pool = _candidates_by_key("k1", k1, 800) + _candidates_by_key("k2", k2, 800)

    seen, filtered = set(), []
    for c in pool:
        if c["word"] == w:
            continue
        if not (syllable_min <= c["syls"] <= syllable_max):
            continue
        if c["word"] in seen:
            continue
        seen.add(c["word"])
        filtered.append(c)

    results = []
    for c in filtered:
        cand_tail = tuple(key_k1(c["pron"]))
        rtype = classify(src_tail, cand_tail)
        if rhyme_type != "any" and rtype != rhyme_type:
            continue
        multi = syllables(src_tail) >= 2
        rhyme_q = {"perfect":1.0, "assonant":0.75, "consonant":0.65, "slant":0.5}[rtype]
        if multi:
            rhyme_q = min(rhyme_q + 0.1, 1.1)
        rar = _rarity_score(c["word"])
        score = weight_quality * rhyme_q + weight_rarity * rar
        results.append({
            "word": c["word"],
            "pron": c["pron"] if include_pron else None,
            "syls": c["syls"],
            "rhyme_type": ("multisyllabic "+rtype) if (multi and rtype=="perfect") else rtype,
            "score": round(score, 4),
            "why": f"{rtype}; {'multi' if multi else 'mono'}-syllabic tail; rarity={rar:.2f}"
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
    import csv
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
