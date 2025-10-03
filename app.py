import gradio as gr
from pathlib import Path
from rhyme_core.search import search_word, search_phrase_to_words, make_csv_bytes
from rhyme_core.patterns import find_patterns_by_keys

def _rows_to_table(res, include_pron=False):
    if not res:
        return []
    cols = ["Candidate","Type","Score","Why"]
    if include_pron:
        cols.insert(1, "Pron")
    rows = []
    for r in res:
        base = [r["word"]]
        if include_pron:
            base.append(" ".join(r.get("pron", []) or []))
        base += [r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")]
        rows.append(base)
    return rows

def do_word(word, rhyme_type, slant, syl_min, syl_max, w_quality, w_rarity, include_pron):
    res = search_word(
        word,
        rhyme_type=rhyme_type,
        slant_strength=slant,
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=300,
        weight_quality=float(w_quality),
        weight_rarity=float(w_rarity),
        include_pron=bool(include_pron),
    )
    return _rows_to_table(res, include_pron=bool(include_pron))

def do_phrase(phrase, rhyme_type, slant, syl_min, syl_max, w_quality, w_rarity, include_pron):
    res = search_phrase_to_words(
        phrase,
        rhyme_type=rhyme_type,
        slant_strength=slant,
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=300,
        weight_quality=float(w_quality),
        weight_rarity=float(w_rarity),
        include_pron=bool(include_pron),
    )
    return _rows_to_table(res, include_pron=bool(include_pron))

def do_patterns(phrase, limit):
    rows = find_patterns_by_keys(phrase, limit=int(limit))
    out = []
    for r in rows:
        out.append([r.get("_table","patterns"), r.get("id",""), r.get("_preview","")])
    return out

def do_download_csv(input_word, rhyme_type, slant, syl_min, syl_max, w_quality, w_rarity, include_pron):
    csv_bytes = make_csv_bytes(
        input_word,
        rhyme_type=rhyme_type,
        slant_strength=slant,
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        weight_quality=float(w_quality),
        weight_rarity=float(w_rarity),
        include_pron=bool(include_pron),
    )
    return csv_bytes

with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()
    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Uncommon Rhymes V2 — enhanced")

    with gr.Tab("Word → rhymes"):
        with gr.Row():
            w = gr.Textbox(label="Word", placeholder="window", scale=2)
            include_pron = gr.Checkbox(value=False, label="Show pronunciations")
        with gr.Row():
            rhyme_type = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="Rhyme type")
            slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        with gr.Row():
            syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        with gr.Row():
            w_quality = gr.Slider(0.0, 1.0, value=0.6, step=0.05, label="Weight: rhyme quality")
            w_rarity  = gr.Slider(0.0, 1.0, value=0.4, step=0.05, label="Weight: rarity")
        with gr.Row():
            btn = gr.Button("Search", variant="primary")
            dl = gr.DownloadButton("Download CSV", file_name="rhymes.csv")
        out = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], wrap=True)
        btn.click(
            do_word,
            [w, rhyme_type, slant, syl_min, syl_max, w_quality, w_rarity, include_pron],
            out
        )
        dl.click(
            do_download_csv,
            [w, rhyme_type, slant, syl_min, syl_max, w_quality, w_rarity, include_pron],
            dl
        )

    with gr.Tab("Phrase → single-word rhymes"):
        with gr.Row():
            p = gr.Textbox(label="Phrase", placeholder="him so", scale=2)
            include_pron2 = gr.Checkbox(value=False, label="Show pronunciations")
        with gr.Row():
            rhyme_type2 = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="Rhyme type")
            slant2 = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        with gr.Row():
            syl_min2 = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            syl_max2 = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        with gr.Row():
            w_quality2 = gr.Slider(0.0, 1.0, value=0.6, step=0.05, label="Weight: rhyme quality")
            w_rarity2  = gr.Slider(0.0, 1.0, value=0.4, step=0.05, label="Weight: rarity")
        btn2 = gr.Button("Search", variant="primary")
        out2 = gr.Dataframe(headers=["Candidate","Pron","Type","Score","Why"], datatype=["str","str","str","number","str"], wrap=True)
        btn2.click(
            do_phrase,
            [p, rhyme_type2, slant2, syl_min2, syl_max2, w_quality2, w_rarity2, include_pron2],
            out2
        )

    with gr.Tab("Phrase → patterns (v2)"):
        pp = gr.Textbox(label="Phrase", placeholder="him so")
        limit = gr.Slider(5, 200, value=50, step=5, label="Max rows")
        btn3 = gr.Button("Find patterns")
        out3 = gr.Dataframe(headers=["Table","ID","Preview"], datatype=["str","str","str"], wrap=True)
        btn3.click(do_patterns, [pp, limit], out3)

if __name__ == "__main__":
    demo.launch()
