from __future__ import annotations
import re
from typing import List

STRESS_RE = re.compile(r"(\d)")
VOWEL_RE = re.compile(r"^(AA|AE|AH|AO|AW|AY|EH|ER|EY|IH|IY|OW|OY|UH|UW)\d?$")

def syllable_count(pron: List[str]) -> int:
    return sum(1 for p in pron if VOWEL_RE.match(p))

def stress_digits(pron: List[str]) -> List[int]:
    digs = []
    for p in pron:
        m = STRESS_RE.search(p)
        if m:
            digs.append(int(m.group(1)))
    return digs

def stress_pattern_str(pron: List[str]) -> str:
    digs = stress_digits(pron)
    if not digs:
        return ""
    # normalize 2→1 so pattern is binary
    return "-".join("1" if d > 0 else "0" for d in digs)

def metrical_name(pattern: str) -> str:
    mapping = {
        "1-0": "Trochee",
        "0-1": "Iamb",
        "1-0-0": "Dactyl",
        "0-0-1": "Anapest",
        "1-1": "Spondee",
        "0-1-0": "Amphibrach",
        "1-0-1": "Cretic",
        "0-1-1": "Bacchius",
        "1-1-0": "Antibacchius",
    }
    return mapping.get(pattern, "—")
