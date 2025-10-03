import gradio as gr
from pathlib import Path
from rhyme_core.search import search_word, search_phrase_to_words
from rhyme_core.patterns import find_patterns_by_keys

def do_word(word, rhyme_type, slant, syl_min, syl_max):
    res = search_word(word, rhyme_type=rhyme_type, slant_strength=slant,
                      syllable_min=int(syl_min), syllable_max=int(syl_max), max_results=200)
    if not res:
        return []
    first = [res[0]["word"], res[0].get("rhyme_type",""), res[0].get("score",0.0), res[0].get("why","")]
    rest = [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")] for r in res[1:]]
    return [first] + rest

def do_phrase(phrase, rhyme_type, slant, syl_min, syl_max):
    res = search_phrase_to_words(phrase, rhyme_type=rhyme_type, slant_strength=slant,
                                 syllable_min=int(syl_min), syllable_max=int(syl_max), max_results=200)
    if not res:
        return []
    first = [res[0]["word"], res[0].get("rhyme_type",""), res[0].get("score",0.0), res[0].get("why","")]
    rest = [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")] for r in res[1:]]
    return [first] + rest

def do_patterns(phrase, limit):
    rows = find_patterns_by_keys(phrase, limit=int(limit))
    out = []
    for r in rows:
        out.append([r.get("_table","patterns"), r.get("id",""), r.get("_preview","")])
    return out

with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()
    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Rhyme Rarity")
    with gr.Tab("Word → rhymes"):
        w = gr.Textbox(label="Word", placeholder="window")
        with gr.Row():
            rhyme_type = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="Rhyme type")
            slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        with gr.Row():
            syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        btn = gr.Button("Search")
        out = gr.Dataframe(headers=["Candidate","Type","Score","Why"], datatype=["str","str","number","str"], wrap=True)
        btn.click(do_word, [w, rhyme_type, slant, syl_min, syl_max], out)

    with gr.Tab("Phrase → single-word rhymes"):
        p = gr.Textbox(label="Phrase", placeholder="him so")
        with gr.Row():
            rhyme_type2 = gr.Dropdown(["any","perfect","assonant","consonant","slant"], value="any", label="Rhyme type")
            slant2 = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
        with gr.Row():
            syl_min2 = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            syl_max2 = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
        btn2 = gr.Button("Search")
        out2 = gr.Dataframe(headers=["Candidate","Type","Score","Why"], datatype=["str","str","number","str"], wrap=True)
        btn2.click(do_phrase, [p, rhyme_type2, slant2, syl_min2, syl_max2], out2)

    with gr.Tab("Phrase → patterns (v2)"):
        pp = gr.Textbox(label="Phrase", placeholder="him so")
        limit = gr.Slider(5, 200, value=50, step=5, label="Max rows")
        btn3 = gr.Button("Find patterns")
        out3 = gr.Dataframe(headers=["Table","ID","Preview"], datatype=["str","str","str"], wrap=True)
        btn3.click(do_patterns, [pp, limit], out3)

if __name__ == "__main__":
    demo.launch()
