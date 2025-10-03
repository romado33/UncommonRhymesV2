# rhyme_core/patterns.py
from __future__ import annotations
import os, sqlite3, json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from rhyme_core.search import _clean, _keys_for_word  # reuse helpers

DB_CANDIDATES = [Path("data/patterns_small.db"), Path("data/patterns.db")]

def _open() -> Optional[sqlite3.Connection]:
    for p in DB_CANDIDATES:
        if p.exists():
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return con
    return None

def _list_tables(cur) -> list[str]:
    return [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]

def _has_cols(cur, table: str, needed: Tuple[str, ...]) -> bool:
    cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    return all(c in cols for c in needed)

def _resolve_table(cur) -> str:
    # 1) explicit env override
    t = os.environ.get("PATTERNS_TABLE")
    if t and _has_cols(cur, t, ("last_word_rime_key","last_two_syllables_key")):
        return t
    # 2) prefer 'patterns'
    if "patterns" in _list_tables(cur) and _has_cols(cur, "patterns",
        ("last_word_rime_key","last_two_syllables_key")):
        return "patterns"
    # 3) otherwise, pick any table that has the key columns
    for tab in _list_tables(cur):
        if _has_cols(cur, tab, ("last_word_rime_key","last_two_syllables_key")):
            return tab
    # fallback
    return "patterns"

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
        d["_table"] = table
        d["_preview"] = (d.get("pattern") or d.get("target_context") or d.get("source_context") or "")[:200]
        out.append(d)

    con.close()
    return out
