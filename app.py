import gradio as gr
from pathlib import Path
from wordfreq import zipf_frequency

from rhyme_core.search import (
    search_word,
    _get_pron,
    _clean,
    classify_rhyme,
    _final_coda,
    _norm_tail,
)
from rhyme_core.prosody import syllable_count, stress_pattern_str, metrical_name

# Prefer enriched function from patterns; fall back to legacy name if present
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except ImportError:  # legacy name
    from rhyme_core.patterns import find_patterns_by_keys


# -----------------------
# Helpers
# -----------------------

def _rarity(word: str) -> float:
    """Return 0..1 rarity (1 = very rare), based on Zipf frequency."""
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


def _prosody_compact(pron) -> str:
    """Return 'S • Stress • Metre' compact string."""
    p = pron or []
    s = syllable_count(p)
    sp = stress_pattern_str(p) or "—"
    m = metrical_name(sp) if sp and sp != "—" else "—"
    return f"{s} • {sp} • {m}"


def _query_summary(word: str) -> str:
    """One-line summary for the top of the UI."""
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
    """Lightweight highlighter for both target and source in a lyric/context string."""
    if not text:
        return ""
    out = text
    for w in [target or "", source or ""]:
        w = w.strip()
        if not w:
            continue
        # simple case-preserving highlight
        out = out.replace(w, f"▁{w}▁")
        cap = w.capitalize()
        if cap != w:
            out = out.replace(cap, f"▁{cap}▁")
    return out


def _in_syllable_bounds(pron, smin: int, smax: int) -> bool:
    s = syllable_count(pron or [])
    return smin <= s <= smax


def _best_rhyme_choice(query_pron, target_word: str, source_word: str):
    """
    Return the best (quality, word, pron, rtype) among target/source that actually rhyme
    with the query pronunciation per our rules. None if neither rhyme.
    """
    def _qual(rt: str) -> int:
        # strict ordering of quality
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
        # tighten: for assonant/consonant we require the same FINAL CODA (word ending)
        if rt in ("assonant", "consonant"):
            if tuple(_final_coda(query_pron)) != tuple(_final_coda(pr)):
                continue
        choices.append((_qual(rt), w, pr, rt))

    if not choices:
        return None
    choices.sort(reverse=True)  # highest quality first
    return choices[0]  # (qual, word, pron, rtype)


# -----------------------
# Core handler
# -----------------------

def do_search(*args):
    """
    Back-compat handler:
      - 6 args:  word, rhyme_type, slant, syl_min, syl_max, rarity_min
      - 9 args:  word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min
    """
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

    # --- split ---
    slant_list, multiword = [], []
    for r in res:
        rt = (r.get("rhyme_type") or "").lower()
        sc = float(r.get("score", 0.0))
        if rt != "perfect" or sc < 0.999:
            slant_list.append(r)
        if r.get("is_multiword"):
            multiword.append(r)

    # ---- curate “Uncommon” (aim ~20) with adaptive fallback ----
    TARGET_N = 20
    single_word = [r for r in res if not r.get("is_multiword")]

    # All perfects (for fallback), and “rare perfects” per slider
    perfect_all = [r for r in single_word if (r.get("rhyme_type", "").startswith("perfect"))]
    rare_perfects = [r for r in perfect_all if _rarity(r["word"]) >= rarity_min]

    # If not enough rare perfects, fill with the least-common perfects regardless of threshold
    fallback_perfects = []
    if len(rare_perfects) < TARGET_N:
        need = TARGET_N - len(rare_perfects)
        ranked_perfects = sorted(
            perfect_all,
            key=lambda x: (-_rarity(x["word"]), -float(x.get("score", 0.0)), x["word"])
        )
        seen_words = {r["word"] for r in rare_perfects}
        for r in ranked_perfects:
            if r["word"] in seen_words:
                continue
            fallback_perfects.append(r)
            seen_words.add(r["word"])
            if len(fallback_perfects) >= need:
                break

    # If STILL short, allow rare strong assonant/consonant as backfill
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
            key=lambda x: (-_rarity(x["word"]), -float(x.get("score", 0.0)), x["word"])
        )[:need]
        backfill = strong_slants

    # Assemble and de-dup by normalized tail
    curation_pool = rare_perfects + fallback_perfects + backfill

    seen_tails = set()
    curated = []
    for r in sorted(
        curation_pool,
        key=lambda x: (-_rarity(x["word"]), -float(x.get("score", 0.0)), x["word"])
    ):
        tkey = tuple(_norm_tail(r.get("pron") or []))
        if tkey in seen_tails:
            continue
        seen_tails.add(tkey)
        curated.append(r)
        if len(curated) >= TARGET_N:
            break
    uncommon = curated

    # final sorts/caps for other two columns
    slant_list = sorted(slant_list, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50]
    multiword = sorted(multiword, key=lambda x: (-x.get("score", 0.0), x["word"]))[:50]

    # Build row-1 tables (COMPACT): [Word, Prosody] and Slant adds Type
    def as_rows(items, add_type: bool = False):
        rows = []
        for r in items:
            prosody = _prosody_compact(r.get("pron") or [])
            if add_type:
                rows.append([r["word"], prosody, (r.get("rhyme_type") or "")])
            else:
                rows.append([r["word"], prosody])
        return rows

    row1_col1 = as_rows(uncommon)                        # Uncommon Perfect (+rare/least-common/backfill)
    row1_col2 = as_rows(slant_list, add_type=True)       # Slant + Type
    row1_col3 = as_rows(multiword)                       # Multi-word

    # -----------------------
    # Row 2: Patterns DB (compact)
    # -----------------------
    query_for_patterns = (phrase or word).strip()
    patterns_rows = []
    if query_for_patterns:
        try:
            enriched = find_patterns_by_keys(query_for_patterns, limit=int(patterns_limit))

            # use the query WORD pronunciation to compare, not the phrase tail
            query_pr = _get_pron(_clean(word)) or []
            if not query_pr:
                enriched = []

            for d in enriched or []:
                tgt = (d.get("target_rhyme") or d.get("target_word") or "").strip().lower()
                src = (d.get("source_word") or "").strip().lower()

                best = _best_rhyme_choice(query_pr, tgt, src)
                if not best:
                    continue  # neither term rhymes with the query -> drop row

                _, chosen_word, chosen_pr, _rtype = best
                if not _in_syllable_bounds(chosen_pr, int(syl_min), int(syl_max)):
                    continue

                prosody = _prosody_compact(chosen_pr)
                artist = d.get("artist", "")
                song = d.get("song_title", "")

                # highlight BOTH terms in the merged context
                ctx_src = (d.get("lyric_context") or d.get("source_context") or "").strip()
                ctx_tgt = (d.get("target_context") or "").strip()
                context = ctx_src
                if ctx_tgt:
                    context = f"{ctx_src} ⟂ {ctx_tgt}" if ctx_src else ctx_tgt
                context = _mark_ctx(context, tgt, src).replace("\n", " ")
                if len(context) > 140:
                    context = context[:137] + "…"

                patterns_rows.append([chosen_word, prosody, artist, song, context])

        except Exception:
            patterns_rows = []

    # always return summary + three columns + patterns
    return query_summary, row1_col1, row1_col2, row1_col3, patterns_rows


# -----------------------
# UI
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

    # Inputs (9 widgets). We bind both 6-arg and 9-arg signatures for cached clients.
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
        # Default lowered to 0.30 so more perfects show by default
        rarity_min = gr.Slider(0.20, 0.70, value=0.30, step=0.01, label="Rarity ≥ (uncommon filter)")

    summary_md = gr.Markdown("—")  # top summary line

    # Row 1: three compact tables
    with gr.Row():
        out_uncommon = gr.Dataframe(
            headers=["Word", "Prosody"],
            datatype=["str", "str"],
            label="Uncommon Rhymes (curated ~20)",
            wrap=True
        )
        out_slant = gr.Dataframe(
            headers=["Word", "Prosody", "Type"],
            datatype=["str", "str", "str"],
            label="Slant Rhymes",
            wrap=True
        )
        out_multi = gr.Dataframe(
            headers=["Word", "Prosody"],
            datatype=["str", "str"],
            label="Multi-word Rhymes",
            wrap=True
        )

    # Row 2: patterns DB compact
    with gr.Row():
        out_patterns = gr.Dataframe(
            headers=["Word", "Prosody", "Artist", "Song", "Context"],
            datatype=["str", "str", "str", "str", "str"],
            label="Rap Pattern Database",
            wrap=True
        )

    # Bind both 6-arg and 9-arg signatures (compat with cached UIs)
    btn = gr.Button("Search", variant="primary")
    btn.click(
        do_search,
        [word, rhyme_type, slant, syl_min, syl_max, rarity_min],
        [summary_md, out_uncommon, out_slant, out_multi, out_patterns]
    )
    btn.click(
        do_search,
        [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min],
        [summary_md, out_uncommon, out_slant, out_multi, out_patterns]
    )

if __name__ == "__main__":
    demo.launch()
