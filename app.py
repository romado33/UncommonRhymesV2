import gradio as gr
from rhyme_core.search import search_word, search_phrase_to_words

def do_word(word, rhyme_type, slant, syl_min, syl_max):
    res = search_word(word, rhyme_type=rhyme_type, slant_strength=slant,
                      syllable_min=int(syl_min), syllable_max=int(syl_max), max_results=150)
    if not res: return []
    return [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")]] +            [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")] for r in res[1:]]

def do_phrase(phrase, rhyme_type, slant, syl_min, syl_max):
    res = search_phrase_to_words(phrase, rhyme_type=rhyme_type, slant_strength=slant,
                                 syllable_min=int(syl_min), syllable_max=int(syl_max), max_results=150)
    if not res: return []
    return [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")]] +            [[r["word"], r.get("rhyme_type",""), r.get("score",0.0), r.get("why","")] for r in res[1:]]

with gr.Blocks() as demo:
    gr.Markdown("# Rhyme Rarity (core)")
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

if __name__ == "__main__":
    demo.launch()
