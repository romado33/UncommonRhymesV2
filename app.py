import gradio as gr
from pathlib import Path
from collections import defaultdict
from wordfreq import zipf_frequency

from rhyme_core.search import (
    search_word,
    _get_pron,
    _clean,
    classify_rhyme,
    _final_coda,
    _norm_tail,
    stress_pattern_str,
    syllable_count,
)
from rhyme_core.prosody import metrical_name

# Prefer enriched function from patterns; fall back to legacy name if present
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except ImportError:  # legacy name
    from rhyme_core.patterns import find_patterns_by_keys

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

# -----------------------
# Helpers
# -----------------------

def _rarity(word: str) -> float:
    """Return 0..1 rarity (1 = very rare), based on Zipf frequency."""
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0


def _prosody_compact(pron) -> str:
    """Return 'S • Stress • Metre' compact string."""
    p = pron or []
    s = syllable_count(p)
    sp = stress_pattern_str(p) or "—"
    m = metrical_name(sp) if sp and sp != "—" else "—"
    return f"{s} • {sp} • {m}"


def _query_summary(word: str) -> str:
    w = _clean(word or "")
    if not w:
        return "—"
    pr = _get_pron(w) or []
    if not pr:
        return f"**{w}**: (no pronunciation found)"
    s = syllable_count(pr)
    sp = stress_pattern_str(pr) or "—"
    m = metrical_name(sp) if sp and sp != "—" else "—"
    return f"**{w}** · **{s}** syllables · stress **{sp}** · metre **{m}**"


def _mark_ctx(text: str, target: str, source: str) -> str:
    if not text:
        return ""
    out = text
    for w in [target or "", source or ""]:
        w = w.strip()
        if not w:
            continue
        out = out.replace(w, f"▁{w}▁")
        cap = w.capitalize()
        if cap != w:
            out = out.replace(cap, f"▁{cap}▁")
    return out


def _in_syllable_bounds(pron, smin: int, smax: int) -> bool:
    s = syllable_count(pron or [])
    return smin <= s <= smax


def _prosody_bonus(query_pron, cand_pron):
    """Return tuple used for tie-breaks: (-stress_match, abs(syl_diff))."""
    qs = stress_pattern_str(query_pron) or ""
    cs = stress_pattern_str(cand_pron or []) or ""
    stress_match = 1 if (qs and cs and qs == cs) else 0
    qn = syllable_count(query_pron or [])
    cn = syllable_count(cand_pron or [])
    return (-stress_match, abs(qn - cn))


def _best_rhyme_choice(query_pron, target_word: str, source_word: str):
    def _qual(rt: str) -> int:
        return {"perfect": 3, "consonant": 2, "assonant": 2, "slant": 1}.get(rt, 0)

    choices = []
    for w in [target_word or "", source_word or ""]:
        w = w.strip().lower()
        if not w:
            continue
        pr = _get_pron(_clean(w)) or []
        if not pr:
            continue
        rt = classify_rhyme(query_pron, pr)
        if rt == "none":
            continue
        if rt in ("assonant", "consonant"):
            if tuple(_final_coda(query_pron)) != tuple(_final_coda(pr)):
                continue
        choices.append((_qual(rt), w, pr, rt))

    if not choices:
        return None
    choices.sort(reverse=True)
    return choices[0]

# -----------------------
# Core search (main tab)
# -----------------------

def do_search(*args):
    if len(args) == 6:
        word, rhyme_type, slant, syl_min, syl_max, rarity_min = args
        phrase = ""
        patterns_limit = 50
    elif len(args) == 9:
        word, phrase, rhyme_type, slant, syl_min, syl_max, _include_pron, patterns_limit, rarity_min = args
    else:
        raise ValueError(f"Unexpected number of inputs: {len(args)}")

    rarity_min = float(rarity_min)
    query_summary = _query_summary(word)

    # Deterministic pool (always include pron for prosody)
    res = search_word(
        word,
        rhyme_type="any",
        slant_strength=float(slant),
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=1000,
        include_pron=True,
    )

    # Optional: natural-language parser (reserved; not wired to a text box yet)
    try:
        parsed = parse_query("") if _FLAGS.LLM_NL_QUERY else {}
    except Exception:
        parsed = {}
    rhyme_type = rhyme_type or parsed.get("rhyme_type", "any")

    qpron = _get_pron(_clean(word)) or []

    # Split
    slant_list, multiword = [], []
    for r in res:
        rt = (r.get("rhyme_type") or "").lower()
        sc = float(r.get("score", 0.0))
        if rt != "perfect" or sc < 0.999:
            slant_list.append(r)
        if r.get("is_multiword"):
            multiword.append(r)

    # Curate uncommon (~20)
    TARGET_N = 20
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
            if (r.get("rhyme_type") in ("consonant", "assonant"))
            and _rarity(r["word"]) >= max(0.0, rarity_min - 0.10)
            and ({"perfect": 1.0, "consonant": 0.9, "assonant": 0.85}.get(r.get("rhyme_type", ""), 0) * float(r.get("score", 0.0)) >= 0.55)
        ]
        strong_slants = sorted(
            strong_slants,
            key=lambda x: (
                -_rarity(x["word"]),
                _prosody_bonus(qpron, x.get("pron") or []),
                -float(x.get("score", 0.0)),
                x["word"],
            ),
        )[:need]
        backfill = strong_slants

    curation_pool = rare_perfects + fallback_perfects + backfill

    seen_tails = set()
    curated = []
    for r in sorted(
        curation_pool,
        key=lambda x: (
            -_rarity(x["word"]),
            _prosody_bonus(qpron, x.get("pron") or []),
            -float(x.get("score", 0.0)),
            x["word"],
        ),
    ):
        tkey = tuple(_norm_tail(r.get("pron") or []))
        if tkey in seen_tails:
            continue
        seen_tails.add(tkey)
        curated.append(r)
        if len(curated) >= TARGET_N:
            break
    uncommon = curated

    # Sort/cap others (with prosody tie-break)
    slant_list = sorted(
        slant_list,
        key=lambda x: (
            -x.get("score", 0.0),
            _prosody_bonus(qpron, x.get("pron") or []),
            x["word"],
        ),
    )[:50]
    multiword = sorted(
        multiword,
        key=lambda x: (
            -x.get("score", 0.0),
            _prosody_bonus(qpron, x.get("pron") or []),
            x["word"],
        ),
    )[:50]

    # LLM rerank (safe no-op if disabled)
    if _FLAGS.LLM_RERANK:
        try:
            uncommon = rerank_candidates(word, qpron, uncommon)
            slant_list = rerank_candidates(word, qpron, slant_list)
            multiword = rerank_candidates(word, qpron, multiword)
        except Exception:
            pass

    # Build compact tables
    def as_rows(items, add_type: bool = False):
        rows = []
        for r in items:
            prosody = _prosody_compact(r.get("pron") or [])
            if add_type:
                rows.append([r["word"], prosody, (r.get("rhyme_type") or "")])
            else:
                rows.append([r["word"], prosody])
        return rows

    row1_col1 = as_rows(uncommon)
    row1_col2 = as_rows(slant_list, add_type=True)
    row1_col3 = as_rows(multiword)

    # Patterns: require query token in source/target; group by song default
    query_for_patterns = (phrase or word).strip()
    patterns_rows = []
    if query_for_patterns:
        try:
            enriched = find_patterns_by_keys(query_for_patterns, limit=int(patterns_limit))
            query_pr = qpron
            qtok = _clean(word).lower()

            groups = defaultdict(list)  # (artist,song) -> rows

            for d in enriched or []:
                tgt = (d.get("target_rhyme") or d.get("target_word") or "").strip().lower()
                src = (d.get("source_word") or "").strip().lower()

                # require query token to appear in src or tgt tokenization
                src_tokens = {t for t in src.replace("-", " ").split() if t}
                tgt_tokens = {t for t in tgt.replace("-", " ").split() if t}
                if qtok not in src_tokens and qtok not in tgt_tokens:
                    continue

                best = _best_rhyme_choice(query_pr, tgt, src)
                if not best:
                    continue
                _, chosen_word, chosen_pr, _rtype = best
                if not _in_syllable_bounds(chosen_pr, int(syl_min), int(syl_max)):
                    continue

                prosody = _prosody_compact(chosen_pr)
                artist = d.get("artist", "")
                song = d.get("song_title", "")
                ctx_src = (d.get("lyric_context") or d.get("source_context") or "").strip()
                ctx_tgt = (d.get("target_context") or "").strip()
                context = ctx_src
                if ctx_tgt:
                    context = f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt
                context = _mark_ctx(context, tgt, src).replace("\n", " ")
                if len(context) > 140:
                    context = context[:137] + "…"

                groups[(artist, song)].append([chosen_word, prosody, artist, song, context])

            # group by default, cap per song
            MAX_PER_SONG = 3
            ordered = []
            for (artist, song), rows in groups.items():
                if _FLAGS.LLM_PATTERN_RERANK:
                    try:
                        rows = pick_best_contexts(word, [
                            {"Word": w, "Prosody": p, "Artist": a, "Song": s, "Context": c}
                            for (w,p,a,s,c) in rows
                        ], per_song=MAX_PER_SONG)
                        rows = [[d["Word"], d["Prosody"], d["Artist"], d["Song"], d["Context"]] for d in rows]
                    except Exception:
                        pass
                ordered.extend(rows[:MAX_PER_SONG])
            patterns_rows = ordered

        except Exception:
            patterns_rows = []

    return _query_summary(word), row1_col1, row1_col2, row1_col3, patterns_rows

# -----------------------
# Reverse phrase search (beta) — lightweight CMU-only + optional LLM variants
# -----------------------

def do_reverse(phrase: str, syl_min: int, syl_max: int):
    phrase = (phrase or "").strip()
    if not phrase:
        return []
    # take last word of phrase
    tail_word = _clean(phrase.split()[-1])
    if not tail_word:
        return []

    # Search multi-word rhymes for the tail word, then keep only multi-word candidates
    res = search_word(
        tail_word,
        rhyme_type="any",
        slant_strength=0.5,
        syllable_min=int(syl_min),
        syllable_max=int(syl_max),
        max_results=500,
        include_pron=True,
    )
    multi = [r for r in res if r.get("is_multiword")]

    # Optionally mine extra variants via LLM and keep those that end in perfect rhyme
    if getattr(_FLAGS, "LLM_MULTIWORD_MINE", False):
        try:
            extra = mine_multiword_variants(tail_word)
            qpr = _get_pron(_clean(tail_word)) or []
            for phrase in extra:
                last = _clean(phrase.split()[-1])
                cpr = _get_pron(last) or []
                if classify_rhyme(qpr, cpr) == "perfect":
                    multi.append({"word": phrase, "pron": cpr})
        except Exception:
            pass

    out = [[r["word"], _prosody_compact(r.get("pron") or [])] for r in multi[:100]]
    return out

# -----------------------
# UI (two tabs)
# -----------------------
with gr.Blocks() as demo:
    data_dir = Path("data")
    has_index = (data_dir / "words_index.sqlite").exists()
    has_patterns = (data_dir / "patterns.db").exists() or (data_dir / "patterns_small.db").exists()

    msgs = []
    msgs.append("✅ **Word index**: found." if has_index else "⚠️ **Word index missing**: build with `python -m scripts.build_index`.")
    msgs.append("ℹ️ **Patterns DB**: found." if has_patterns else "ℹ️ **Patterns DB not present (optional)**.")
    gr.Markdown("\n".join(msgs))

    gr.Markdown("# Uncommon Rhymes V2 — prosody outputs (compact)")

    with gr.Tabs():
        with gr.TabItem("Rhymes"):
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
                rarity_min = gr.Slider(0.20, 0.70, value=0.30, step=0.01, label="Rarity ≥ (uncommon filter)")

            summary_md = gr.Markdown("—")
            with gr.Row():
                out_uncommon = gr.Dataframe(headers=["Word", "Prosody"], datatype=["str", "str"], label="Uncommon Rhymes (curated ~20)", wrap=True)
                out_slant = gr.Dataframe(headers=["Word", "Prosody", "Type"], datatype=["str", "str", "str"], label="Slant Rhymes", wrap=True)
                out_multi = gr.Dataframe(headers=["Word", "Prosody"], datatype=["str", "str"], label="Multi-word Rhymes", wrap=True)
            with gr.Row():
                out_patterns = gr.Dataframe(headers=["Word", "Prosody", "Artist", "Song", "Context"], datatype=["str", "str", "str", "str", "str"], label="Rap Pattern Database (grouped)", wrap=True)

            btn = gr.Button("Search", variant="primary")
            btn.click(
                do_search,
                [word, rhyme_type, slant, syl_min, syl_max, rarity_min],
                [summary_md, out_uncommon, out_slant, out_multi, out_patterns],
            )
            btn.click(
                do_search,
                [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min],
                [summary_md, out_uncommon, out_slant, out_multi, out_patterns],
            )

        with gr.TabItem("Reverse phrase (beta)"):
            rev_phrase = gr.Textbox(label="Phrase (we use the last word)", placeholder="on the table")
            rev_min = gr.Slider(1, 12, value=1, step=1, label="Min syllables")
            rev_max = gr.Slider(1, 12, value=8, step=1, label="Max syllables")
            rev_btn = gr.Button("Find multi-word completions")
            rev_out = gr.Dataframe(headers=["Phrase", "Prosody"], datatype=["str", "str"], label="Multi-word candidates", wrap=True)
            rev_btn.click(do_reverse, [rev_phrase, rev_min, rev_max], [rev_out])

if __name__ == "__main__":
    demo.launch()
