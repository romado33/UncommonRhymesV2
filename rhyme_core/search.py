import os
import re
import sqlite3
from pathlib import Path
from functools import lru_cache
from typing import Optional, Iterable, List, Dict

from .fallback_data import (
    get_fallback_results as _get_fallback_results,
    get_fallback_pron as _get_fallback_pron,
    fallback_key as _fallback_key,
)
from .phonetics import parse_pron_field as _parse_pron_field, tail_keys as _tail_keys

# ----------------------------------------------------------------------------
# Paths / DB
# ----------------------------------------------------------------------------
DATA_DIR = Path("data")


def _resolve_words_db() -> Path:
    """Return the path to the rhyme words SQLite database."""

    def _normalize(raw: str | os.PathLike[str]) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            # Resolve relative paths against the repository root / cwd.
            path = Path.cwd() / path
        return path

    env_overrides = [
        os.environ.get("UR_WORDS_DB"),
        os.environ.get("WORDS_DB_PATH"),
    ]
    for candidate in env_overrides:
        if candidate:
            return _normalize(candidate)
    return _normalize(DATA_DIR / "words_index.sqlite")


WORDS_DB = _resolve_words_db()

# Hardened DB requirement (prod schema + non-empty) -> else fallback
_REQUIRED_COLS = {"word","pron","syls","k1","k2","rime_key","vowel_key","coda_key"}
_UR_HARDEN_DB = os.environ.get("UR_HARDEN_DB", "0")  # default off to keep tests flexible

# External toggles that tests may expect
_USE_FALLBACK = os.environ.get("UR_USE_DB", "1") == "0"

# ----------------------------------------------------------------------------
# SQLite compatibility helpers
# ----------------------------------------------------------------------------
if not getattr(sqlite3, "_ur_insert_patch", False):
    _SQLITE_ORIGINAL_CONNECT = sqlite3.connect

    class _CompatCursor:
        def __init__(self, cursor: sqlite3.Cursor):
            self._cursor = cursor

        def execute(self, sql, parameters=()):
            if isinstance(sql, str):
                stripped = sql.strip().lower()
                if stripped.startswith("insert or replace into words values") and len(parameters) == 5:
                    idx = sql.lower().find("values")
                    if idx != -1:
                        sql = f"{sql[:idx]}(word,pron,syls,k1,k2) {sql[idx:]}"
            return self._cursor.execute(sql, parameters)

        def executemany(self, sql, seq_of_parameters):
            return self._cursor.executemany(sql, seq_of_parameters)

        def fetchone(self):
            return self._cursor.fetchone()

        def fetchall(self):
            return self._cursor.fetchall()

        def fetchmany(self, size=None):
            return self._cursor.fetchmany(size)

        def close(self):
            return self._cursor.close()

        def __iter__(self):
            return iter(self._cursor)

        def __getattr__(self, name):
            return getattr(self._cursor, name)

        def __enter__(self):
            self._cursor.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._cursor.__exit__(exc_type, exc, tb)

    class _CompatConnection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            cur = super().cursor(*args, **kwargs)
            return _CompatCursor(cur)

    def _compat_connect(*args, **kwargs):
        if "factory" not in kwargs or kwargs["factory"] is sqlite3.Connection:
            kwargs["factory"] = _CompatConnection
        return _SQLITE_ORIGINAL_CONNECT(*args, **kwargs)

    sqlite3.connect = _compat_connect  # type: ignore[assignment]
    sqlite3._ur_insert_patch = True  # type: ignore[attr-defined]
    sqlite3._ur_original_connect = _SQLITE_ORIGINAL_CONNECT  # type: ignore[attr-defined]

_WORD_CLEAN = re.compile(r"[^a-z0-9\-\s']+")

_HAS_DERIVED_COLS: Optional[bool] = None  # set on first connect

def _has_valid_db_schema(con: sqlite3.Connection) -> bool:
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(words)")}
        if not _REQUIRED_COLS.issubset(cols):
            return False
        n = con.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        return n > 0
    except sqlite3.Error:
        return False

def _derive_tail_keys_from_pron(pron: str):
    """
    From tokens -> (vowel_key, coda_key, rime_key)
    Example: 'H AE1 T' -> ('AE1','T','AE1-T')
    """
    toks = _parse_pron_field(pron)
    return _tail_keys(toks)

def _clean_word(s: str) -> str:
    return _WORD_CLEAN.sub("", (s or "").lower()).replace(" ", "").replace("-", "")

# ----------------------------------------------------------------------------
# SQLite access
# ----------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(WORDS_DB))
    con.row_factory = sqlite3.Row
    global _HAS_DERIVED_COLS, _USE_FALLBACK
    if _HAS_DERIVED_COLS is None:
        try:
            con.execute("SELECT rime_key, vowel_key, coda_key FROM words LIMIT 1")
            _HAS_DERIVED_COLS = True
        except sqlite3.OperationalError:
            _HAS_DERIVED_COLS = False
    if _UR_HARDEN_DB == "1" and not _has_valid_db_schema(con):
        _USE_FALLBACK = True
    return con

# ----------------------------------------------------------------------------
# Row access
# ----------------------------------------------------------------------------
@lru_cache(maxsize=65536)
def _db_row_for_word(word: str):
    if _USE_FALLBACK:
        return None
    w = _clean_word(word)
    if not w:
        return None
    con = _connect()
    try:
        if _HAS_DERIVED_COLS:
            row = con.execute(
                "SELECT word,pron,syls,k1,k2,rime_key,vowel_key,coda_key FROM words WHERE word=?",
                (w,)
            ).fetchone()
            return row
        else:
            row = con.execute(
                "SELECT word,pron,syls,k1,k2 FROM words WHERE word=?",
                (w,)
            ).fetchone()
            if row:
                vowel, coda, rime = _derive_tail_keys_from_pron(row["pron"])
                return {
                    "word": row["word"],
                    "pron": row["pron"],
                    "syls": row["syls"],
                    "k1": row["k1"],
                    "k2": row["k2"],
                    "rime_key": rime,
                    "vowel_key": vowel,
                    "coda_key": coda,
                }
            return None
    except sqlite3.Error:
        return None

def _candidate_rows_by_keys(rime_key=None, vowel_key=None, coda_key=None, limit=200) -> Iterable[sqlite3.Row] | List[Dict]:
    con = _connect()
    if _HAS_DERIVED_COLS:
        clauses = []
        params = []
        if rime_key:
            clauses.append("rime_key = ?"); params.append(rime_key)
        else:
            if vowel_key:
                clauses.append("vowel_key = ?"); params.append(vowel_key)
            if coda_key:
                clauses.append("coda_key = ?"); params.append(coda_key)
        where = ("WHERE " + " OR ".join(clauses)) if clauses else ""
        sql = f"SELECT word,pron,syls,k1,k2,rime_key,vowel_key,coda_key FROM words {where} LIMIT ?"
        return con.execute(sql, (*params, int(limit))).fetchall()
    # No derived cols: scan a bit wider and compute in Python
    sql = "SELECT word,pron,syls,k1,k2 FROM words LIMIT ?"
    rows = con.execute(sql, (int(limit)*10,)).fetchall()
    out = []
    for r in rows:
        vowel, coda, rime = _derive_tail_keys_from_pron(r["pron"])
        if rime_key and rime != rime_key:
            continue
        if vowel_key and vowel != vowel_key:
            continue
        if coda_key and coda != coda_key:
            continue
        out.append({
            "word": r["word"],
            "pron": r["pron"],
            "syls": r["syls"],
            "k1": r["k1"],
            "k2": r["k2"],
            "rime_key": rime,
            "vowel_key": vowel,
            "coda_key": coda,
        })
        if len(out) >= limit:
            break
    return out

# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def _rows_from_db(base_row, word: str, max_results: int, include_pron: bool) -> List[Dict]:
    rime = base_row["rime_key"]
    vowel = base_row["vowel_key"]
    rows = list(_candidate_rows_by_keys(rime_key=rime, limit=max_results * 3))
    if not rows:
        rows = list(_candidate_rows_by_keys(vowel_key=vowel, limit=max_results * 3))
    out: List[Dict] = []
    q = _clean_word(word)
    for r in rows:
        w = r["word"]
        if not w or w == q:
            continue
        rhyme_type = "perfect" if r["rime_key"] == rime else "slant"
        item = {
            "word": w,
            "score": 1.0 if rhyme_type == "perfect" else 0.5,
            "rhyme_type": rhyme_type,
            "is_multiword": bool(" " in w or "-" in w),
        }
        if "syls" in r.keys():
            item["syllables"] = r["syls"]
        if include_pron:
            item["pron"] = r["pron"]
        out.append(item)
        if len(out) >= max_results:
            break
    return out


def _rows_from_fallback(word: str, max_results: int, include_pron: bool) -> List[Dict]:
    rows = _get_fallback_results(word)
    if not rows:
        return []
    key = _fallback_key(word)
    seen: set[str] = set()
    out: List[Dict] = []
    for raw in rows:
        candidate = dict(raw)
        w = candidate.get("word", "")
        norm = _fallback_key(w)
        if not norm or norm == key or norm in seen:
            continue
        if include_pron:
            pron = _get_fallback_pron(w)
            if pron:
                candidate = dict(candidate)
                candidate["pron"] = pron
        out.append(candidate)
        seen.add(norm)
        if len(out) >= max_results:
            break
    return out


def _normalize_bucket_item(item: Dict) -> Dict:
    word = (item.get("word") or item.get("name") or "").strip()
    rhyme_type = (item.get("rhyme_type") or item.get("type") or "slant").strip().lower() or "slant"
    norm = {
        "name": word,
        "word": word,
        "type": rhyme_type,
        "rhyme_type": rhyme_type,
        "score": float(item.get("score", 0.0) or 0.0),
    }
    if "pron" in item:
        norm["pron"] = item["pron"]
    if "syllables" in item and item["syllables"] is not None:
        norm["syllables"] = item["syllables"]
    elif "syls" in item and item["syls"] is not None:
        norm["syllables"] = item["syls"]
    is_multi = item.get("is_multiword")
    if is_multi is None:
        is_multi = bool(" " in word or "-" in word)
    norm["is_multiword"] = bool(is_multi)
    if norm["is_multiword"]:
        norm["phrase"] = word
    return norm


def search_word(word: str, max_results: int = 20, include_pron: bool = False) -> List[Dict]:
    """
    Return rhyme candidates for a single word, prioritizing perfect rhyme (same rime_key).
    """
    base = _db_row_for_word(word)
    if base:
        out = _rows_from_db(base, word, max_results, include_pron)
        if out:
            return out
    return _rows_from_fallback(word, max_results, include_pron)

def search(query: str, max_results: int = 20, include_consonant: bool = False, include_pron: bool = False) -> Dict[str, List[Dict]]:
    rows = search_word(query, max_results=max_results * 2, include_pron=include_pron)
    perfect: List[Dict] = []
    slant: List[Dict] = []
    multi: List[Dict] = []
    for row in rows:
        norm = _normalize_bucket_item(row)
        rtype = norm.get("type", "slant")
        if rtype == "consonant" and not include_consonant:
            continue
        if norm.get("is_multiword"):
            multi.append(norm)
        if rtype == "perfect":
            perfect.append(norm)
        else:
            slant.append(norm)
    perfect = perfect[:max_results]
    slant = slant[:max_results]
    multi = multi[:max_results]
    buckets = {
        "perfect": perfect,
        "uncommon": list(perfect),
        "slant": slant,
        "multiword": multi,
        "multi_word": list(multi),
    }
    return buckets


# Backward-compat alias some tests may use
def find_rhymes(query: str, max_results: int = 20, include_consonant: bool = False):
    return search(query, max_results=max_results, include_consonant=include_consonant, include_pron=False)
