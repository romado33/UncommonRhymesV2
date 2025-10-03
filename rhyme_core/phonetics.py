from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple
import re

VOWEL_RE = re.compile(r"[AEIOU]")        # ARPABET vowel marker in stress symbols
STRESS_RE = re.compile(r"\d")           # captures 0/1/2
SYLLABLE_VOWELS = {"AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"}

def parse_cmu_line(line: str) -> tuple[str, List[str]] | None:
    line=line.strip()
    if not line or line.startswith(";;;"):
        return None
    # WORD  PHONEMES...
    head, *phones = line.split()
    word = head.split("(")[0].lower()
    return word, phones

def syllable_count(phones: List[str]) -> int:
    return sum(1 for p in phones if any(v in p for v in SYLLABLE_VOWELS))

def stressed_vowel_positions(phones: List[str]) -> List[int]:
    return [i for i,p in enumerate(phones) if STRESS_RE.search(p)]

def last_stressed_vowel_idx(phones: List[str]) -> int | None:
    idxs = stressed_vowel_positions(phones)
    return idxs[-1] if idxs else None

def rime_from(phones: List[str], start_idx: int) -> Tuple[str,...]:
    return tuple(phones[start_idx:]) if 0 <= start_idx < len(phones) else tuple(phones)

def key_k1(phones: List[str]) -> Tuple[str,...]:
    """Last stressed vowel → end (standard rime key)."""
    i = last_stressed_vowel_idx(phones)
    return rime_from(phones, i if i is not None else 0)

def key_k2(phones: List[str]) -> Tuple[str,...]:
    """Two-syllable compound rime key. Fallback to K1 if only one syllable."""
    syll_ix = [i for i,p in enumerate(phones) if any(v in p for v in SYLLABLE_VOWELS)]
    if len(syll_ix) < 2:
        return key_k1(phones)
    penult = syll_ix[-2]
    return tuple(phones[penult:])
