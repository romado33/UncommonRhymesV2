from __future__ import annotations
import re
from typing import Tuple

VOWELS = {
    "AA","AE","AH","AO","AW","AY","EH","ER","EY","IH","IY","OW","OY","UH","UW"
}

def is_vowel(phone: str) -> bool:
    base = re.sub(r"\d", "", phone)
    return base in VOWELS

def only_vowels(phones: Tuple[str,...]) -> Tuple[str,...]:
    return tuple(re.sub(r"\d", "", p) for p in phones if is_vowel(p))

def only_cons(phones: Tuple[str,...]) -> Tuple[str,...]:
    return tuple(re.sub(r"\d", "", p) for p in phones if not is_vowel(p))

def syllables(phones: Tuple[str,...]) -> int:
    return sum(1 for p in phones if is_vowel(p))

def classify(src_tail: Tuple[str,...], cand_tail: Tuple[str,...]) -> str:
    if cand_tail == src_tail:
        return "perfect"
    if only_vowels(cand_tail) == only_vowels(src_tail):
        return "assonant"
    if only_cons(cand_tail) == only_cons(src_tail):
        return "consonant"
    return "slant"
