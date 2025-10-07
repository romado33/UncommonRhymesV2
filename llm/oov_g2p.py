from __future__ import annotations
from typing import List

from config import FLAGS

from .loader import get_llm


def infer_pron_arpabet(word: str) -> List[str] | None:
    if not FLAGS.get("USE_LLM"):
        return None
    llm = get_llm()
    if llm is None:
        return None
    js = llm.complete_json(
        "Provide ARPABET phoneme list for the English word '"
        + word
        + "'. Only CMU symbols with stress (e.g., AH0, EY1). Return JSON: {'arpabet':['...']}",
        schema_hint="{'arpabet':[str,...]}",
        temperature=0.1,
    )
    ph = js.get("arpabet") if isinstance(js, dict) else None
    if isinstance(ph, list) and ph and any(isinstance(p, str) and p.endswith(tuple("012")) for p in ph):
        return [str(p) for p in ph]
    return None
