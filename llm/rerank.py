from __future__ import annotations
from typing import List, Dict
from config import FLAGS
from .providers import complete_json
import json

def rerank_candidates(query_word: str, query_pron: list, rows: List[Dict]) -> List[Dict]:
    if not FLAGS.LLM_RERANK or len(rows) < 5:
        return rows
    payload = [
        {"word": r["word"], "rtype": r.get("rhyme_type",""), "score": float(r.get("score",0.0))}
        for r in rows[:50]
    ]
    prompt = (
        "You are a rhyme editor. Reorder candidates (do NOT add/remove). "
        "Prefer exact rime, matching stress, idiomatic usage.\n"
        f"QUERY={query_word}; CANDS={json.dumps(payload)}\n"
        "Return JSON: {'order':[indices]}"
    )
    js = complete_json(prompt, schema_hint="{'order':[int,...]}", temperature=0.2)
    order = js.get("order") if isinstance(js, dict) else None
    if not isinstance(order, list) or not order:
        return rows
    idxs = [i for i in order if isinstance(i,int) and 0 <= i < len(payload)]
    missing = [i for i in range(len(payload)) if i not in idxs]
    try:
        return [rows[i] for i in (idxs + missing)] + rows[len(payload):]
    except Exception:
        return rows