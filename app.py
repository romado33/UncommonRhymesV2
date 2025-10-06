from pathlib import Path
import gradio as gr
from wordfreq import zipf_frequency

# Core logic
from rhyme_core.search import (
    search_word,
    _get_pron,
    _clean,
)
from rhyme_core.prosody import (
    syllable_count,
    stress_pattern_str,
    metrical_name,
)

# Patterns DB (returns enriched rows when available)
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except Exception:  # pragma: no cover
    from rhyme_core.patterns import find_patterns_by_keys  # type: ignore

# Optional LLM hooks (all no-op if modules/flags are absent)
try:
    from config import FLAGS as _FLAGS
    from llm.rerank import rerank_candidates
    from llm.phrase_gen import generate_phrases
    from llm.patterns_semantic import pick_best_contexts
    from llm.multiword_mining import mine_multiword_variants
    from llm.nl_query import parse_query
except Exception:
    class _D:
        LLM_RERANK=False; LLM_PHRASE_GEN=False; LLM_PATTERN_RERANK=False; LLM_MULTIWORD_MINE=False; LLM_NL_QUERY=False
    _FLAGS=_D()
    def rerank_candidates(*a, **k): return a[2] if len(a)>=3 else []
    def generate_phrases(*a, **k): return []
    def pick_best_contexts(*a, **k): return a[1] if len(a)>=2 else []
    def mine_multiword_variants(*a, **k): return []
    def parse_query(*a, **k): return {}

# ---------- helpers ----------

def _rarity(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0


def _prosody_row_from_pron(word: str, pron):
    """Return compact prosody tuple for a word/pron list."""
    p = pron or []
    syls = syllable_count(p)
    stress = stress_pattern_str(p)  # e.g. 1-0 or 1-1-0
    meter = metrical_name(stress) if stress else "—"
    return [word, f"{syls} • {stress} • {meter}"]


# ---------- main handler ----------

def do_search(*args):
    if len(args) == 6:
        word, rhyme_type, slant, syl_min, syl_max, rarity_min = args
        phrase = ""
        patterns_limit = 50
    elif len(args) == 9:
        word, phrase, rhyme_type, slant, syl_min, syl_max, _include_pron, patterns_limit, rarity_min = args
    else:  # pragma: no cover
        raise ValueError(f"Unexpected number of inputs: {len(args)}")

    word = (word or "").strip()
    phrase = (phrase or "").strip()  # *** no default text, will only be used if user actually enters something ***
    rarity_min = float(rarity_min)
    query_summary = _query_summary(word)

    # quick header summary for the query word
    q_pron = _get_pron(_clean(word)) if word else []
    q_syl = syllable_count(q_pron) if q_pron else 0
    q_stress = stress_pattern_str(q_pron) if q_pron else ""
    q_metre = metrical_name(q_stress) if q_stress else "—"
    header_md = f"**{word}** · {q_syl} syllables · stress **{q_stress or '—'}** · metre **{q_metre}**"

    # Pull a full pool and ALWAYS include pronunciations so we can compute prosody.
    res = search_word(
        word,
        rhyme_type="any",
        slant_strength=float(slant),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        include_pron=True,
    ) if word else []

    # --- split & curate ---
    def _tail_key_from_pron(pron):
        from rhyme_core.search import _norm_tail  # lazy import to avoid cycles
        try:
            return tuple(_norm_tail(pron or []))
        except Exception:
            return ()

    # First-row buckets
    uncommon, slant_list, multiword = [], [], []

    # Split
    slant_list, multiword = [], []
    for r in res:
        rt = (r.get("rhyme_type") or "").lower()
        sc = float(r.get("score", 0.0))
        is_multi = bool(r.get("is_multiword"))
        if rt == "consonant":
            # hide consonant class per latest guidance
            continue
        if rt != "perfect" or sc < 0.999:
            slant_list.append(r)
        if is_multi:
            multiword.append(r)

    single_word = [r for r in res if not r.get("is_multiword")]
    perfect_all = [r for r in single_word if (r.get("rhyme_type", "").startswith("perfect"))]
    rare_perfects = [r for r in perfect_all if _rarity(r["word"]) >= rarity_min]

    fallback_perfects = []
    if len(rare_perfects) < TARGET_N:
        need = TARGET_N - len(rare_perfects)
        ranked_perfects = sorted(
            perfect_all,
            key=lambda x: (
                -_rarity(x["word"]),
                _prosody_bonus(qpron, x.get("pron") or []),
                -float(x.get("score", 0.0)),
                x["word"],
            ),
        )
        seen_words = {r["word"] for r in rare_perfects}
        for r in ranked_perfects:
            if r["word"] in seen_words:
                continue
            fallback_perfects.append(r)
            seen_words.add(r["word"])
            if len(fallback_perfects) >= need:
                break

    backfill = []
    if len(rare_perfects) + len(fallback_perfects) < TARGET_N:
        need = TARGET_N - (len(rare_perfects) + len(fallback_perfects))
        strong_slants = [
            r for r in single_word
            if (r.get("rhyme_type") in ("assonant",) and _rarity(r["word"]) >= (rarity_min + 0.10))
        ]
        bf = [r for r in bf if float(r.get("score", 0.0)) >= 0.55]
        backfill = bf

    curation_pool = perfect_rare + backfill

    seen_tails = set()
    for r in sorted(
        curation_pool,
        key=lambda x: (-_rarity(x["word"]), -float(x.get("score", 0.0)), x["word"])  # rare then strong
    ):
        tkey = tuple(_norm_tail(r.get("pron") or []))
        if tkey in seen_tails:
            continue
        seen_tails.add(tkey)
        uncommon.append(r)
        if len(uncommon) >= 20:
            break

    # format rows
    def as_rows(items, add_type=False):
        rows = []
        for r in items:
            prosody = _prosody_compact(r.get("pron") or [])
            if add_type:
                base.append(r.get("rhyme_type", ""))
            rows.append(base)
        return rows

    row1_col1 = as_rows(uncommon)
    row1_col2 = as_rows(sorted(slant_list, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50], add_type=True)
    row1_col3 = as_rows(sorted(multiword, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50])

    # Row 2: patterns DB — now uses PHRASE **only if user entered it**; otherwise uses WORD
    key_for_patterns = phrase if phrase else word
    patterns_rows = []
    if key_for_patterns:
        try:
            enriched = find_patterns_by_keys(key_for_patterns, limit=int(patterns_limit)) or []
            # Keep rows where either target OR source truly rhymes with the query *word* pronunciation.
            qpr = q_pron
            if qpr:
                from rhyme_core.search import classify_rhyme, _final_coda
                def _best_choice(target_word: str, source_word: str):
                    def qual(rt: str) -> int:
                        return {"perfect": 3, "assonant": 2, "consonant": 0, "slant": 1}.get(rt, 0)
                    choices = []
                    for w in [target_word or "", source_word or ""]:
                        w = (w or "").strip().lower()
                        if not w:
                            continue
                        pr = _get_pron(_clean(w)) or []
                        if not pr:
                            continue
                        rt = classify_rhyme(qpr, pr)
                        if rt == "none" or rt == "consonant":
                            continue
                        if rt in ("assonant",):
                            if tuple(_final_coda(qpr)) != tuple(_final_coda(pr)):
                                continue
                        choices.append((qual(rt), w, pr, rt))
                    if not choices:
                        return None
                    choices.sort(reverse=True)
                    return choices[0]

                for d in enriched:
                    tgt = (d.get("target_rhyme") or d.get("target_word") or "").strip().lower()
                    src = (d.get("source_word") or "").strip().lower()
                    pick = _best_choice(tgt, src)
                    if not pick:
                        continue
                    _, chosen_word, chosen_pr, _rtype = pick
                    base = _prosody_row_from_pron(chosen_word, chosen_pr)
                    artist = d.get("artist", "")
                    song = d.get("song_title", "")
                    ctx_src = (d.get("lyric_context") or d.get("source_context") or "").strip()
                    ctx_tgt = (d.get("target_context") or "").strip()
                    context = ctx_src
                    if ctx_tgt:
                        context = f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt
                    patterns_rows.append(base + [artist, song, context[:400]])
        except Exception:
            patterns_rows = []

    return header_md, row1_col1, row1_col2, row1_col3, patterns_rows


# ---------- UI ----------

def build_ui():
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()

    with gr.Blocks() as demo:
        msgs = []
        msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
        msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
        gr.Markdown("\n".join(msgs))
        gr.Markdown("# Uncommon Rhymes V2 — prosody outputs")

        # Inputs — *** no default text values ***
        with gr.Row():
            word = gr.Textbox(label="Word", placeholder="")  # no default
            phrase = gr.Textbox(label="Phrase for patterns (optional)", placeholder="")  # no default
        with gr.Row():
            rhyme_type = gr.Dropdown(["any", "perfect", "assonant", "slant"], value="any", label="Rhyme type (ignored in split)")
            slant = gr.Slider(0.0, 1.0, value=0.5, step=0.05, label="Slant strength")
            syl_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            syl_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
            include_pron = gr.Checkbox(value=False, label="(unused) Show pronunciations")
            patterns_limit = gr.Slider(5, 200, value=50, step=5, label="Patterns max rows")
            rarity_min = gr.Slider(0.30, 0.70, value=0.42, step=0.01, label="Rarity ≥ (uncommon filter)")

        btn = gr.Button("Search", variant="primary")

        # Query-word prosody summary
        header = gr.Markdown(visible=True)

        # Row 1: three columns compact (Word • prosody)
        with gr.Row():
            out_uncommon = gr.Dataframe(
                headers=["Word", "Prosody"],
                datatype=["str", "str"],
                label="Uncommon Rhymes (curated ~20)",
                wrap=True,
            )
            out_slant = gr.Dataframe(
                headers=["Word", "Prosody", "Type"],
                datatype=["str", "str", "str"],
                label="Slant Rhymes",
                wrap=True,
            )
            out_multi = gr.Dataframe(
                headers=["Word", "Prosody"],
                datatype=["str", "str"],
                label="Multi-word Rhymes",
                wrap=True,
            )

        # Row 2: patterns DB with artist/song/context
        with gr.Row():
            out_patterns = gr.Dataframe(
                headers=["Word", "Prosody", "Artist", "Song", "Lyrical Context"],
                datatype=["str", "str", "str", "str", "str"],
                label="Rap Pattern Database",
                wrap=True,
            )

        # Bind both signatures (compat for cached clients)
        btn.click(
            do_search,
            [word, rhyme_type, slant, syl_min, syl_max, rarity_min],
            [header, out_uncommon, out_slant, out_multi, out_patterns],
        )
        btn.click(
            do_search,
            [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min],
            [header, out_uncommon, out_slant, out_multi, out_patterns],
        )

    return demo


if __name__ == "__main__":
    build_ui().launch()
