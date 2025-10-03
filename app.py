import gradio as gr
from pathlib import Path
from wordfreq import zipf_frequency
from rhyme_core.search import search_word, search_phrase_to_words
from rhyme_core.patterns import find_patterns_by_keys

def _rarity(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0

def _to_rows(res, include_pron=False):
    rows = []
    for r in res:
        base = [r["word"]]
        if include_pron:
            base.append(" ".join(r.get("pron") or []))
        base += [r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")]
        rows.append(base)
    return rows

def do_search(word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit):
    # Core search from the word (always 'any' to allow full splitting)
    res = search_word(
        word,
        rhyme_type="any",
        slant_strength=float(slant),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        include_pron=bool(include_pron),
    )
    # Split into three lists
    uncommon = []
    slant_list = []
    multiword = []
    for r in res:
        w = r["word"]
        rar = _rarity(w)
        rt = r.get("rhyme_type","")
        if rt != "perfect":
            slant_list.append(r)
        else:
            # curated 'good but uncommon': prefer perfect rhymes that aren't super common
            if rar >= 0.45:   # ~zipf <= 3.6
                uncommon.append((rar, r))
        if (" " in w) or ("-" in w):
            multiword.append(r)
    # Sort & cap
    uncommon = [r for _, r in sorted(uncommon, key=lambda x: (-x[0], x[1]["word"]))][:20]
    slant_list = sorted(slant_list, key=lambda x: (-x.get("score",0.0), x["word"]))[:50]
    multiword = sorted(multiword, key=lambda x: (-x.get("score",0.0), x["word"]))[:50]

    # Patterns row: prefer phrase; fall back to word
    query_for_patterns = phrase.strip() or word.strip()
    patterns_rows = find_patterns_by_keys(query_for_patterns, limit=int(patterns_limit)) if query_for_patterns else []

    # Build tables
    headers = ["Candidate","Pron","Type","Score","Why"] if include_pron else ["Candidate","Type","Score","Why"]
    def table(res):
        rows = []
        for r in res:
            row = [r["word"]]
            if include_pron:
                row.append(" ".join(r.get("pron") or []))
            row += [r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")]
            rows.append(row)
        return rows

    patterns_table = []
    for r in patterns_rows:
        patterns_table.append([
            r.get("_table","song_rhyme_patterns"),
            r.get("id",""),
            r.get("_preview","")
        ])

    return table(uncommon), table(slant_list), table(multiword), patterns_table

with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()
    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Uncommon Rhymes V2 — split results")

    with gr.Row():
        word = gr.Textbox(label="Word", placeholder="window")
        phrase = gr.Textbox(label="Phrase for patterns (optional)", placeholder="him so")
    with gr.Row():
        rhyme_type = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="(Filter not used in split view; set to 'any')", interactive=False)
        slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
        syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        include_pron = gr.Checkbox(value=False, label="Show pronunciations")
        patterns_limit = gr.Slider(5, 200, value=50, step=5, label="Patterns max rows")

    btn = gr.Button("Search", variant="primary")

    # First row: 3 columns
    with gr.Row():
        out_uncommon = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Uncommon Rhymes (curated top ~20)", wrap=True)
        out_slant = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Slant Rhymes", wrap=True)
        out_multi = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], label="Multi-word Rhymes", wrap=True)

    # Second row: patterns DB
    with gr.Row():
        out_patterns = gr.Dataframe(headers=["Table","ID","Preview"], datatype=["str","str","str"], label="Rap Pattern Database (by rhyme keys)", wrap=True)

    btn.click(
        do_search,
        [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit],
        [out_uncommon, out_slant, out_multi, out_patterns]
    )

if __name__ == "__main__":
    demo.launch()
