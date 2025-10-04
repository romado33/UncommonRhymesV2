from __future__ import annotations
from typing import List
from config import FLAGS
from .providers import complete_json

def infer_pron_arpabet(word: str) -> List[str] | None:
    if not FLAGS.LLM_OOV_G2P:
        return None
    js = complete_json(
        "Provide ARPABET phoneme list for the English word '"
        + word
        + "'. Only CMU symbols with stress (e.g., AH0, EY1). "
          "Return JSON: {'arpabet':['...']}",
        schema_hint="{'arpabet':[str,...]}",
        temperature=0.1,
    )
    ph = js.get("arpabet") if isinstance(js, dict) else None
    if isinstance(ph, list) and ph and any(isinstance(p,str) and p.endswith(tuple('012')) for p in ph):
        return [str(p) for p in ph]
    return None
