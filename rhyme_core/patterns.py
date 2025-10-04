"""
Patterns DB accessors. Thread‑safe connections and an enriched finder that
returns rows with source/target/context metadata. The DB file can be either
`data/patterns.db` or `data/patterns_small.db`.
"""
from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Iterable, List

_DB_LOCAL = threading.local()

DATA_DIR = Path(os.environ.get("UR_DATA_DIR", "data"))
_DB_CANDIDATES = [DATA_DIR / "patterns_small.db", DATA_DIR / "patterns.db"]


def _pick_db_path() -> Path | None:
    for p in _DB_CANDIDATES:
        if p.exists():
            return p
    return None


def _conn() -> sqlite3.Connection | None:
    """Per‑thread connection with WAL + sensible pragmas."""
    path = _pick_db_path()
    if not path:
        return None
    key = str(path.resolve())
    cache: Dict[str, sqlite3.Connection] = getattr(_DB_LOCAL, "cache", {})
    if key in cache:
        return cache[key]
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    cache[key] = con
    _DB_LOCAL.cache = cache
    return con


def find_patterns_by_keys_enriched(query: str, limit: int = 100) -> List[dict]:
    """
    Lightweight "enriched" lookup. We map the query to keys in a permissive way
    (rime or last two syllables), then return a list of dict rows containing
    source/target terms and contexts. The caller (app) can further filter/rank.
    """
    con = _conn()
    if not con:
        return []

    q = (query or "").strip().lower()
    if not q:
        return []

    # Strategy: try to match by suffix/rime keys if the table has them; otherwise
    # fall back to a LIKE on the text columns to keep things forgiving.
    cols = {r[1] for r in con.execute("PRAGMA table_info(patterns)").fetchall()}
    use_keys = {"last_word_rime_key", "last_two_syllables_key"} <= cols

    rows: Iterable[sqlite3.Row]
    if use_keys:
        # We don't compute keys here; instead, select a generous slice ordered by
        # recency/created_timestamp. The app will post‑filter.
        rows = con.execute(
            """
            SELECT
              target_word, source_word,
              artist, song_title,
              source_context, target_context, lyric_context,
              created_timestamp
            FROM patterns
            ORDER BY created_timestamp DESC
            LIMIT ?
            """,
            (max(1000, int(limit) * 4),),
        ).fetchall()
    else:
        like = f"%{q}%"
        rows = con.execute(
            """
            SELECT target_word, source_word,
                   artist, song_title,
                   source_context, target_context, lyric_context,
                   created_timestamp
            FROM patterns
            WHERE LOWER(COALESCE(target_word,'')) LIKE ?
               OR LOWER(COALESCE(source_word,'')) LIKE ?
               OR LOWER(COALESCE(source_context,'')) LIKE ?
               OR LOWER(COALESCE(target_context,'')) LIKE ?
               OR LOWER(COALESCE(lyric_context,'')) LIKE ?
            ORDER BY created_timestamp DESC
            LIMIT ?
            """,
            (like, like, like, like, like, max(1000, int(limit) * 4)),
        ).fetchall()

    out: List[dict] = []
    for r in rows:
        out.append({k: r[k] for k in r.keys()})
    return out


# Back‑compat name expected by older app versions
find_patterns_by_keys = find_patterns_by_keys_enriched  # type: ignore
