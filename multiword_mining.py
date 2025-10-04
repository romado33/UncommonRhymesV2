from __future__ import annotations
from typing import List
from config import FLAGS
from .providers import complete_lines

def mine_multiword_variants(target_word: str) -> List[str]:
    if not FLAGS.LLM_MULTIWORD_MINE:
        return []
    prompt = (
        "Propose 15 concise multi-word variants ending with the same rime as '"
        + target_word + "' (e.g., 'on the TABLE' for TABLE). One per line."
    )
    return complete_lines(prompt, n=15, temperature=0.7)