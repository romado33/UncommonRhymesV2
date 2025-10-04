from __future__ import annotations
from typing import List
from config import FLAGS
from .providers import complete_lines

def generate_phrases(target_word: str, metre_hint: str = "") -> List[str]:
    if not FLAGS.LLM_PHRASE_GEN:
        return []
    prompt = (
        "Write 10 short, punchy phrases that END with a perfect rhyme for '"
        + target_word + "'. If metre hint is given, try to match it. "
        "Each on its own line."
    )
    return complete_lines(prompt, n=10, temperature=0.8)