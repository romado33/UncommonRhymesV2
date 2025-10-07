from __future__ import annotations
from typing import Dict, List

from config import FLAGS

from .loader import get_llm


def pick_best_contexts(query_word: str, rows: List[Dict], per_song: int = 3) -> List[Dict]:
    if not FLAGS.get("USE_LLM") or not rows:
        return rows
    llm = get_llm()
    if llm is None:
        return rows
    payload = [
        {"i": i, "artist": r.get("Artist", ""), "song": r.get("Song", ""), "context": r.get("Context", ""), "word": r.get("Word", "")}
        for i, r in enumerate(rows[:80])
    ]
    js = llm.complete_json(
        "For each (artist,song), pick up to "
        + str(per_song)
        + " contexts that most clearly demonstrate rhymes related to '"
        + query_word
        + "'. Return JSON: {'by_song': {'artist | song':[indices]}}",
        schema_hint="{'by_song':{str:[int,...]}}",
        temperature=0.2,
    )
    by = (js or {}).get("by_song", {}) if isinstance(js, dict) else {}
    chosen = set()
    for idxs in by.values():
        for i in (idxs or [])[:per_song]:
            if isinstance(i, int) and 0 <= i < len(payload):
                chosen.add(i)
    if not chosen:
        return rows
    return [rows[i] for i in sorted(chosen)] + [r for i, r in enumerate(rows) if i not in chosen]
