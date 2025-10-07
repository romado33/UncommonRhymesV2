from __future__ import annotations
from typing import Any, Dict

from config import FLAGS

from .loader import get_llm


def parse_query(nl: str) -> Dict[str, Any]:
    if not FLAGS.get("USE_LLM"):
        return {}
    llm = get_llm()
    if llm is None:
        return {}
    js = llm.complete_json(
        "Parse this user request for rhyme search parameters. Keys: "
        "{'rhyme_type': one of [any,perfect,assonant,consonant,slant], "
        "'syl_min': int, 'syl_max': int, 'rarity_min': float [0..1], 'multiword': bool}.\n"
        f"Text: {nl}",
        schema_hint="{'rhyme_type':str,'syl_min':int,'syl_max':int,'rarity_min':float,'multiword':bool}",
        temperature=0.1,
    )
    return js if isinstance(js, dict) else {}
