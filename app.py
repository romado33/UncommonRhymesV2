import gradio as gr
from pathlib import Path
from wordfreq import zipf_frequency
from rhyme_core.search import search_word
from rhyme_core.patterns import find_patterns_by_keys

def _rarity(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0

def _build_table(res, include_pron=False):
    """Always return 5 columns to match the Dataframe headers."""
    rows = []
    for r in res:
        pron = " ".join(r.get("pron") or [])
        if not include_pron:
            pron = ""
        rows.append([
            r["word"],
            pron,
            r.get("rhyme_type", ""),
            r.get("score", 0.0),
            r.get("why", ""),
        ])
    return rows

def do_search(*args):
    """Backward-compat handler.
    Accepts either:
      - 5 args:  word, rhyme_type, slant, syl_min, syl_max
      - 8 args:  word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit
    """
    if len(args) == 5:
        word, rhyme_type, slant, syl_min, syl_max = args
        phrase = ""
        include_pron = False
        patterns_limit = 50
    elif len(args) == 8:
        word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit = args
    else:
        raise ValueError(f"Unexpected number of inputs: {len(args)}")

    res = search_word(
        word,
        rhyme_type="any",  # split view wants full pool
        slant_strength=float(slant),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        include_pron=bool(include_pron),
    )

    uncommon, slant_list, multiword = [], [], []
    for r in res:
        w = r["word"]
        rar = _rarity(w)
        rt = r.get("rhyme_type","")

        if rt != "perfect":
            slant_list.append(r)
        else:
            if rar >= 0.45:  # curated uncommon cutoff
                uncommon.append((rar, r))

        if (" " in w) or ("-" in w):
            multiword.append(r)

    uncommon = [r for _, r in sorted(uncommon, key=lambda x: (-x[0], x[1]["word"]))][:20]
    slant_list = sorted(slant_list, key=lambda x: (-x.get("score",0.0), x["word"]))[:50]
    multiword = sorted(multiword, key=lambda x: (-x.get("score",0.0), x["word"]))[:50]

    query_for_patterns = (phrase or word).strip()
    patterns_rows = find_patterns_by_keys(query_for_patterns, limit=int(patterns_limit)) if query_for_patterns else []
    patterns_table = [
        [r.get("_table","song_rhyme_patterns"), r.get("id",""), r.get("_preview","")]
        for r in patterns_rows
    ]

    return (
        _build_table(uncommon, include_pron),
        _build_table(slant_list, include_pron),
        _build_table(multiword, include_pron),
        patterns_table,
    )

with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()
    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Uncommon Rhymes V2 — split results (compat)")

    # Inputs (8 widgets). Older serialized UIs may still send 5 args; do_search handles both.
    with gr.Row():
        word = gr.Textbox(label="Word", placeholder="sister")
        phrase = gr.Textbox(label="Phrase for patterns (optional)", placeholder="him so")
    with gr.Row():
        rhyme_type = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="Rhyme type (ignored in split)")
        slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
        syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        include_pron = gr.Checkbox(value=False, label="Show pronunciations")
        patterns_limit = gr.Slider(5, 200, value=50, step=5, label="Patterns max rows")

    btn = gr.Button("Search", variant="primary")

    with gr.Row():
        out_uncommon = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Uncommon Rhymes (curated ~20)", wrap=True)
        out_slant = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Slant Rhymes", wrap=True)
        out_multi = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Multi-word Rhymes", wrap=True)

    with gr.Row():
        out_patterns = gr.Dataframe(headers=["Table","ID","Preview"], datatype=["str","str","str"], label="Rap Pattern Database (by rhyme keys)", wrap=True)

    # --- COMPAT: bind BOTH input signatures to the same handler ---
    # Legacy (5 inputs): word, rhyme_type, slant, syl_min, syl_max
    btn.click(
        do_search,
        [word, rhyme_type, slant, syl_min, syl_max],
        [out_uncommon, out_slant, out_multi, out_patterns]
    )

    # New (8 inputs): word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit
    btn.click(
        do_search,
        [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit],
        [out_uncommon, out_slant, out_multi, out_patterns]
    )

if __name__ == "__main__":
    demo.launch()
