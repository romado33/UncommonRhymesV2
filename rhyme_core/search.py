from __future__ import annotations
import sqlite3, json, re, io, csv
from functools import lru_cache
from typing import List, Tuple, Dict
from unidecode import unidecode
from wordfreq import zipf_frequency
from .phonetics import key_k1, key_k2

# Optional OOV fallback
try:
    from g2p_en import G2p
except Exception:
    G2p = None

VALID_WORD_RE = re.compile(r"^[a-z][a-z'\- ]*$")

def _clean(text: str) -> str:
    return re.sub(r"[^a-zA-Z'\- ]+", "", unidecode(text)).strip().lower()

@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    con = sqlite3.connect("data/words_index.sqlite", check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

# ---------- rarity ----------
def _rarity_score(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0

# ---------- g2p ----------
@lru_cache(maxsize=1)
def _g2p():
    return G2p() if G2p is not None else None

def _g2p_fallback(word_or_phrase: str) -> list[str] | None:
    g2p = _g2p()
    if not g2p:
        return None
    toks = g2p(word_or_phrase)
    phones = []
    for t in toks:
        t = t.strip()
        if not t:
            continue
        if any(ch.isdigit() for ch in t) or t.isalpha():
            phones.append(t.upper())
    out = [re.sub(r"[^A-Z0-9]", "", p) for p in phones if re.match(r"^[A-Z]{1,3}\d?$", p)]
    return out or None

# ---------- vowels / tails / classifier ----------
_VOWELS = {
    "AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"
}

_EQV = {  # voicing equivalence for consonant-only check
    "S":"Z", "Z":"Z",
    "T":"D", "D":"D",
    "K":"G", "G":"G",
    "P":"B", "B":"B",
    "F":"V", "V":"V",
    "CH":"JH", "JH":"JH",
}
def _eqv(p: str) -> str: return _EQV.get(p, p)

def _is_vowel(p: str) -> bool:
    core = p[:-1] if p and p[-1].isdigit() else p
    return core in _VOWELS

def _stress_digit(p: str) -> int:
    return int(p[-1]) if p and p[-1].isdigit() else 0

def _vowel_core(p: str) -> str:
    return (p[:-1] if p and p[-1].isdigit() else p)

def _tail_parts(pron: List[str]) -> tuple[list[str], str, tuple[str, ...]]:
    if not pron:
        return [], "", ()
    idx = -1
    for i in range(len(pron)-1, -1, -1):
        if _is_vowel(pron[i]) and _stress_digit(pron[i]) in (1, 2):
            idx = i; break
    if idx == -1:
        for i in range(len(pron)-1, -1, -1):
            if _is_vowel(pron[i]): idx = i; break
    if idx == -1: return [], "", ()
    tail = pron[idx:]
    nuc  = _vowel_core(pron[idx])
    coda = tuple(p for p in tail[1:] if not _is_vowel(p))
    return tail, nuc, coda

def _norm_tail(pron: List[str]) -> tuple[str, ...]:
    tail, _, _ = _tail_parts(pron)
    norm: list[str] = []
    for p in tail:
        norm.append(_vowel_core(p) if _is_vowel(p) else p)
    return tuple(norm)

def _lev(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    la, lb = len(a), len(b)
    dp = [list(range(lb+1))] + [[i] + [0]*lb for i in range(1, la+1)]
    for i in range(1, la+1):
        for j in range(1, lb+1):
            cost = 0 if a[i-1] == b[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[la][lb]

# --- NEW: helpers for final-coda consonant rhyme ---
def _last_vowel_idx(pron: List[str]) -> int:
    """Index of the last vowel phone in the whole word; -1 if none."""
    for i in range(len(pron) - 1, -1, -1):
        p = pron[i]
        core = p[:-1] if p and p[-1].isdigit() else p
        if core in _VOWELS:
            return i
    return -1

def _final_coda(pron: List[str]) -> tuple[str, ...]:
    """Consonants strictly after the last vowel of the word (the true word ending)."""
    j = _last_vowel_idx(pron)
    if j == -1:
        return ()
    return tuple(p for p in pron[j+1:] if not _is_vowel(p))

def classify_rhyme(pron_a: List[str], pron_b: List[str]) -> str:
    if not pron_a or not pron_b:
        return "none"

    tail_a, nuc_a, coda_a = _tail_parts(pron_a)
    tail_b, nuc_b, coda_b = _tail_parts(pron_b)
    if not tail_a or not tail_b:
        return "none"

    # Perfect: identical normalized tails (vowel stress removed)
    norm_a, norm_b = _norm_tail(pron_a), _norm_tail(pron_b)
    if norm_a == norm_b:
        return "perfect"

    # Consonant: same FINAL CODA (true word ending), different vowel nucleus
    fc_a = tuple(_eqv(p) for p in _final_coda(pron_a))
    fc_b = tuple(_eqv(p) for p in _final_coda(pron_b))
    if fc_a and (fc_a == fc_b) and (nuc_a != nuc_b):
        return "consonant"

    # Assonant: same vowel nucleus, different coda (in the tail)
    if (nuc_a == nuc_b) and (coda_a != coda_b):
        return "assonant"

    # Otherwise, allow a small edit distance on normalized tails as "slant"
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

# ---------- pronunciations ----------
def _get_pron_all(word: str) -> list[list[str]]:
    row = _db().execute("SELECT pron FROM words WHERE word=?", (word,)).fetchone()
    prons = []
    if row:
        try:
            pr = json.loads(row["pron"])
            if isinstance(pr, list) and pr and isinstance(pr[0], str):
                prons.append(pr)
            elif isinstance(pr, list) and pr and isinstance(pr[0], list):
                prons.extend(pr)
        except Exception:
            pass
    if not prons:
        gp = _g2p_fallback(word)
        if gp: prons.append(gp)
    return prons

def _best_match_pron(base_pron: list[str], cand_prons: list[list[str]]) -> list[str] | None:
    best, best_q = None, -1.0
    for cp in cand_prons:
        rtype = classify_rhyme(base_pron, cp)
        q = {"perfect":1.0,"consonant":0.9,"assonant":0.85,"slant":0.75,"none":0.0}.get(rtype, 0.0)
        if q > best_q: best_q, best = q, cp
    return best

def _keys_for_word(word: str):
    prons = _get_pron_all(word)
    if not prons: return None
    best = max(prons, key=lambda p: len(_norm_tail(p)))
    return tuple(key_k1(best)), tuple(key_k2(best)), tuple(best)

# legacy helper used by app’s patterns fallback
def _get_pron(word: str) -> list[str]:
    pr = _get_pron_all(word)
    return pr[0] if pr else []

# ---------- candidate pools ----------
def _candidates_by_key(key_col: str, key: Tuple[str,...], limit: int=500) -> List[Dict]:
    key_json = json.dumps(list(key))
    rows = _db().execute(
        f"SELECT word, pron, syls FROM words WHERE {key_col}=? LIMIT ?",
        (key_json, limit)
    ).fetchall()
    out = []
    for r in rows:
        try:
            out.append({"word": r["word"], "pron": json.loads(r["pron"]), "syls": r["syls"]})
        except Exception:
            out.append({"word": r["word"], "pron": [], "syls": r["syls"]})
    return out

def _q(sql: str, args: tuple, limit: int) -> list[sqlite3.Row]:
    return _db().execute(sql + " LIMIT ?", (*args, limit)).fetchall()

def _candidates_by_tail_family(src_pron: List[str], limit_each: int = 400) -> List[Dict]:
    tail, vowel, coda = _tail_parts(src_pron)
    if not tail: return []
    rime = json.dumps(list(_norm_tail(src_pron)))
    coda_json = json.dumps(list(coda))
    rows = []
    rows += _q("SELECT word, pron, syls FROM words WHERE rime_key = ?", (rime,), limit_each)
    rows += _q("SELECT word, pron, syls FROM words WHERE coda_key = ? AND vowel_key <> ?",
               (coda_json, vowel), limit_each)
    rows += _q("SELECT word, pron, syls FROM words WHERE vowel_key = ? AND rime_key <> ?",
               (vowel, rime), limit_each)
    out: List[Dict] = []
    for r in rows:
        try:
            out.append({"word": r["word"], "pron": json.loads(r["pron"]), "syls": r["syls"]})
        except Exception:
            out.append({"word": r["word"], "pron": [], "syls": r["syls"]})
    return out

# ---------- search ----------
def search_word(
    word: str,
    rhyme_type: str="any",
    slant_strength: float=0.5,  # reserved; currently used via edit-distance threshold
    syllable_min: int=1,
    syllable_max: int=8,
    max_results: int=150,
    weight_quality: float=0.6,
    weight_rarity: float=0.4,
    include_pron: bool=False,
) -> List[Dict]:
    w = _clean(word)
    info = _keys_for_word(w)
    if not info: return []
    k1, k2, src_pron = info

    # Prefer tail-family pools for targeted recall
    pool = _candidates_by_tail_family(list(src_pron), limit_each=400)
    if len(pool) < 200:   # fallback to legacy keys if sparse
        pool += _candidates_by_key("k1", k1, 800)
        pool += _candidates_by_key("k2", k2, 800)

    seen, filtered = set(), []
    for c in pool:
        w_cand = c["word"]
        if w_cand == w: continue
        if not (syllable_min <= c["syls"] <= syllable_max): continue
        if not VALID_WORD_RE.match(w_cand): continue
        if w_cand in seen: continue
        seen.add(w_cand)
        filtered.append(c)

    results: List[Dict] = []
    for c in filtered:
        cand_word = c["word"]
        cand_pron = c["pron"] or _g2p_fallback(cand_word) or []
        best_cand_pron = _best_match_pron(list(src_pron), [cand_pron] or [])
        if not best_cand_pron: continue

        rtype = classify_rhyme(list(src_pron), best_cand_pron)
        if rhyme_type != "any" and rtype != rhyme_type: continue

        tail_multi = tail_syllables(best_cand_pron) >= 2
        orth_multi = is_multiword(cand_word)

        rhyme_q_map = {"perfect":1.0, "assonant":0.85, "consonant":0.9, "slant":0.75, "none":0.0}
        rhyme_q = rhyme_q_map.get(rtype, 0.0)
        if tail_multi: rhyme_q = min(rhyme_q + 0.05, 1.1)

        rar = _rarity_score(cand_word)
        score = weight_quality * rhyme_q + weight_rarity * rar

        results.append({
            "word": cand_word,
            "pron": best_cand_pron if include_pron else None,
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
    if not parts: return []
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
