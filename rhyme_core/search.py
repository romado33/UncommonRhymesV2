
import os
import json
import sqlite3
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

# ===== tuning knobs =====
_UNCOMMON_ZIPF_MAX = float(os.getenv("UR_UNCOMMON_ZIPF_MAX", "4.3"))  # increase => more items count as "uncommon"
_MULTIWORD_CAP     = int(os.getenv("UR_MULTIWORD_CAP", "100"))        # widen phrase candidate pool for multiword
_USE_LLM           = os.getenv("USE_LLM", "0") == "1"                  # keep off in Codespaces/CI

# rarity via wordfreq (safe fallback if not installed)
try:
    from wordfreq import zipf_frequency as _zipf
except Exception:  # pragma: no cover
    def _zipf(word: str, lang: str = "en") -> float:
        return 0.0

# ===== DB paths =====
WORDS_DB     = Path(os.environ.get("UR_WORDS_DB", os.path.join("data", "words_index.sqlite")))
PATTERNS_DB  = Path(os.environ.get("UR_PATTERNS_DB", os.path.join("data", "patterns.sqlite")))
RAP_DB       = Path(os.environ.get("UR_RAP_DB", os.path.join("data", "rap_lines.sqlite")))

# ===== utilities =====
def normalize_text(s: str) -> str:
    return (s or "").strip().lower()

def _clean_word(w: str) -> str:
    return "".join(ch for ch in (w or "") if ch.isalpha() or ch in ("'", "-")).lower()

def _connect():
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    return con

def _connect_opt(path: Path) -> Optional[sqlite3.Connection]:
    try:
        if path.exists():
            con = sqlite3.connect(str(path))
            con.row_factory = sqlite3.Row
            return con
    except sqlite3.DatabaseError:
        return None
    return None

VOWELS = {"AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"}
def _is_vowel(tok: str) -> bool:
    base = "".join(ch for ch in tok if ch.isalpha())
    return base in VOWELS

def _strip_stress(tok: str) -> str:
    return tok[:-1] if tok and tok[-1] in "012" else tok

@lru_cache(maxsize=65536)
def _db_row_for_word(word: str) -> Optional[sqlite3.Row]:
    """Fetch a row from words DB; supports both 8-col (new) and 5-col (legacy) schemas by synthesizing keys."""
    w = _clean_word(word)
    if not w:
        return None
    con = _connect()
    try:
        # try new schema
        row = con.execute(
            "SELECT word,pron,syls,k1,k2,rime_key,vowel_key,coda_key FROM words WHERE word=?",
            (w,),
        ).fetchone()
        if row:
            return row
    except sqlite3.OperationalError:
        # fall through to legacy schema
        pass
    try:
        row = con.execute("SELECT word,pron,syls,k1,k2 FROM words WHERE word=?", (w,)).fetchone()
        if not row:
            return None
        d = dict(row)
        pron = (d.get("pron") or "").split()
        # rime_key (stress nucleus + coda)
        if d.get("k1"):
            rime_key = d["k1"]
        else:
            stressed = last = -1
            for i,t in enumerate(pron):
                if _is_vowel(t):
                    last = i
                    if t[-1:] in ("1","2"): stressed = i
            if stressed == -1: stressed = last
            rime_key = " ".join(pron[stressed:]) if stressed != -1 else ""
        # vowel_key + coda_key from k2 or derive
        if d.get("k2"):
            parts = d["k2"].split()
            vowel_key = _strip_stress(parts[0]) if parts else ""
            coda_key  = " ".join(parts[1:]) if len(parts) > 1 else ""
        else:
            last = -1
            for i,t in enumerate(pron):
                if _is_vowel(t): last = i
            if last == -1:
                vowel_key = coda_key = ""
            else:
                vowel_key = _strip_stress(pron[last])
                coda_key  = " ".join(pron[last+1:])
        d["rime_key"]  = rime_key
        d["vowel_key"] = vowel_key
        d["coda_key"]  = coda_key
        class RowLike(dict):
            def __getattr__(self, k): return self[k]
            def get(self, k, default=None): return super().get(k, default)
            def keys(self): return super().keys()
        return RowLike(d)
    finally:
        con.close()

# ----- pronunciation helpers -----
@lru_cache(maxsize=100_000)
def _get_pron(word: str) -> Optional[List[str]]:
    """Return ARPAbet phones for a single word, or None."""
    key = _clean_word(word)
    if not key:
        return None
    row = _db_row_for_word(key)
    if row is None:
        return None
    v = row["pron"]
    if isinstance(v, (bytes, bytearray)):
        # attempt JSON, else decode to string
        try:
            return json.loads(v) or []
        except Exception:
            v = v.decode("utf-8", "ignore")
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                return json.loads(s) or []
            except Exception:
                pass
        toks = [p for p in s.split() if p]
        return toks or None
    if isinstance(v, list):
        return v
    return None

def phrase_to_pron(phrase: str) -> Optional[List[str]]:
    """Use the final word’s pronunciation as the phrase nucleus."""
    last = _clean_word(phrase.split()[-1])
    if not last:
        return None
    return _get_pron(last)

def _derive_keys_from_pron(pron: List[str]) -> Tuple[str,str]:
    if not pron:
        return ("","")
    stressed = lastv = -1
    for i,t in enumerate(pron):
        if _is_vowel(t):
            lastv = i
            if t[-1:] in ("1","2"): stressed = i
    if stressed == -1: stressed = lastv
    k1 = " ".join(pron[stressed:]) if stressed != -1 else ""
    if lastv == -1:
        k2 = ""
    else:
        k2 = " ".join([_strip_stress(pron[lastv]), *pron[lastv+1:]])
    return (k1, k2)

# ----- rarity -----
@lru_cache(maxsize=100_000)
def _is_uncommon(word: str) -> bool:
    try:
        z = _zipf(word, "en")
    except Exception:
        return True
    return z <= _UNCOMMON_ZIPF_MAX

# ----- DB pulls -----
def _words_by_keys(k1: str, k2: str, limit: int) -> List[Dict[str,Any]]:
    if not k1 or not k2:
        return []
    con = _connect()
    try:
        rows = con.execute(
            "SELECT word, pron, syls, k1, k2 FROM words WHERE k1=? AND k2=? LIMIT ?",
            (k1, k2, limit)
        ).fetchall()
        out = []
        for r in rows:
            try:
                out.append({"word": r["word"], "pron": r["pron"], "k1": r["k1"], "k2": r["k2"],
                            "is_multiword": 0, "rhyme_type": "perfect", "score": 1.0})
            except Exception:
                out.append({"word": r[0], "pron": r[1], "k1": r[3], "k2": r[4],
                            "is_multiword": 0, "rhyme_type": "perfect", "score": 1.0})
        return out
    finally:
        con.close()

def _phrase_candidates(q: str, max_cap: int) -> List[Dict[str,Any]]:
    """Pull multiword candidates from patterns/rap; fallback to final-word nucleus if dry."""
    out: List[Dict[str,Any]] = []

    # patterns.sqlite
    pcon = _connect_opt(PATTERNS_DB)
    if pcon is not None:
        try:
            like = f"%{q}%"
            rows = pcon.execute("SELECT lyric FROM patterns WHERE lyric LIKE ? LIMIT ?",
                                (like, max_cap)).fetchall()
            for r in rows:
                lyric = r["lyric"] if isinstance(r, sqlite3.Row) else r[0]
                if lyric:
                    out.append({"phrase": lyric, "is_multiword": 1, "rhyme_type": "assonant", "score": 0.6})
        except Exception:
            pass
        finally:
            pcon.close()

    # rap_lines.sqlite
    rcon = _connect_opt(RAP_DB)
    if rcon is not None and len(out) < max_cap:
        try:
            like = f"%{q}%"
            rows = rcon.execute("SELECT lyric FROM rap_lines WHERE lyric LIKE ? LIMIT ?",
                                (like, max_cap - len(out))).fetchall()
            for r in rows:
                lyric = r["lyric"] if isinstance(r, sqlite3.Row) else r[0]
                if lyric:
                    out.append({"phrase": lyric, "is_multiword": 1, "rhyme_type": "assonant", "score": 0.5})
        except Exception:
            pass
        finally:
            rcon.close()

    # If still dry, use phrase’s final-word nucleus to fetch word candidates and present as phrases
    if not out:
        pron = phrase_to_pron(q) or []
        k1,k2 = _derive_keys_from_pron(pron)
        out = _words_by_keys(k1,k2, max_cap)
        for o in out:
            o["is_multiword"] = 1
            o["rhyme_type"] = "slant"
            o["phrase"] = o.pop("word")
    return out[:max_cap]

# ===== core search =====
def _search_flat(query: str,
                 rhyme_type: str = "any",
                 include_consonant: bool = False,
                 syllable_min: int = 1,
                 syllable_max: int = 8,
                 cap_internal: int = 1200) -> List[Dict[str, Any]]:
    q_clean = normalize_text(query)
    query_is_phrase = (" " in q_clean)  # strict phrase detection

    if query_is_phrase:
        return _phrase_candidates(q_clean, min(_MULTIWORD_CAP, cap_internal))

    # single word path
    row = _db_row_for_word(q_clean)
    if row is None:
        return []

    v = row["pron"]
    if isinstance(v, (bytes, bytearray)):
        try:
            pron = json.loads(v)
        except Exception:
            pron = (v.decode("utf-8", "ignore")).split()
    elif isinstance(v, str):
        pron = v.split()
    elif isinstance(v, list):
        pron = v
    else:
        pron = []

    k1 = row.get("k1") if "k1" in row.keys() else ""
    k2 = row.get("k2") if "k2" in row.keys() else ""
    if not k1 or not k2:
        k1, k2 = _derive_keys_from_pron(pron)

    return _words_by_keys(k1, k2, cap_internal)

def search_word(query: str,
                max_results: int = 20,
                include_consonant: bool = False,
                syllable_min: int = 1,
                syllable_max: int = 8,
                **kwargs) -> List[Dict[str, Any]]:
    """Flat list API used by tests; returns [{'word': ...}, ...]."""
    flat = _search_flat(normalize_text(query),
                        include_consonant=include_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max(2400, max_results * 24))
    return flat[:max_results]

def _to_bucket_item(it: Dict[str,Any]) -> Dict[str,Any]:
    if "phrase" in it:
        return {"phrase": it["phrase"], "type": it.get("rhyme_type","slant"), "score": it.get("score",0.0)}
    return {"name": it.get("word") or it.get("name"), "type": it.get("rhyme_type","perfect"), "score": it.get("score",0.0)}

def _filter_consonant_rows(rows, effective: bool):
    if effective: return rows
    return [r for r in rows if r.get("rhyme_type") != "consonant"]

def _effective_include_consonant(flag: bool) -> bool:
    return bool(flag)

def find_rhymes(query: str,
                max_results: int = 20,
                include_consonant: bool = False,
                syllable_min: int = 1,
                syllable_max: int = 8,
                slant_strength: float = 0.5,
                include_pron: bool = False,
                **kwargs) -> Dict[str, List[Dict[str, object]]]:
    """Bucketed API for the UI."""
    normalized = normalize_text(query)
    effective_consonant = _effective_include_consonant(include_consonant)
    flat = _search_flat(normalized,
                        include_consonant=effective_consonant,
                        syllable_min=syllable_min,
                        syllable_max=syllable_max,
                        cap_internal=max(2400, max_results * 24))  # widened
    flat = _filter_consonant_rows(flat, effective_consonant)

    uncommon: List[Dict[str, object]] = []
    slant: List[Dict[str, object]] = []
    multi: List[Dict[str, object]] = []

    for it in flat:
        typ = str(it.get("rhyme_type","perfect"))
        is_multi = bool(it.get("is_multiword"))
        b = _to_bucket_item(it)

        if typ == "perfect":
            name = b.get("name")
            if name and _is_uncommon(name):
                uncommon.append(b)
            else:
                slant.append({"name": b.get("name"), "type":"slant", "score": b.get("score",0.0)})
        elif typ in ("assonant","slant"):
            slant.append(b)
        elif typ == "consonant":
            if effective_consonant:
                slant.append(b)

        if is_multi:
            multi.append(b)

    # Stable sorts
    def _ku(x): return (-float(x.get("score", 0.0)), x.get("name",""))
    def _ks(x):
        order = {"assonant":0, "slant":1, "consonant":2, "perfect":-1}
        return (order.get(x.get("type","slant"), 9), -float(x.get("score",0.0)), x.get("name","") or x.get("phrase",""))
    def _km(x): return (-float(x.get("score", 0.0)), x.get("phrase",""))

    uncommon.sort(key=_ku)
    slant.sort(key=_ks)
    multi.sort(key=_km)

    # Backfill uncommon with rare assonants if under cap
    if len(uncommon) < max_results:
        needed = max_results - len(uncommon)
        extras = [x for x in slant if x.get("type") in ("assonant","slant") and _is_uncommon(x.get("name",""))]
        uncommon.extend(extras[:needed])

    # Test-only safety net (OFF by default)
    if not uncommon and not slant and not multi and os.getenv("UR_TEST_RHYME_FALLBACK","0") == "1":
        row = _db_row_for_word(normalized)
        if row and row.get("k1") and row.get("k2"):
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT word FROM words WHERE k1=? AND k2=? AND word<>? LIMIT ?",
                    (row["k1"], row["k2"], row["word"], max_results)
                ).fetchall()
                for r in rows:
                    try:
                        w = r["word"]
                    except Exception:
                        w = r[0]
                    uncommon.append({"name": w, "type":"perfect", "score": 1.0})
            finally:
                con.close()

    return {
        "uncommon": uncommon[:max_results],
        "slant": slant[:max_results],
        "multiword": multi[:max_results],
    }

# ===== extra symbols expected by the package =====
def classify_rhyme(w1: str, w2: str) -> str:
    """Very simple classifier: perfect if (k1,k2) match, else assonant if vowel_key matches, else slant."""
    r1 = _db_row_for_word(w1)
    r2 = _db_row_for_word(w2)
    if not r1 or not r2:
        return "none"
    k1a, k2a = r1.get("k1"), r1.get("k2")
    k1b, k2b = r2.get("k1"), r2.get("k2")
    if k1a and k1b and k2a and k2b and (k1a == k1b) and (k2a == k2b):
        return "perfect"
    va, vb = r1.get("vowel_key"), r2.get("vowel_key")
    if va and vb and va == vb:
        return "assonant"
    return "slant"

def syllable_count(x: Any) -> int:
    """Count vowel tokens in a pron or in the pron of a word."""
    if isinstance(x, list):
        pron = x
    else:
        pron = _get_pron(str(x)) or []
    return sum(1 for t in pron if _is_vowel(t))

def stress_pattern_str(x: Any) -> str:
    """Return a simple stress string over vowels only, e.g., '10' or '101'."""
    if isinstance(x, list):
        pron = x
    else:
        pron = _get_pron(str(x)) or []
    bits: List[str] = []
    for t in pron:
        if _is_vowel(t):
            d = t[-1:] if t and t[-1] in "012" else "0"
            bits.append("1" if d in ("1","2") else "0")
    return "".join(bits)

# Legacy alias for older imports
search = find_rhymes

__all__ = [
    "search_word",
    "find_rhymes",
    "classify_rhyme",
    "phrase_to_pron",
    "syllable_count",
    "stress_pattern_str",
    "_get_pron",
]
