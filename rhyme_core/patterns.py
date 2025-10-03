from __future__ import annotations
import sqlite3, json
from pathlib import Path
from typing import List, Dict, Optional
from .search import _clean, _keys_for_word

DB_CANDIDATES = [Path("data/patterns_small.db"), Path("data/patterns.db")]

def _open() -> Optional[sqlite3.Connection]:
    for p in DB_CANDIDATES:
        if p.exists():
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return con
    return None

def find_patterns_by_keys(phrase: str, limit: int = 50) -> List[Dict]:
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
    try:
        rows = cur.execute(
            "SELECT * FROM song_rhyme_patterns WHERE (last_word_rime_key = ? OR last_two_syllables_key = ?) LIMIT ?",
            (key1, key2, limit)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = dict(r)
        d["_table"] = "song_rhyme_patterns"
        d["_preview"] = (d.get("pattern") or d.get("source_context") or d.get("target_context") or "")[:200]
        out.append(d)
    con.close()
    return out[:limit]
