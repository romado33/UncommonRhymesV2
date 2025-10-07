"""Normalization helpers for rhyme queries."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List

_SMART_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
}

_DASHES = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
}

_WHITESPACE_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[-]+")
_WORD_CLEAN_RE = re.compile(r"[^a-z0-9\-\s']+")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    if not text:
        return ""
    fixed = text
    for src, dst in _SMART_QUOTES.items():
        fixed = fixed.replace(src, dst)
    for src, dst in _DASHES.items():
        fixed = fixed.replace(src, dst)
    fixed = _strip_accents(fixed)
    fixed = fixed.lower()
    fixed = _DASH_RE.sub(" ", fixed)
    fixed = _WHITESPACE_RE.sub(" ", fixed)
    return fixed.strip()


def normalize_texts(items: Iterable[str]) -> List[str]:
    return [normalize_text(item) for item in items]


def normalize_word(text: str) -> str:
    """Normalize text for dictionary lookups by stripping punctuation and spaces."""
    normalized = normalize_text(text)
    if not normalized:
        return ""
    cleaned = _WORD_CLEAN_RE.sub("", normalized)
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace(" ", "")
    return cleaned.strip()

__all__ = ["normalize_text", "normalize_texts", "normalize_word"]
