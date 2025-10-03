from __future__ import annotations
import sqlite3, json
from pathlib import Path
from typing import List, Dict, Optional
from rhyme_core.search import _clean, _keys_for_word, _get_pron
from rhyme_core.prosody import syllable_count, stress_pattern_str, metrical_name

DB_CANDIDATES = [Path("data/patterns_small.db"), Path("data/patterns.db")]

def _open() -> Optional[sqlite3.Connection]:
    for p in DB_CANDIDATES:
        if p.exists():
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return con
    return None

def _resolve_table(cur) -> str:
    tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "patterns" in tabs:
        return "patterns"
    for t in tabs:
        cols = {r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()}
        if "last_word_rime_key" in cols and "last_two_syllables_key" in cols:
            return t
    return "patterns"

def find_patterns_by_keys_enriched(phrase: str, limit: int = 50) -> List[Dict]:
    tokens = _clean(phrase).split()
    if not tokens:
        return []
    info = _keys_for_word(tokens[-1])
    if not info:
        return []
    k1, k2, _ = info
    key1 = json.dumps(list(k1)); key2 = json.dumps(list(k2))

    con = _open()
    if not con:
        return []
    cur = con.cursor()
    table = _resolve_table(cur)

    try:
        rows = cur.execute(
            f"SELECT * FROM {table} WHERE (last_word_rime_key = ? OR last_two_syllables_key = ?) LIMIT ?",
            (key1, key2, int(limit))
        ).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return []

    out = []
    for r in rows:
        d = dict(r)
        target = (d.get("target_word") or d.get("source_word") or "").strip().lower()
        pron = _get_pron(target) or []
        syls = syllable_count(pron)
        stress = stress_pattern_str(pron)
        meter = metrical_name(stress) if stress else "—"
        ctx_src = (d.get("source_context") or "").strip()
        ctx_tgt = (d.get("target_context") or "").strip()
        lyric_context = ctx_src
        if ctx_tgt:
            lyric_context = f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt

        out.append({
            "id": d.get("id"),
            "artist": d.get("artist",""),
            "song_title": d.get("song_title",""),
            "target_rhyme": target,
            "syllables": syls,
            "stress": stress,
            "meter": meter,
            "lyric_context": lyric_context[:300],
        })

    con.close()
    return out
