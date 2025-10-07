from __future__ import annotations
from typing import List

from config import FLAGS

from .loader import get_llm


def generate_phrases(target_word: str, metre_hint: str = "") -> List[str]:
    if not FLAGS.get("USE_LLM"):
        return []
    llm = get_llm()
    if llm is None:
        return []
    prompt = (
        "Write 10 short, punchy phrases that END with a perfect rhyme for '"
        + target_word
        + "'. If metre hint is given, try to match it. Each on its own line."
    )
    return llm.complete_lines(prompt, n=10)
