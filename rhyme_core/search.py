# -*- coding: utf-8 -*-
"""
UncommonRhymesV2 — Deterministic search core
============================================

This module provides deterministic rhyme search over a CMU-derived
SQLite index, with:

- Single **and** multi-word (phrase) query support
- Stress-aware rhyme nucleus (last **primary-stressed** vowel)
- Candidate widening (rime_key / vowel_key / coda_key / k1 / k2)
- Clean, bucketed output: Uncommon (perfect, backfilled), Slant,
  and Multi-word
- Optional LLM OOV G2P fallback (feature-flagged)
- Prosody helpers (syllables, stress string) wired to rhyme scoring

Public API
----------
- search_word(...): flat scored list of candidates
- find_rhymes(...): bucketed dict for the UI (uncommon/slant/multiword)
- stress_pattern_str, syllable_count: re-exported from prosody
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Optional flags
try:
    from config import FLAGS  # type: ignore
except Exception:  # pragma: no cover
    class _F:
        LLM_OOV_G2P = False
        # When True, hide consonant rhymes by default (app can override)
        DISABLE_CONSONANT_RHYMES = True
    FLAGS = _F()  # type: ignore

# External deps
from wordfreq import zipf_frequency  # rarity
# Prosody helpers from our package
from rhyme_core.prosody import syllable_count, stress_pattern_str  # type: ignore
from .fallback_data import FALLBACK_FLAT_RESULTS, FALLBACK_PRONS

# Optional G2P (feature-flagged via config.FLAGS.LLM_OOV_G2P)
try:
    from g2p_en import G2p  # type: ignore
    _G2P = G2p()
except Exception:  # pragma: no cover - environment without g2p_en
    _G2P = None  # type: ignore

# ----------------------------------------------------------------------------
# Paths / DB
# ----------------------------------------------------------------------------
DATA_DIR = Path("data")
WORDS_DB = DATA_DIR / "words_index.sqlite"

# ----------------------------------------------------------------------------
# Regex & phoneme helpers
# ----------------------------------------------------------------------------
_VOWELS = {"AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"}
_STRIP_STRESS = re.compile(r"(\d)")
_WORD_CLEAN = re.compile(r"[^a-z0-9\-\s']+")
_TOKEN_SPLIT = re.compile(r"[\s\-]+")

def _clean_word(w: str) -> str:
    """Lowercase, strip accents, and remove non word characters for key lookup."""
    base = unicodedata.normalize("NFKD", (w or "")).encode("ascii", "ignore").decode("ascii")
    cleaned = _WORD_CLEAN.sub("", base.lower())
    return cleaned.replace(" ", "").replace("-", "").strip()

def _base_phone(p: str) -> str:
    """Remove stress digits from a CMU phone (e.g., AY1 -> AY)."""
    return _STRIP_STRESS.sub("", p)

# ----------------------------------------------------------------------------
# DB accessors
# ----------------------------------------------------------------------------
def _has_valid_db() -> bool:
    if not WORDS_DB.exists():
        return False
    try:
        with WORDS_DB.open("rb") as fh:
            header = fh.read(16)
        if not header.startswith(b"SQLite format 3\x00"):
            return False
        con = sqlite3.connect(str(WORDS_DB))
        try:
            con.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        finally:
            con.close()
        return True
    except (OSError, sqlite3.DatabaseError):
        return False

_USE_FALLBACK = not _has_valid_db()

if _USE_FALLBACK and WORDS_DB.exists():
    try:
        with WORDS_DB.open("rb") as fh:
            header = fh.read(16)
        if not header.startswith(b"SQLite format 3\x00"):
            WORDS_DB.unlink(missing_ok=True)  # remove LFS pointer so tests can create a fake DB
    except OSError:
        pass

def _connect() -> sqlite3.Connection:
    if _USE_FALLBACK:
        raise RuntimeError("SQLite backend unavailable; fallback dataset in use")
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    return con

@lru_cache(maxsize=65536)
def _db_row_for_word(word: str) -> Optional[sqlite3.Row]:
    if _USE_FALLBACK:
        return None
    w = _clean_word(word)
    if not w:
        return None
    con = _connect()
    try:
        row = con.execute("SELECT word,pron,syls,k1,k2,rime_key,vowel_key,coda_key FROM words WHERE word=?", (w,)).fetchone()
        return row
    finally:
        con.close()

@lru_cache(maxsize=65536)
def _get_pron(word: str) -> List[str] | None:
    """Return ARPAbet phones for a *single* word, or None if not present.
    If FLAGS.LLM_OOV_G2P is True and g2p is available, use it for OOVs.
    """
    if _USE_FALLBACK:
        key = _clean_word(word)
        pron = FALLBACK_PRONS.get(key)
        return list(pron) if pron else None
    row = _db_row_for_word(word)
    if row is None:
        if getattr(FLAGS, "LLM_OOV_G2P", False) and _G2P is not None:
            try:
                phones = _G2P(_clean_word(word)) or []
                # g2p_en returns mixed tokens; keep CMU-like uppercase phones only
                return [p for p in phones if p and p[0].isalpha() and p[0].isupper()]
            except Exception:
                return None
        return None
    try:
        return json.loads(row["pron"]) or []
    except Exception:
        return None

def _get_keys(word: str) -> Optional[Tuple[str,str,str,str,str]]:
    if _USE_FALLBACK:
        return None
    row = _db_row_for_word(word)
    if not row:
        return None
    return (row["rime_key"], row["vowel_key"], row["coda_key"], row["k1"], row["k2"])

def _candidate_rows_by_keys(rime: str, vowel: str, coda: str, k1: str, k2: str) -> List[sqlite3.Row]:
    """Fetch a widened candidate pool based on any available keys; LIMITs tuned for HF perf."""
    if _USE_FALLBACK:
        return []
    con = _connect()
    try:
        rows: List[sqlite3.Row] = []
        if rime:
            rows += con.execute("SELECT word,pron,syls FROM words WHERE rime_key=? LIMIT 2000", (rime,)).fetchall()
        if vowel:
            rows += con.execute("SELECT word,pron,syls FROM words WHERE vowel_key=? LIMIT 2000", (vowel,)).fetchall()
        if coda:
            rows += con.execute("SELECT word,pron,syls FROM words WHERE coda_key=? LIMIT 1200", (coda,)).fetchall()
        if k1:
            rows += con.execute("SELECT word,pron,syls FROM words WHERE k1=? LIMIT 1200", (k1,)).fetchall()
        if k2:
            rows += con.execute("SELECT word,pron,syls FROM words WHERE k2=? LIMIT 1200", (k2,)).fetchall()
        return rows
    finally:
        con.close()

# ----------------------------------------------------------------------------
# Prosody + rhyme nucleus helpers
# ----------------------------------------------------------------------------
def _last_primary_vowel_index(pron: Sequence[str]) -> int:
    last_vowel = -1
    last_primary = -1
    for i, ph in enumerate(pron):
        b = _base_phone(ph)
        if b in _VOWELS:
            last_vowel = i
            if ph.endswith("1"):
                last_primary = i
    return last_primary if last_primary >= 0 else last_vowel

def _vowel_and_coda_from_index(pron: Sequence[str], idx: int) -> Tuple[str, Tuple[str,...]]:
    if idx < 0:
        return "", tuple()
    v = _base_phone(pron[idx])
    coda = tuple(_base_phone(p) for p in pron[idx+1:])
    return v, coda

def stressed_vowel_and_coda(pron: Sequence[str]) -> Tuple[str, Tuple[str,...]]:
    return _vowel_and_coda_from_index(pron, _last_primary_vowel_index(pron))

def final_vowel_and_coda(pron: Sequence[str]) -> Tuple[str, Tuple[str,...]]:
    j = -1
    for i in range(len(pron)-1, -1, -1):
        if _base_phone(pron[i]) in _VOWELS:
            j = i; break
    return _vowel_and_coda_from_index(pron, j)

# ----------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------
def classify_rhyme(qpron: Sequence[str], cpron: Sequence[str]) -> str:
    """Return one of: perfect, assonant, consonant, slant, none."""
    if not qpron or not cpron:
        return "none"
    qv, qc = stressed_vowel_and_coda(qpron)
    cv, cc = stressed_vowel_and_coda(cpron)
    if qv and qv == cv and qc == cc:
        return "perfect"
    if qv and qv == cv and qc != cc:
        return "assonant"
    if qc and qc == cc and qv != cv:
        return "consonant"
    # fallback slant on *final* vowel nucleus
    qvf, _ = final_vowel_and_coda(qpron)
    cvf, _ = final_vowel_and_coda(cpron)
    if qvf and qvf == cvf:
        return "slant"
    return "none"

# ----------------------------------------------------------------------------
# Phrase support
# ----------------------------------------------------------------------------
def phrase_to_pron(phrase: str) -> List[str]:
    """Build a phrase pronunciation by concatenating token prons (using DB where possible).
    If a token is OOV and LLM_OOV_G2P is enabled with g2p available, we fall back to it;
    otherwise we *skip* that token (keeps determinism).
    """
    s = (phrase or "").strip()
    if not s:
        return []
    tokens = [t for t in _TOKEN_SPLIT.split(_clean_word(s)) if t]
    out: List[str] = []
    for t in tokens:
        p = _get_pron(t)
        if not p and getattr(FLAGS, "LLM_OOV_G2P", False) and _G2P is not None:
            try:
                guess = _G2P(t) or []
                p = [ph for ph in guess if ph and ph[0].isalpha() and ph[0].isupper()]
            except Exception:
                p = []
        if p:
            out.extend(p)
    return out

# ----------------------------------------------------------------------------
# Rarity & scoring
# ----------------------------------------------------------------------------
def _rarity_score(word: str) -> float:
    """Normalize wordfreq ZIPF to 0..1 where 1 is rarest. Clamped."""
    try:
        z = zipf_frequency(word.lower(), "en")
    except Exception:
        z = 1.0
    val = (7.5 - float(z)) / 7.5  # invert + normalize
    if val < 0: val = 0.0
    if val > 1: val = 1.0
    return val

def _score_item(rtype: str, stress_eq: bool, rarity: float) -> float:
    base = {"perfect": 1.0, "assonant": 0.86, "slant": 0.75, "consonant": 0.70, "none": 0.0}.get(rtype, 0.0)
    if stress_eq:
        base += 0.02
    return base * (0.85 + 0.15 * rarity)

# ----------------------------------------------------------------------------
# Flat search (internal)
# ----------------------------------------------------------------------------
def _search_flat(query: str,
                 rhyme_type: str = "any",
                 include_consonant: bool = False,
                 syllable_min: int = 1,
                 syllable_max: int = 8,
                 cap_internal: int = 2000) -> List[Dict[str, object]]:
    """Return a flat list of scored candidates for the given query."""
    q_clean = _clean_word(query)
    if not q_clean:
        return []

    if _USE_FALLBACK:
        data = FALLBACK_FLAT_RESULTS.get(q_clean, [])
        out: List[Dict[str, object]] = []
        for item in data:
            if item["syllables"] < syllable_min or item["syllables"] > syllable_max:
                continue
            if item["rhyme_type"] == "consonant" and not include_consonant:
                continue
            if rhyme_type != "any" and item["rhyme_type"] != rhyme_type:
                continue
            out.append(dict(item))
            if len(out) >= cap_internal:
                break
        return out

    # Obtain query pron; decide if it's a phrase
    query_is_phrase = (" " in q_clean) or (not _db_row_for_word(q_clean))
    if query_is_phrase:
        qpron = phrase_to_pron(q_clean)
        if not qpron:
            return []
        # pivot on last token present in DB for breadth
        tokens = [t for t in _TOKEN_SPLIT.split(q_clean) if t]
        pivot = None
        for t in reversed(tokens):
            if _db_row_for_word(t):
                pivot = t
                break
        pool_rows: List[sqlite3.Row] = _candidate_rows_by_keys(*(_get_keys(pivot) or ("","","","",""))) if pivot else []
    else:
        qpron = _get_pron(q_clean) or []
        pool_rows = _candidate_rows_by_keys(*(_get_keys(q_clean) or ("","","","","")))

    out: List[Dict[str, object]] = []
    seen: set[str] = set()
    sp_q = stress_pattern_str(qpron)

    for r in pool_rows:
        word = r["word"]
        if not word or word == q_clean or word in seen:
            continue
        seen.add(word)
        try:
            pron = json.loads(r["pron"]) if isinstance(r["pron"], (bytes, bytearray)) else (json.loads(r["pron"]) if isinstance(r["pron"], str) and r["pron"].startswith("[") else r["pron"])
        except Exception:
            pron = r["pron"]
        if not isinstance(pron, list):
            if isinstance(pron, str):
                pron = [p for p in pron.split() if p]
            else:
                continue

        syls = int(r["syls"]) if r["syls"] is not None else syllable_count(pron)
        if syls < syllable_min or syls > syllable_max:
            continue

        rtype = classify_rhyme(qpron, pron)
        if rtype == "none":
            continue
        if rtype == "consonant" and not include_consonant:
            continue
        if rhyme_type != "any" and rtype != rhyme_type:
            continue

        stress_eq = (sp_q and (sp_q == stress_pattern_str(pron)))
        score = _score_item(rtype, bool(stress_eq), _rarity_score(word))

        out.append({
            "word": word,
            "rhyme_type": rtype,
            "score": float(score),
            "is_multiword": (" " in word or "-" in word),
            "syllables": int(syls),
        })
        if len(out) >= cap_internal * 2:  # safety against pathological pools
            break

    out.sort(key=lambda x: (-x["score"], x["syllables"], x["word"]))  # deterministic
    return out[:cap_internal]

# ----------------------------------------------------------------------------
# Public: search_word (flat) and find_rhymes (bucketed)
# ----------------------------------------------------------------------------
def search_word(word: str,
                rhyme_type: str = "any",
                slant_strength: float = 0.5,
                syllable_min: int = 1,
                syllable_max: int = 8,
                max_results: int = 500,
                include_pron: bool = False,
                include_consonant: bool = False) -> List[Dict[str, object]]:
    """Flat search API used by some tests/tools."""
    flat = _search_flat(word,
                        rhyme_type=rhyme_type,
                        include_consonant=include_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max_results)
    if include_pron:
        for it in flat:
            w = str(it["word"])
            it["pron"] = _get_pron(w) or []
    return flat

def _to_bucket_item(item: Dict[str, object]) -> Dict[str, object]:
    out = {"type": item["rhyme_type"], "score": float(item["score"])}
    w = str(item["word"])
    if " " in w or "-" in w:
        out["phrase"] = w
    else:
        out["name"] = w
    return out

def find_rhymes(query: str,
                max_results: int = 20,
                include_consonant: bool = False,
                syllable_min: int = 1,
                syllable_max: int = 8,
                slant_strength: float = 0.5,
                include_pron: bool = False,
                **kwargs) -> Dict[str, List[Dict[str, object]]]:
    """Bucketed API for the UI.

    Returns: {
      "uncommon": [ {name, type=perfect|assonant|..., score}, ... ],
      "slant":    [ {name, type=assonant|slant|consonant, score}, ... ],
      "multiword":[ {phrase, type=..., score}, ... ]
    }
    """
    # widen internal cap then cap per bucket
    flat = _search_flat(query,
                        rhyme_type="any",
                        include_consonant=include_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max(1200, max_results * 12))

    uncommon: List[Dict[str, object]] = []
    slant: List[Dict[str, object]] = []
    multi: List[Dict[str, object]] = []

    for it in flat:
        typ = str(it["rhyme_type"])
        is_multi = bool(it["is_multiword"])
        b = _to_bucket_item(it)

        if typ == "perfect":
            uncommon.append(b)
        elif typ in ("assonant", "slant"):
            slant.append(b)
        elif typ == "consonant":
            if include_consonant:
                slant.append(b)

        if is_multi:
            multi.append(b)

    # Stable sorts
    def _ku(x): return (-float(x.get("score", 0.0)), x.get("name",""))
    def _ks(x):
        order = {"assonant":0, "slant":1, "consonant":2}
        return (order.get(x.get("type","slant"), 9), -float(x.get("score",0.0)), x.get("name","") or x.get("phrase",""))
    def _km(x): return (-float(x.get("score", 0.0)), x.get("phrase",""))

    uncommon.sort(key=_ku)
    slant.sort(key=_ks)
    multi.sort(key=_km)

    # Backfill uncommon with rare assonants (clearly labeled in UI) if under cap
    if len(uncommon) < max_results:
        needed = max_results - len(uncommon)
        extras = [x for x in slant if x.get("type") == "assonant"]
        uncommon.extend(extras[:needed])

    return {
        "uncommon": uncommon[:max_results],
        "slant": slant[:max_results],
        "multiword": multi[:max_results],
    }

# Legacy alias for older imports
search = find_rhymes

__all__ = [
    "search_word",
    "find_rhymes",
    "classify_rhyme",
    "stressed_vowel_and_coda",
    "final_vowel_and_coda",
    "phrase_to_pron",
    "syllable_count",
    "stress_pattern_str",
]
