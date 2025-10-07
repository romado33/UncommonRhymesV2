from pathlib import Path
import logging

import gradio as gr
from wordfreq import zipf_frequency

# Core logic (use the bucketed API)
from rhyme_core.logging_utils import setup_logging
from rhyme_core.search import (
    find_rhymes,
    _get_pron,
    phrase_to_pron,
    stress_pattern_str,
)
from rhyme_core.prosody import (
    syllable_count,
    metrical_name,
)

setup_logging()
log = logging.getLogger(__name__)

_DEFAULT_RHYME_TYPES = ["perfect", "slant", "assonance"]
_RHYME_CHOICE_MAP = {
    "perfect": {"perfect"},
    "slant": {"slant"},
    "assonance": {"assonant"},
    "consonance": {"consonant"},
}

# Patterns DB (returns enriched rows when available)
try:
    from rhyme_core.patterns import find_patterns_by_keys_enriched as find_patterns_by_keys
except Exception:  # pragma: no cover
    from rhyme_core.patterns import find_patterns_by_keys  # type: ignore


# ---------- helpers ----------

def _rarity(word: str) -> float:
    z = zipf_frequency(word, "en")
    z = max(0.0, min(8.0, z))
    return (8.0 - z) / 8.0


def _prosody_str_from_pron(pron):
    p = pron or []
    syls = syllable_count(p)
    stress = stress_pattern_str(p)  # e.g. 1-0 or 1-1-0
    meter = metrical_name(stress) if stress else "—"
    return f"{syls} • {stress or '—'} • {meter}"


def _resolve_rhyme_type_selection(selected) -> tuple[list[str], set[str]]:
    if isinstance(selected, str):
        selected = [selected]
    values = [str(v).lower() for v in (selected or []) if v]
    if not values:
        values = list(_DEFAULT_RHYME_TYPES)
    allowed: set[str] = set()
    for val in values:
        allowed.update(_RHYME_CHOICE_MAP.get(val, set()))
    if not allowed:
        for key in _DEFAULT_RHYME_TYPES:
            allowed.update(_RHYME_CHOICE_MAP.get(key, set()))
    return values, allowed


# ---------- main handler ----------

def do_search(*args):
    """
    Back-compat handler:
      - 6 args:  word, rhyme_type, slant, syl_min, syl_max, rarity_min
      - 7 args:  word, rhyme_type, slant, syl_min, syl_max, rarity_min, rhyme_types
      - 9 args:  word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min
      - 10 args: word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min, rhyme_types
    """
    rhyme_type_selection = _DEFAULT_RHYME_TYPES
    if len(args) == 6:
        word, _rhyme_type, slant, syl_min, syl_max, rarity_min = args
        phrase = ""
        patterns_limit = 50
    elif len(args) == 7:
        word, _rhyme_type, slant, syl_min, syl_max, rarity_min, rhyme_type_selection = args
        phrase = ""
        patterns_limit = 50
    elif len(args) == 9:
        word, phrase, _rhyme_type, slant, syl_min, syl_max, _include_pron, patterns_limit, rarity_min = args
    elif len(args) == 10:
        word, phrase, _rhyme_type, slant, syl_min, syl_max, _include_pron, patterns_limit, rarity_min, rhyme_type_selection = args
    else:  # pragma: no cover
        raise ValueError(f"Unexpected number of inputs: {len(args)}")

    word = (word or "").strip()
    phrase = (phrase or "").strip()  # *** no default text, used only if user enters something ***
    rarity_min = float(rarity_min)
    selected_labels, allowed_rhyme_types = _resolve_rhyme_type_selection(rhyme_type_selection)
    include_consonant = "consonant" in allowed_rhyme_types
    log.debug("Search request word=%s phrase=%s rhyme_types=%s", word, phrase, selected_labels)

    # quick header summary for the query word
    q_pron = _get_pron(word) or phrase_to_pron(word)
    q_syl = syllable_count(q_pron) if q_pron else 0
    q_stress = stress_pattern_str(q_pron) if q_pron else ""
    q_metre = metrical_name(q_stress) if q_stress else "—"
    header_md = f"**{word}** · {q_syl} syllables · stress **{q_stress or '—'}** · metre **{q_metre}**"

    # Use bucketed API directly
    buckets = find_rhymes(
        word,
        max_results=100,
        include_consonant=include_consonant,
    ) if word else {"uncommon": [], "slant": [], "multiword": []}

    # Curate uncommon by rarity threshold (already curated internally; apply final rarity gate)
    uncommon_all = buckets.get("uncommon", [])
    uncommon = []
    for u in uncommon_all:
        disp = (u.get("name") or u.get("phrase") or "").strip()
        if not disp:
            continue
        typ = str(u.get("type") or "perfect").lower()
        if typ not in allowed_rhyme_types:
            continue
        if _rarity(disp) >= rarity_min:
            pr = _get_pron(disp) or phrase_to_pron(disp)
            uncommon.append([disp, _prosody_str_from_pron(pr)])
        if len(uncommon) >= 20:
            break

    # Slant and Multi-word — map to display rows with prosody
    slant_rows = []
    for s in buckets.get("slant", [])[:50]:
        n = (s.get("name") or s.get("phrase") or "").strip()
        if not n:
            continue
        typ = str(s.get("type") or "").lower()
        if typ and typ not in allowed_rhyme_types:
            continue
        pr = _get_pron(n) or phrase_to_pron(n)
        slant_rows.append([n, _prosody_str_from_pron(pr), s.get("type","")])

    multi_rows = []
    for m in buckets.get("multiword", [])[:50]:
        n = (m.get("name") or m.get("phrase") or "").strip()
        if not n:
            continue
        typ = str(m.get("type") or "").lower()
        if typ and typ not in allowed_rhyme_types:
            continue
        pr = _get_pron(n) or phrase_to_pron(n)
        multi_rows.append([n, _prosody_str_from_pron(pr)])

    # Row 2: patterns DB — uses PHRASE if user provided, otherwise WORD
    key_for_patterns = phrase if phrase else word
    patterns_rows = []
    if key_for_patterns:
        try:
            enriched = find_patterns_by_keys(key_for_patterns, limit=int(patterns_limit)) or []
            for d in enriched:
                # pick best display word (target > source)
                w = (d.get("target") or d.get("source") or "").strip()
                pr = _get_pron(w) or phrase_to_pron(w)
                patterns_rows.append([w, _prosody_str_from_pron(pr), d.get("artist",""), d.get("song",""), (d.get("context","") or "")[:400]])
        except Exception:
            patterns_rows = []

    return header_md, uncommon, slant_rows, multi_rows, patterns_rows


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
        rhyme_types = gr.CheckboxGroup(
            label="Include rhyme types",
            choices=["perfect", "slant", "assonance", "consonance"],
            value=list(_DEFAULT_RHYME_TYPES),
        )

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
            [word, rhyme_type, slant, syl_min, syl_max, rarity_min, rhyme_types],
            [header, out_uncommon, out_slant, out_multi, out_patterns],
        )
        btn.click(
            do_search,
            [word, phrase, rhyme_type, slant, syl_min, syl_max, include_pron, patterns_limit, rarity_min, rhyme_types],
            [header, out_uncommon, out_slant, out_multi, out_patterns],
        )

    demo.queue()
    return demo


if __name__ == "__main__":
    build_ui().launch()
