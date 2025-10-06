"""Built-in deterministic fallback pronunciations used when the DB is unavailable."""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

from .normalize import normalize_text

# Minimal pronunciation dictionary covering smoke tests and unit tests.
# Phones are taken from CMUdict and simplified (stress digits retained).
_FALLBACK_PRONS: Dict[str, Tuple[str, ...]] = {
    "hat": ("HH", "AE1", "T"),
    "cat": ("K", "AE1", "T"),
    "bat": ("B", "AE1", "T"),
    "mat": ("M", "AE1", "T"),
    "gnat": ("N", "AE1", "T"),
    "flat": ("F", "L", "AE1", "T"),
    "double": ("D", "AH1", "B", "AH0", "L"),
    "bubble": ("B", "AH1", "B", "AH0", "L"),
    "trouble": ("T", "R", "AH1", "B", "AH0", "L"),
    "stubble": ("S", "T", "AH1", "B", "AH0", "L"),
    "rubble": ("R", "AH1", "B", "AH0", "L"),
    "hubble": ("HH", "AH1", "B", "AH0", "L"),
    "puddle": ("P", "AH1", "D", "AH0", "L"),
    "shuffle": ("SH", "AH1", "F", "AH0", "L"),
    "couple": ("K", "AH1", "P", "AH0", "L"),
    "downside": ("D", "AW1", "N", "S", "AY2", "D"),
    "hillside": ("HH", "IH1", "L", "S", "AY2", "D"),
    "blindside": ("B", "L", "AY1", "N", "D", "S", "AY2", "D"),
    "inside": ("IH2", "N", "S", "AY1", "D"),
    "outside": ("AW2", "T", "S", "AY1", "D"),
    "fireside": ("F", "AY1", "ER0", "S", "AY2", "D"),
    "time": ("T", "AY1", "M"),
    "rhyme": ("R", "AY1", "M"),
    "climb": ("K", "L", "AY1", "M"),
    "thyme": ("TH", "AY1", "M"),
}

FALLBACK_WORDS = tuple(sorted(_FALLBACK_PRONS.keys()))


def has_fallback(word: str) -> bool:
    return normalize_text(word) in _FALLBACK_PRONS


def get_fallback_pron(word: str) -> Optional[Tuple[str, ...]]:
    return _FALLBACK_PRONS.get(normalize_text(word))


def iter_fallback_items(exclude: Iterable[str] = ()):
    excluded = {normalize_text(e) for e in exclude}
    for word, pron in _FALLBACK_PRONS.items():
        if word in excluded:
            continue
        yield word, pron

__all__ = ["FALLBACK_WORDS", "has_fallback", "get_fallback_pron", "iter_fallback_items"]
