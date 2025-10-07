from __future__ import annotations
from typing import Dict, List

from config import FLAGS

from .loader import get_llm


def rerank_candidates(query_word: str, query_pron: List[str], rows: List[Dict]) -> List[Dict]:
    if not FLAGS.get("USE_LLM") or len(rows) < 5:
        return rows
    llm = get_llm()
    if llm is None:
        return rows
    try:
        payload = [
            {"word": r.get("word", ""), "rtype": r.get("rhyme_type", ""), "score": float(r.get("score", 0.0))}
            for r in rows[:50]
        ]
        prompt = (
            "You are a rhyme editor. Reorder candidates (do NOT add/remove). "
            "Prefer exact rime, matching stress, idiomatic usage.\n"
            f"QUERY={query_word}; CANDS={payload}"
        )
        js = llm.complete_json(prompt, schema_hint="{'order':[int,...]}")
        order = js.get("order") if isinstance(js, dict) else None
        if not isinstance(order, list) or not order:
            return rows
        idxs = [i for i in order if isinstance(i, int) and 0 <= i < len(payload)]
        missing = [i for i in range(len(payload)) if i not in idxs]
        return [rows[i] for i in (idxs + missing)] + rows[len(payload):]
    except Exception:
        return rows
