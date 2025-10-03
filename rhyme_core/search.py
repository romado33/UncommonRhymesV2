from __future__ import annotations
import sqlite3, json, re
from functools import lru_cache
from typing import List, Tuple, Dict
from unidecode import unidecode
from .phonetics import key_k1, key_k2

def _clean(text: str) -> str:
    return re.sub(r"[^a-zA-Z'\- ]+", "", unidecode(text)).strip().lower()

@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    # Allow use from Gradio worker threads (read-only queries)
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
    return tuple(key_k1(phones)), tuple(key_k2(phones))

def _candidates_by_key(key_col: str, key: Tuple[str,...], limit: int=500) -> List[Dict]:
    key_json = json.dumps(list(key))
    rows = _db().execute(
        f"SELECT word, pron, syls FROM words WHERE {key_col}=? LIMIT ?",
        (key_json, limit)
    ).fetchall()
    return [{"word": r["word"], "pron": json.loads(r["pron"]), "syls": r["syls"]} for r in rows]

def search_word(
    word: str,
    rhyme_type: str="any",
    slant_strength: float=0.5,
    syllable_min: int=1,
    syllable_max: int=8,
    max_results: int=150,
) -> List[Dict]:
    w = _clean(word)
    keys = _keys_for_word(w)
    if not keys:
        return []
    k1, k2 = keys
    pool = _candidates_by_key("k1", k1, 200) + _candidates_by_key("k2", k2, 200)
    # Deduplicate & filter
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
    # Minimal scoring/classification (placeholder)
    for c in filtered:
        c["rhyme_type"] = "perfect"  # TODO: replace with classifier
        c["score"] = 1.0
        c["why"] = "Matches final stressed-vowel rime (K1) or two-syllable key (K2)."
    filtered.sort(key=lambda x: (-x["score"], x["word"]))
    return filtered[:max_results]

def search_phrase_to_words(
    phrase: str,
    **kwargs
) -> List[Dict]:
    parts = _clean(phrase).split()
    if not parts:
        return []
    last = parts[-1]
    return search_word(last, **kwargs)
