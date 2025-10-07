# -*- coding: utf-8 -*-
"""
UncommonRhymesV2 — Rap patterns lookup
======================================

Schema-flexible reader for the (optional) rap patterns database. It:

- Detects column names dynamically (PRAGMA table_info) so we don't
  hard-fail across different dumps.
- Narrows with rime/vowel/coda keys **when available**.
- Validates that either the source or the target actually rhymes with
  the user's query (using the same rhyme classifier as search.py).
- Produces a short highlighted lyric context even if the DB doesn't
  store lyric_context (computed on the fly).
- De-duplicates and caps deterministically.

Exports
-------
- find_patterns_by_keys(query: str, limit: int = 20, db_path: Path | None = None)
- find_patterns_by_keys_enriched(query: str, limit: int = 20, db_path: Path | None = None)
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

# Reuse internals from search core
from .search import classify_rhyme, phrase_to_pron, syllable_count  # type: ignore
from .search import _get_pron  # type: ignore  # internal but stable

DATA_DIR = Path("data")
DEFAULT_DB = DATA_DIR / "patterns_small.db"
WORDS_DB = DATA_DIR / "words_index.sqlite"  # to derive keys from the query token

# -------- column name candidates across dumps --------
SRC_CANDIDATES = ["source_word", "source", "src"]
TGT_CANDIDATES = ["target_word", "target", "tgt"]
LYR_CANDIDATES = ["lyric", "line", "text"]
ARTIST_CANDIDATES = ["artist", "rapper", "author"]
SONG_CANDIDATES = ["song", "title", "track"]
URL_CANDIDATES = ["source_url", "url", "link"]
TABLE_CANDIDATES = ["patterns", "rap_patterns", "pairs"]  # prefer "patterns"

KEY_COLS = ["rime_key", "vowel_key", "coda_key"]

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")

# -----------------------------------------------------------------------------
# SQLite helpers
# -----------------------------------------------------------------------------

def _open_patterns(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else DEFAULT_DB
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    return con

def _open_words() -> sqlite3.Connection:
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    return con

def _table_name(con: sqlite3.Connection) -> str:
    # Prefer "patterns" if present
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    for t in TABLE_CANDIDATES:
        if t in names:
            return t
    # fallback to the first table
    return next(iter(names)) if names else "patterns"

def _columns(con: sqlite3.Connection, table: str) -> Dict[str, int]:
    cols: Dict[str, int] = {}
    for row in con.execute(f"PRAGMA table_info({table})").fetchall():
        cols[row[1]] = row[0]
    return cols

def _first_present(cols: Dict[str, int], candidates: List[str], default: Optional[str] = None) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return default

# -----------------------------------------------------------------------------
# Context + highlighting
# -----------------------------------------------------------------------------

def _highlight(snippet: str, tokens: List[str]) -> str:
    if not snippet:
        return snippet
    out = snippet
    for t in sorted(set(t for t in tokens if t), key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(t)}\b", lambda m: f"[{m.group(0)}]", out, flags=re.IGNORECASE)
    return out

def _context_from_lyric(lyric: str, src: str, tgt: str, radius: int = 90) -> str:
    text = (lyric or "").strip()
    if not text:
        return ""
    tokens = [w for w in [src, tgt] if w]
    # find earliest of src/tgt
    pos = None
    for t in tokens:
        m = re.search(rf"\b{re.escape(t)}\b", text, flags=re.IGNORECASE)
        if m:
            pos = m.start() if pos is None else min(pos, m.start())
    if pos is None:
        # Just center on the middle to avoid empty
        mid = max(0, len(text) // 2)
        snippet = text[max(0, mid - radius): min(len(text), mid + radius)]
    else:
        snippet = text[max(0, pos - radius): min(len(text), pos + radius)]
    return _highlight(snippet, tokens)

# -----------------------------------------------------------------------------
# Query keys from words index
# -----------------------------------------------------------------------------

def _keys_for_last_token(query: str) -> Tuple[str, str, str]:
    tokens = [m.group(0).lower() for m in _WORD_RE.finditer(query.lower())]
    if not tokens:
        return "", "", ""
    last = tokens[-1]
    con = _open_words()
    try:
        r = con.execute("SELECT rime_key, vowel_key, coda_key FROM words WHERE word=?", (last,)).fetchone()
        if not r:
            return "", "", ""
        return r["rime_key"] or "", r["vowel_key"] or "", r["coda_key"] or ""
    finally:
        con.close()

# -----------------------------------------------------------------------------
# Main API
# -----------------------------------------------------------------------------

def find_patterns_by_keys(query: str,
                          limit: int = 20,
                          db_path: Optional[Path] = None,
                          syllable_min: int = 1,
                          syllable_max: int = 16,
                          include_consonant: bool = False) -> List[Dict[str, object]]:
    """Return rap pattern rows where either the source or target rhymes with the query.

    Narrowing strategy:
    - If the table has rime_key/vowel_key/coda_key, we fetch using OR on those keys,
      but the keys come from the *query*'s last token (via words_index).
    - Otherwise we fallback to a simple LIKE on the lyric column to keep results non-empty.

    We always post-filter by rhyme validity using the same classifier as the main search.
    """
    con = _open_patterns(db_path)
    try:
        table = _table_name(con)
        cols = _columns(con, table)

        src_col = _first_present(cols, SRC_CANDIDATES, "source_word") or "source_word"
        tgt_col = _first_present(cols, TGT_CANDIDATES, "target_word") or "target_word"
        lyr_col = _first_present(cols, LYR_CANDIDATES, "lyric") or "lyric"
        art_col = _first_present(cols, ARTIST_CANDIDATES, None)
        song_col = _first_present(cols, SONG_CANDIDATES, None)
        url_col  = _first_present(cols, URL_CANDIDATES, None)
        ctx_col = "lyric_context" if "lyric_context" in cols else None

        qv, qvv, qc = _keys_for_last_token(query)
        has_keys = all(k in cols for k in KEY_COLS)

        # Build SQL
        fields = [f"{src_col} AS src", f"{tgt_col} AS tgt", f"{lyr_col} AS lyric"]
        if art_col: fields.append(f"{art_col} AS artist")
        if song_col: fields.append(f"{song_col} AS song")
        if url_col: fields.append(f"{url_col} AS url")
        if ctx_col: fields.append("lyric_context AS lyric_context")
        sql = f"SELECT {', '.join(fields)} FROM {table}"
        args: List[object] = []

        if has_keys and (qv or qvv or qc):
            conds = []
            if qv:  conds.append("rime_key=?");   args.append(qv)
            if qvv: conds.append("vowel_key=?");  args.append(qvv)
            if qc:  conds.append("coda_key=?");   args.append(qc)
            if conds:
                sql += " WHERE " + " OR ".join(conds)
        else:
            # fallback LIKE; match lyric contains any query token
            qtokens = [m.group(0) for m in _WORD_RE.finditer(query)]
            if qtokens:
                like_cond = "(" + " OR ".join([f"{lyr_col} LIKE ?"] * len(qtokens)) + ")"
                sql += f" WHERE {like_cond}"
                args.extend([f"%{t}%" for t in qtokens])

        # pull a widened pool to allow post filtering
        sql += " LIMIT ?"
        args.append(max(300, limit * 12))

        rows = con.execute(sql, args).fetchall()

        # Prepare query pronunciation once
        qpron = _get_pron(query) or phrase_to_pron(query)

        out: List[Dict[str, object]] = []
        for r in rows:
            src = (r["src"] or "").strip()
            tgt = (r["tgt"] or "").strip()
            lyric = (r["lyric"] or "").strip()

            spron = _get_pron(src) or []
            tpron = _get_pron(tgt) or []

            r_src = classify_rhyme(qpron, spron)
            r_tgt = classify_rhyme(qpron, tpron)

            # Decide acceptance: either side must rhyme; consonants are optional
            ok_src = r_src in ("perfect", "assonant", "slant") or (include_consonant and r_src == "consonant")
            ok_tgt = r_tgt in ("perfect", "assonant", "slant") or (include_consonant and r_tgt == "consonant")
            if not (ok_src or ok_tgt):
                continue

            # Optional syllable bounds (only filter the side that rhymes)
            if ok_src:
                ss = syllable_count(spron)
                if ss and (ss < syllable_min or ss > syllable_max):
                    ok_src = False
            if ok_tgt:
                ts = syllable_count(tpron)
                if ts and (ts < syllable_min or ts > syllable_max):
                    ok_tgt = False
            if not (ok_src or ok_tgt):
                continue

            # Build context
            context = r["lyric_context"].strip() if (ctx_col and r["lyric_context"]) else _context_from_lyric(lyric, src, tgt)

            item: Dict[str, object] = {
                "source": src,
                "target": tgt,
                "context": context,
            }
            if art_col: item["artist"] = r["artist"]
            if song_col: item["song"] = r["song"]
            if url_col:  item["url"] = r["url"]

            # Primary type for display preference
            if ok_src and r_src != "none":
                item["type"] = r_src
            elif ok_tgt:
                item["type"] = r_tgt
            else:
                item["type"] = "slant"

            out.append(item)

        # De-dup: (source, target, song) triple
        seen = set()
        uniq: List[Dict[str, object]] = []
        for it in out:
            key = (it.get("source",""), it.get("target",""), it.get("song",""))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(it)

        # Sort: prefer perfect/assonant, then title/artist alpha for determinism
        order = {"perfect": 0, "assonant": 1, "slant": 2, "consonant": 3}
        uniq.sort(key=lambda x: (order.get(str(x.get("type","slant")), 9),
                                 str(x.get("song","")).lower(),
                                 str(x.get("artist","")).lower(),
                                 str(x.get("source","")).lower(),
                                 str(x.get("target","")).lower()))
        return uniq[:limit]

    finally:
        con.close()

def find_patterns_by_keys_enriched(query: str,
                                   limit: int = 20,
                                   db_path: Optional[Path] = None) -> List[Dict[str, object]]:
    """Currently same as basic; kept for API parity if we attach more fields later."""
    return find_patterns_by_keys(query=query, limit=limit, db_path=db_path)
