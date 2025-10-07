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

Assumptions
-----------
- SQLite DB at data/words_index.sqlite with schema:
  words(word TEXT PRIMARY KEY, pron TEXT JSON, syls INT,
        k1 TEXT, k2 TEXT, rime_key TEXT, vowel_key TEXT, coda_key TEXT)

Determinism
-----------
All operations are deterministic given the DB contents and flags.
No randomization; LLM hooks are OFF by default.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# External deps
from wordfreq import zipf_frequency  # rarity

from config import FLAGS

from rhyme_core.normalize import normalize_text, normalize_word
from rhyme_core.prosody import syllable_count, stress_pattern_str  # type: ignore

from .fallback import get_fallback_pron, iter_fallback_items
from .lfs_guard import looks_like_lfs_pointer

# Optional G2P (used only when USE_LLM=1 and g2p_en is available)
if FLAGS.get("USE_LLM"):
    try:
        from g2p_en import G2p  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        G2p = None  # type: ignore
        _G2P = None  # type: ignore
    else:
        _G2P = None  # type: ignore
else:  # pragma: no cover - default path when USE_LLM=0
    G2p = None  # type: ignore
    _G2P = None  # type: ignore

# ----------------------------------------------------------------------------
# Paths / DB
# ----------------------------------------------------------------------------
DATA_DIR = Path("data")
WORDS_DB = DATA_DIR / "words_index.sqlite"
PATTERNS_DB = DATA_DIR / "patterns_small.db"

logging.basicConfig(level=getattr(logging, str(FLAGS.get("LOG_LEVEL", "INFO")).upper(), logging.INFO))
LOGGER = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Regex & phoneme helpers
# ----------------------------------------------------------------------------
_VOWELS = {"AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"}
_STRIP_STRESS = re.compile(r"(\d)")
_TOKEN_SPLIT = re.compile(r"[\\s\\-]+")


def _clean_word(w: str) -> str:
    """Normalize text and keep alphanumerics for key lookup."""
    return normalize_word(w)

def _base_phone(p: str) -> str:
    """Remove stress digits from a CMU phone (e.g., AY1 -> AY)."""
    return _STRIP_STRESS.sub("", p)

# ----------------------------------------------------------------------------
# DB accessors
# ----------------------------------------------------------------------------
def _db_is_usable() -> bool:
    reasons: List[str] = []
    if not WORDS_DB.exists():
        reasons.append("words_index.sqlite missing")
    elif looks_like_lfs_pointer(WORDS_DB):
        reasons.append("words_index.sqlite is a Git LFS pointer")
    else:
        try:
            with sqlite3.connect(str(WORDS_DB)) as con:
                con.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        except sqlite3.DatabaseError:
            reasons.append("words_index.sqlite not readable")

    if not PATTERNS_DB.exists():
        reasons.append("patterns_small.db missing")
    elif looks_like_lfs_pointer(PATTERNS_DB):
        reasons.append("patterns_small.db is a Git LFS pointer")

    if reasons:
        for msg in reasons:
            LOGGER.warning("%s; falling back to built-in dataset", msg)
        return False
    return True


_USE_FALLBACK = not _db_is_usable()

if _USE_FALLBACK and not FLAGS.get("ALLOW_FALLBACK", True):
    raise RuntimeError("Rhyme database unavailable and fallbacks disabled")


def _ensure_g2p():
    global _G2P
    if not FLAGS.get("USE_LLM"):
        return None
    if _G2P is None and 'G2p' in globals() and G2p is not None:
        try:
            _G2P = G2p()  # type: ignore[call-arg]
        except Exception:
            _G2P = None
    return _G2P


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
        row = con.execute(
            "SELECT word,pron,syls,k1,k2,rime_key,vowel_key,coda_key FROM words WHERE word=?",
            (w,),
        ).fetchone()
        return row
    finally:
        con.close()

# Cache pronunciation lookups aggressively; they're pure and heavily reused.
@lru_cache(maxsize=100_000)
def _get_pron(word: str) -> List[str] | None:
    """Return ARPAbet phones for a *single* word, or None if not present."""
    key = _clean_word(word)
    if not key:
        return None

    row = _db_row_for_word(word)
    if row is not None:
        try:
            return json.loads(row["pron"]) or []
        except Exception:
            return None

    fallback_pron = get_fallback_pron(word)
    if fallback_pron:
        return list(fallback_pron)

    g2p = _ensure_g2p()
    if g2p is not None:
        try:
            phones = g2p(key) or []
            return [p for p in phones if p and p[0].isalpha() and p[0].isupper()]
        except Exception:
            return None
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


@lru_cache(maxsize=100_000)
def _final_coda_cached(pron_key: Tuple[str, ...]) -> Tuple[str, ...]:
    if not pron_key:
        return tuple()
    j = -1
    for i in range(len(pron_key) - 1, -1, -1):
        if _base_phone(pron_key[i]) in _VOWELS:
            j = i
            break
    if j < 0:
        return tuple()
    return tuple(_base_phone(p) for p in pron_key[j + 1 :])


def _final_coda(pron: Sequence[str]) -> Tuple[str, ...]:
    return _final_coda_cached(tuple(pron))


def final_vowel_and_coda(pron: Sequence[str]) -> Tuple[str, Tuple[str,...]]:
    j = -1
    for i in range(len(pron)-1, -1, -1):
        if _base_phone(pron[i]) in _VOWELS:
            j = i; break
    return _vowel_and_coda_from_index(pron, j)


@lru_cache(maxsize=100_000)
def _norm_tail_cached(pron_key: Tuple[str, ...]) -> Tuple[str, ...]:
    if not pron_key:
        return tuple()
    idx = _last_primary_vowel_index(pron_key)
    if idx < 0:
        return tuple(_base_phone(p) for p in pron_key)
    return tuple(_base_phone(p) for p in pron_key[idx:])


def _norm_tail(pron: Sequence[str]) -> Tuple[str, ...]:
    return _norm_tail_cached(tuple(pron))

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
    normalized = normalize_text(s)
    tokens = [t for t in _TOKEN_SPLIT.split(normalized) if t]
    out: List[str] = []
    for t in tokens:
        p = _get_pron(t)
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
    # Typical english words are 3-7 range; invert + normalize
    val = (7.5 - float(z)) / 7.5
    if val < 0: val = 0.0
    if val > 1: val = 1.0
    return val

def _score_item(rtype: str, stress_eq: bool, rarity: float) -> float:
    # base by type
    base = {"perfect": 1.0, "assonant": 0.86, "slant": 0.75, "consonant": 0.70, "none": 0.0}.get(rtype, 0.0)
    # add tiny bonus for exact stress alignment
    if stress_eq:
        base += 0.02
    # blend rarity mild (keeps determinism; prevents overdominance by ultrarare junk)
    return base * (0.85 + 0.15 * rarity)


def _effective_include_consonant(user_override: bool) -> bool:
    if user_override:
        return True
    return not FLAGS.get("DISABLE_CONSONANT_RHYMES", True)


def _filter_consonant_rows(rows: List[Dict[str, object]], include_consonant: bool) -> List[Dict[str, object]]:
    if include_consonant:
        return rows
    if not FLAGS.get("DISABLE_CONSONANT_RHYMES", True):
        return rows
    return [row for row in rows if row.get("rhyme_type") != "consonant"]


def _fallback_candidates(query: str,
                         rhyme_type: str,
                         include_consonant: bool,
                         syllable_min: int,
                         syllable_max: int,
                         cap_internal: int) -> List[Dict[str, object]]:
    qpron_tuple = get_fallback_pron(query)
    if not qpron_tuple:
        return []
    qpron = list(qpron_tuple)
    qstress = stress_pattern_str(qpron)
    out: List[Dict[str, object]] = []
    normalized_query = normalize_text(query)
    for word, pron_tuple in iter_fallback_items(exclude=[normalized_query]):
        if normalize_text(word) == normalized_query:
            continue
        pron = list(pron_tuple)
        rtype = classify_rhyme(qpron, pron)
        if rtype == "none":
            continue
        if rtype == "consonant" and not include_consonant:
            continue
        if rhyme_type != "any" and rtype != rhyme_type:
            continue
        syls = sum(1 for ph in pron if ph and ph[-1].isdigit())
        if not syls:
            syls = max(1, syllable_count(word))
        if syls < syllable_min or syls > syllable_max:
            continue
        score = _score_item(rtype, stress_pattern_str(pron) == qstress, _rarity_score(word))
        out.append({
            "word": word,
            "rhyme_type": rtype,
            "score": float(score),
            "is_multiword": False,
            "syllables": int(syls),
        })
        if len(out) >= cap_internal:
            break
    out.sort(key=lambda x: (-x["score"], x["syllables"], x["word"]))
    return out

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
        return _fallback_candidates(
            query,
            rhyme_type,
            include_consonant,
            syllable_min,
            syllable_max,
            cap_internal,
        )

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
            # DB may already store list in python object (sqlite adapter), fallback:
            pron = r["pron"]
        if not isinstance(pron, list):
            # if pron is a space-separated string from older builds
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
                slant_strength: float = 0.5,  # kept for API compatibility; slant weighting is internal
                syllable_min: int = 1,
                syllable_max: int = 8,
                max_results: int = 500,
                include_pron: bool = False,
                include_consonant: bool = False) -> List[Dict[str, object]]:
    """Flat search API used by some tests/tools."""
    normalized = normalize_text(word)
    effective_consonant = _effective_include_consonant(include_consonant)
    flat = _search_flat(normalized,
                        rhyme_type=rhyme_type,
                        include_consonant=effective_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max_results)
    flat = _filter_consonant_rows(flat, effective_consonant)
    if include_pron:
        # attach pron if caller asked (extra SQLite hits avoided intentionally for speed)
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
    normalized = normalize_text(query)
    effective_consonant = _effective_include_consonant(include_consonant)
    flat = _search_flat(normalized,
                        rhyme_type="any",
                        include_consonant=effective_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max(1200, max_results * 12))
    flat = _filter_consonant_rows(flat, effective_consonant)

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
            if effective_consonant:
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
