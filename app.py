from __future__ import annotations
from pathlib import Path
from typing import List, Tuple

import gradio as gr

# Core search & prosody
from rhyme_core.search import (
    search_word,
    _get_pron,
    _clean,
    classify_rhyme,
    _final_coda,
    _norm_tail,
    stress_pattern_str as stress_digits_str,   # from core (digits)
    syllable_count,
)
# Your prosody module returns binary 0/1 pattern and metre name
from rhyme_core.prosody import stress_pattern_str, metrical_name  # binary stress + metre  :contentReference[oaicite:4]{index=4}

# Optional patterns DB
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except Exception:
    try:
        from rhyme_core.patterns import find_patterns_by_keys  # legacy
    except Exception:
        try:
            from patterns import find_patterns_by_keys_enriched as find_patterns_by_keys  # local fallback
        except Exception:
            try:
                from patterns import find_patterns_by_keys
            except Exception:
                find_patterns_by_keys = None  # patterns tab becomes empty


# ---------------- Utility ----------------

def rarity_zipf(word: str) -> float:
    """Cheap rarity proxy: prefer long/odd tokens; bounded to [0,1].  (Keeps UI responsive without wordfreq.)"""
    w = (word or "").lower()
    # a simple heuristic: length and presence of rare letters
    base = min(1.0, max(0.0, (len(w) - 3) / 10.0))
    rare = sum(ch in "jxqz" for ch in w) * 0.15
    return min(1.0, base + rare)


def prosody_row(word: str, pron: List[str]) -> Tuple[str, str]:
    """Return compact prosody 'S • pattern • metre' string."""
    s = syllable_count(pron)                                    # :contentReference[oaicite:5]{index=5}
    pat = stress_pattern_str(pron)                              # binary 0/1 pattern   :contentReference[oaicite:6]{index=6}
    metre = metrical_name(pat) if pat else "—"                  # metre label          :contentReference[oaicite:7]{index=7}
    return word, f"{s} • {pat or '—'} • {metre}"


def split_columns(results: List[dict]):
    """Split master search list into Uncommon/Slant/Multi-word buckets (all items carry 'pron')."""
    uncommon, slant_list, multiword = [], [], []
    for r in results:
        rt = (r.get("rhyme_type") or "").lower()
        if " " in r["word"] or "-" in r["word"]:
            multiword.append(r)
        elif rt == "perfect":
            uncommon.append(r)
        else:
            slant_list.append(r)
    return uncommon, slant_list, multiword


def curate_uncommon(perfect_rows: List[dict], rarity_min: float) -> List[dict]:
    """Guarantee up to 20 uncommon rows; backfill from strong not-perfect candidates if needed."""
    # Start with rare perfects
    rare = [r for r in perfect_rows if rarity_zipf(r["word"]) >= rarity_min]
    # De-dupe by normalized tail (from core)  :contentReference[oaicite:8]{index=8}
    seen = set()
    curated: List[dict] = []
    for r in sorted(rare, key=lambda x: (-rarity_zipf(x["word"]), -float(x["score"]), x["word"])):
        tkey = _norm_tail(r.get("pron") or [])                  # :contentReference[oaicite:9]{index=9}
        if tkey in seen:
            continue
        seen.add(tkey)
        curated.append(r)
        if len(curated) >= 20:
            return curated

    # Not enough? Backfill with best “near-perfects”
    if len(curated) < 20:
        backfill = [
            r for r in perfect_rows  # reuse pool; we’ll allow consonant/assonant if strong
            if (r.get("rhyme_type") in ("consonant", "assonant")
                and rarity_zipf(r["word"]) >= max(0.0, rarity_min - 0.05)
                and float(r.get("score", 0.0)) >= 0.82)
        ]
        for r in sorted(backfill, key=lambda x: (-float(x["score"]), x["word"])):
            tkey = _norm_tail(r.get("pron") or [])              # :contentReference[oaicite:10]{index=10}
            if tkey in seen:
                continue
            seen.add(tkey)
            curated.append(r)
            if len(curated) >= 20:
                break

    return curated


def patterns_rows(query_word: str, phrase: str, syl_min: int, syl_max: int, limit: int) -> List[List[str]]:
    """Build patterns table: [Target, Prosody, Artist, Song, Context]."""
    if not find_patterns_by_keys:
        return []

    qpron = _get_pron(_clean(query_word)) or []                 # :contentReference[oaicite:11]{index=11}
    if not qpron:
        return []

    rows: List[List[str]] = []
    try:
        enriched = find_patterns_by_keys(phrase or query_word, limit=limit) or []
    except Exception:
        enriched = []

    for d in enriched:
        tgt = (d.get("target_rhyme") or d.get("target_word") or "").strip()
        src = (d.get("source_word") or "").strip()
        # pick whichever actually rhymes with the query (ensures relevance)
        chosen_word = ""
        chosen_pron: List[str] = []
        for cand in (tgt, src):
            if not cand:
                continue
            pr = _get_pron(_clean(cand)) or []
            if not pr:
                continue
            rt = classify_rhyme(qpron, pr)                      # :contentReference[oaicite:12]{index=12}
            if rt != "none":
                chosen_word, chosen_pron = cand, pr
                break
        if not chosen_word:
            continue

        s = syllable_count(chosen_pron)                         # :contentReference[oaicite:13]{index=13}
        if not (syl_min <= s <= syl_max):
            continue
        word, pro = prosody_row(chosen_word, chosen_pron)

        artist = d.get("artist", "")
        song = d.get("song_title", "")
        ctx_src = (d.get("lyric_context") or d.get("source_context") or "").strip()
        ctx_tgt = (d.get("target_context") or "").strip()
        ctx = ctx_src
        if ctx_tgt:
            ctx = f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt
        rows.append([word, pro, artist, song, ctx[:400]])

    return rows


# ---------------- Search handler ----------------

def do_search(word: str,
              phrase: str,
              rhyme_type: str,
              slant_strength: float,
              syl_min: int,
              syl_max: int,
              _include_pron: bool,
              patterns_limit: int,
              rarity_min: float):

    # Query prosody header (binary stress + metre)
    qpron = _get_pron(_clean(word)) or []                       # :contentReference[oaicite:14]{index=14}
    q_syl = syllable_count(qpron)                               # :contentReference[oaicite:15]{index=15}
    q_pat = stress_pattern_str(qpron)                           # binary                  :contentReference[oaicite:16]{index=16}
    q_met = metrical_name(q_pat) if q_pat else "—"              # metre label             :contentReference[oaicite:17]{index=17}
    header = f"**{word.lower()}** · **{q_syl}** syllables · stress **{q_pat or '—'}** · metre **{q_met}**"

    # Pull a large pool with pronunciations so we can format prosody compactly.
    results = search_word(
        word,
        rhyme_type="any",
        slant_strength=float(slant_strength),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=750,
        include_pron=True,                                      # keep pron for display  :contentReference[oaicite:18]{index=18}
    )

    # Split & curate
    perfects, slants, multis = split_columns(results)
    uncommon = curate_uncommon(perfects, float(rarity_min))

    # Build compact rows (no horizontal scrolling)
    uncommon_rows = [list(prosody_row(r["word"], r.get("pron") or [])) for r in uncommon]
    slant_rows    = [list(prosody_row(r["word"], r.get("pron") or [])) + [r.get("rhyme_type","")] for r in slants][:200]
    multi_rows    = [list(prosody_row(r["word"], r.get("pron") or [])) for r in multis][:200]

    # Patterns table
    pat_rows = patterns_rows(word, phrase, int(syl_min), int(syl_max), int(patterns_limit))

    return header, uncommon_rows, slant_rows, multi_rows, pat_rows


# ---------------- UI ----------------

def build_ui():
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()

    with gr.Blocks() as demo:
        gr.Markdown(
            f"{'✅' if has_index else '⚠️'} **Word index**: {'found' if has_index else 'missing'}  "
            f"{'· ℹ️ **Patterns DB**: found' if has_patterns else '· ℹ️ **Patterns DB not present (optional)**'}"
        )
        gr.Markdown("# Uncommon Rhymes V2 — prosody outputs")

        with gr.Row():
            t_word   = gr.Textbox(label="Word", placeholder="sister", value="")
            t_phrase = gr.Textbox(label="Phrase for patterns (optional)", placeholder="him so", value="")
        with gr.Row():
            dd_type  = gr.Dropdown(["any", "perfect", "assonant", "consonant", "slant"], value="any", label="Rhyme type (ignored in split)")
            s_slant  = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
            s_min    = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            s_max    = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
            cb_pron  = gr.Checkbox(value=False, label="(unused) Show pronunciations")
            s_limit  = gr.Slider(5, 200, value=50, step=5, label="Patterns max rows")
            s_rare   = gr.Slider(0.30, 0.70, value=0.42, step=0.01, label="Rarity ≥ (uncommon filter)")

        btn = gr.Button("Search", variant="primary")

        # Query prosody header
        out_header = gr.Markdown(value="")

        with gr.Row():
            out_uncommon = gr.Dataframe(headers=["Word", "Prosody"], datatype=["str", "str"],
                                        label="Uncommon Rhymes (curated ~20)", wrap=True)
            out_slant    = gr.Dataframe(headers=["Word", "Prosody", "Type"], datatype=["str", "str", "str"],
                                        label="Slant Rhymes", wrap=True)
            out_multi    = gr.Dataframe(headers=["Word", "Prosody"], datatype=["str", "str"],
                                        label="Multi-word Rhymes", wrap=True)
        with gr.Row():
            out_patterns = gr.Dataframe(
                headers=["Word", "Prosody", "Artist", "Song", "Lyrical Context"],
                datatype=["str", "str", "str", "str", "str"],
                label="Rap Pattern Database",
                wrap=True
            )

        btn.click(
            do_search,
            [t_word, t_phrase, dd_type, s_slant, s_min, s_max, cb_pron, s_limit, s_rare],
            [out_header, out_uncommon, out_slant, out_multi, out_patterns]
        )
    return demo


if __name__ == "__main__":
    ui = build_ui()
    ui.launch()
