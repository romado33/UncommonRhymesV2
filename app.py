import gradio as gr
from pathlib import Path
from wordfreq import zipf_frequency
from rhyme_core.search import search_word, _get_pron, _clean
from rhyme_core.prosody import syllable_count, stress_pattern_str, metrical_name

# Prefer enriched function from patterns; fall back to legacy name if present
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except ImportError:
    from rhyme_core.patterns import find_patterns_by_keys  # legacy alias expected

def _rarity(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0

def _prosody_row_from_pron(word: str, pron):
    """Return [Target Rhyme, Syllables, #-Pattern, Metrical Name] for a word/pron list."""
    p = pron or []
    syls = syllable_count(p)
    stress = stress_pattern_str(p)
    meter = metrical_name(stress) if stress else "—"
    return [word, syls, stress, meter]

def do_search(*args):
    """
    Back-compat handler:
      - 5 args:  word, rhyme_type, slant, syl_min, syl_max
      - 8 args:  word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit
    """
    if len(args) == 5:
        word, rhyme_type, slant, syl_min, syl_max = args
        phrase = ""
        patterns_limit = 50
    elif len(args) == 8:
        word, phrase, rhyme_type, slant, syl_min, syl_max, _include_pron, patterns_limit = args
    else:
        raise ValueError(f"Unexpected number of inputs: {len(args)}")

    # Pull a full pool and ALWAYS include pronunciations so we can compute prosody.
    res = search_word(
        word,
        rhyme_type="any",
        slant_strength=float(slant),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        include_pron=True,
    )

    # Split into Uncommon (rare perfects), Slant (non-perfect), Multi-word (space/hyphen).
    uncommon, slant_list, multiword = [], [], []
    for r in res:
        w_cand = r["word"]
        rar = _rarity(w_cand)
        rt = r.get("rhyme_type", "")
        if rt == "perfect" and rar >= 0.45:
            uncommon.append((rar, r))
        if rt != "perfect":
            slant_list.append(r)
        if (" " in w_cand) or ("-" in w_cand):
            multiword.append(r)

    # Sort & cap
    uncommon = [r for _, r in sorted(uncommon, key=lambda x: (-x[0], x[1]["word"]))][:20]
    slant_list = sorted(slant_list, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50]
    multiword = sorted(multiword, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50]

    # Build row-1 tables: Target Rhyme, Syllables, #-Pattern, Metrical Name
    def as_rows(items):
        rows = []
        for r in items:
            rows.append(_prosody_row_from_pron(r["word"], r.get("pron") or []))
        return rows

    row1_col1 = as_rows(uncommon)
    row1_col2 = as_rows(slant_list)
    row1_col3 = as_rows(multiword)

    # Row 2: Patterns DB (target rhyme + prosody + artist/song/context)
    query_for_patterns = (phrase or word).strip()
    patterns_rows = []
    if query_for_patterns:
        try:
            enriched = find_patterns_by_keys(query_for_patterns, limit=int(patterns_limit))
            # If API already returns enriched dicts with 'syllables', use directly
            if isinstance(enriched, list) and enriched and isinstance(enriched[0], dict) and "syllables" in enriched[0]:
                for d in enriched:
                    patterns_rows.append([
                        d.get("target_rhyme", ""),
                        d.get("syllables", 0),
                        d.get("stress", ""),
                        d.get("meter", "—"),
                        d.get("artist", ""),
                        d.get("song_title", ""),
                        d.get("lyric_context", ""),
                    ])
            else:
                # Fallback: legacy rows from table; compute prosody locally
                for d in enriched or []:
                    target = (d.get("target_word") or d.get("source_word") or "").strip().lower()
                    pron = _get_pron(_clean(target)) or []
                    base = _prosody_row_from_pron(target, pron)
                    artist = d.get("artist", "")
                    song = d.get("song_title", "")
                    ctx_src = (d.get("source_context") or "").strip()
                    ctx_tgt = (d.get("target_context") or "").strip()
                    context = ctx_src if not ctx_tgt else (f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt)
                    patterns_rows.append(base + [artist, song, context[:300]])
        except Exception:
            patterns_rows = []

    return row1_col1, row1_col2, row1_col3, patterns_rows

with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()
    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Uncommon Rhymes V2 — prosody outputs")

    # Inputs (8 widgets). We bind both 5-arg and 8-arg signatures for cached clients.
    with gr.Row():
        word = gr.Textbox(label="Word", placeholder="sister")
        phrase = gr.Textbox(label="Phrase for patterns (optional)", placeholder="him so")
    with gr.Row():
        rhyme_type = gr.Dropdown(["any", "perfect", "assonant", "consonant", "slant"], value="any", label="Rhyme type (ignored in split)")
        slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
        syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        include_pron = gr.Checkbox(value=False, label="(unused) Show pronunciations")
        patterns_limit = gr.Slider(5, 200, value=50, step=5, label="Patterns max rows")

    btn = gr.Button("Search", variant="primary")

    # Row 1: three columns with prosodic info
    with gr.Row():
        out_uncommon = gr.Dataframe(
            headers=["Target Rhyme", "Syllables", "#-Pattern", "Metrical Name"],
            datatype=["str", "number", "str", "str"],
            label="Uncommon Rhymes (curated ~20)",
            wrap=True
        )
        out_slant = gr.Dataframe(
            headers=["Target Rhyme", "Syllables", "#-Pattern", "Metrical Name"],
            datatype=["str", "number", "str", "str"],
            label="Slant Rhymes",
            wrap=True
        )
        out_multi = gr.Dataframe(
            headers=["Target Rhyme", "Syllables", "#-Pattern", "Metrical Name"],
            datatype=["str", "number", "str", "str"],
            label="Multi-word Rhymes",
            wrap=True
        )

    # Row 2: patterns DB with artist/song/context
    with gr.Row():
        out_patterns = gr.Dataframe(
            headers=["Target Rhyme", "Syllables", "#-Pattern", "Metrical Name", "Artist", "Song", "Lyrical Context"],
            datatype=["str", "number", "str", "str", "str", "str", "str"],
            label="Rap Pattern Database",
            wrap=True
        )

    # Bind both 5-arg and 8-arg signatures (compat with cached UIs)
    btn.click(
        do_search,
        [word, rhyme_type, slant, syl_min, syl_max],
        [out_uncommon, out_slant, out_multi, out_patterns]
    )
    btn.click(
        do_search,
        [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit],
        [out_uncommon, out_slant, out_multi, out_patterns]
    )

if __name__ == "__main__":
    demo.launch()
