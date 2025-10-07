from __future__ import annotations
from typing import List

from config import FLAGS

from .loader import get_llm


def mine_multiword_variants(target_word: str) -> List[str]:
    if not FLAGS.get("USE_LLM"):
        return []
    llm = get_llm()
    if llm is None:
        return []
    prompt = (
        "Propose 15 concise multi-word variants ending with the same rime as '"
        + target_word
        + "' (e.g., 'on the TABLE' for TABLE). One per line."
    )
    return llm.complete_lines(prompt, n=15)
